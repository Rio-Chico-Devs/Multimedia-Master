"""
Audio Engine — all business logic, zero UI dependencies.

Dependencies:
  required  : pydub (+ ffmpeg binary in PATH), soundfile, numpy
  optional  : noisereduce (enhance), scipy (EQ), mutagen (tags), demucs (stems)

Every public method returns an AudioResult (or AudioInfo for probe).
Long operations accept an optional progress_cb(float 0‥1) callback.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class AudioInfo:
    path:         Path
    duration_s:   float
    sample_rate:  int
    channels:     int
    format:       str
    bitrate_kbps: int
    file_size:    int
    tags:         dict[str, str] = field(default_factory=dict)


@dataclass
class AudioResult:
    output:     Path | None
    success:    bool
    duration_s: float = 0.0
    file_size:  int   = 0
    error:      str   = ""


# ── Engine ────────────────────────────────────────────────────────────────────

class AudioEngine:
    """Stateless audio processing engine."""

    def __init__(self):
        self._ffmpeg: str | None = shutil.which("ffmpeg")
        if self._ffmpeg:
            try:
                from pydub import AudioSegment
                AudioSegment.converter = self._ffmpeg
            except ImportError:
                pass

    # ── Probe ─────────────────────────────────────────────────────────────

    def probe(self, path: Path) -> AudioInfo:
        """Return metadata for any audio/video file."""
        duration_s   = 0.0
        sample_rate  = 0
        channels     = 1
        tags: dict[str, str] = {}

        # soundfile — fast for PCM-based formats
        try:
            import soundfile as sf
            info        = sf.info(str(path))
            duration_s  = info.duration
            sample_rate = info.samplerate
            channels    = info.channels
        except Exception:
            pass

        # pydub fallback — handles mp3/aac/ogg etc. via ffmpeg
        if duration_s == 0.0:
            try:
                from pydub import AudioSegment
                audio       = AudioSegment.from_file(str(path))
                duration_s  = len(audio) / 1000.0
                sample_rate = audio.frame_rate
                channels    = audio.channels
            except Exception:
                pass

        size = path.stat().st_size if path.exists() else 0
        bitrate_kbps = int((size * 8) / (duration_s * 1000)) if duration_s > 0 else 0

        # Tags via mutagen
        try:
            import mutagen
            mf = mutagen.File(str(path), easy=True)
            if mf:
                for k in ("title", "artist", "album", "date", "tracknumber",
                          "genre", "comment"):
                    v = mf.get(k)
                    if v:
                        tags[k] = str(v[0]) if isinstance(v, (list, tuple)) else str(v)
        except Exception:
            pass

        return AudioInfo(
            path=path,
            duration_s=duration_s,
            sample_rate=sample_rate,
            channels=channels,
            format=path.suffix.lstrip(".").lower(),
            bitrate_kbps=bitrate_kbps,
            file_size=size,
            tags=tags,
        )

    # ── Convert / Compress ────────────────────────────────────────────────

    def convert(
        self,
        src:         Path,
        output:      Path,
        fmt:         str,
        bitrate:     int | None = None,   # kbps
        sample_rate: int | None = None,   # Hz
        channels:    int | None = None,
    ) -> AudioResult:
        """Convert/compress audio to the target format and settings."""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(src))

            if sample_rate:
                audio = audio.set_frame_rate(sample_rate)
            if channels:
                audio = audio.set_channels(channels)

            kw: dict = {"format": fmt}
            if bitrate and fmt not in ("wav", "flac", "aiff"):
                kw["bitrate"] = f"{bitrate}k"

            audio.export(str(output), **kw)
            return self._ok(output, len(audio) / 1000.0)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── Extract audio from video ──────────────────────────────────────────

    def extract_audio(
        self,
        video:       Path,
        output:      Path,
        fmt:         str = "mp3",
        bitrate:     int | None = None,
        sample_rate: int | None = None,
        progress_cb: Callable[[float], None] | None = None,
    ) -> AudioResult:
        """Extract the audio track from any video file using ffmpeg."""
        if not self._ffmpeg:
            return AudioResult(output=output, success=False,
                               error="ffmpeg non trovato. Installalo e aggiungilo al PATH.")
        try:
            cmd = [self._ffmpeg, "-y", "-i", str(video), "-vn"]
            if sample_rate:
                cmd += ["-ar", str(sample_rate)]
            if bitrate and fmt not in ("wav", "flac"):
                cmd += ["-b:a", f"{bitrate}k"]
            cmd.append(str(output))

            proc = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                universal_newlines=True,
            )
            duration_s = 0.0
            for line in (proc.stderr or []):
                if "Duration:" in line and duration_s == 0.0:
                    try:
                        t = line.split("Duration:")[1].split(",")[0].strip()
                        h, m, s = t.split(":")
                        duration_s = int(h) * 3600 + int(m) * 60 + float(s)
                    except Exception:
                        pass
                if "time=" in line and duration_s > 0 and progress_cb:
                    try:
                        t = line.split("time=")[1].split()[0]
                        h, m, s = t.split(":")
                        elapsed = int(h) * 3600 + int(m) * 60 + float(s)
                        progress_cb(min(elapsed / duration_s, 1.0))
                    except Exception:
                        pass
            proc.wait()
            if proc.returncode != 0:
                return AudioResult(output=output, success=False,
                                   error=f"ffmpeg ha restituito codice {proc.returncode}.")
            return self._ok(output, duration_s)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── Enhance (noise reduction + normalize) ─────────────────────────────

    def enhance(
        self,
        src:           Path,
        output:        Path,
        denoise:       bool  = True,
        normalize:     bool  = True,
        prop_decrease: float = 0.75,
        progress_cb:   Callable[[float], None] | None = None,
    ) -> AudioResult:
        """Reduce noise and/or normalize loudness. Requires soundfile + numpy."""
        try:
            import soundfile as sf
            import numpy as np

            data, sr = sf.read(str(src), always_2d=True)  # (frames, ch)
            if progress_cb: progress_cb(0.15)

            if denoise:
                try:
                    import noisereduce as nr
                    data = np.stack(
                        [nr.reduce_noise(y=data[:, c], sr=sr,
                                         prop_decrease=prop_decrease)
                         for c in range(data.shape[1])],
                        axis=1,
                    )
                except ImportError:
                    pass   # skip silently if not installed
            if progress_cb: progress_cb(0.75)

            if normalize:
                peak = np.max(np.abs(data))
                if peak > 1e-6:
                    data = data / peak * 0.95   # -0.45 dBFS headroom

            if progress_cb: progress_cb(0.90)

            # Preserve original format where possible
            fmt_map = {".flac": "flac", ".wav": "WAV", ".ogg": "ogg"}
            out_fmt = fmt_map.get(output.suffix.lower(), "WAV")
            sf.write(str(output), data, sr, format=out_fmt)

            if progress_cb: progress_cb(1.0)
            return self._ok(output, len(data) / sr)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── Trim ──────────────────────────────────────────────────────────────

    def trim(
        self,
        src:      Path,
        output:   Path,
        start_ms: int,
        end_ms:   int,
    ) -> AudioResult:
        """Cut audio to [start_ms, end_ms] range."""
        try:
            from pydub import AudioSegment
            audio  = AudioSegment.from_file(str(src))
            end_ms = min(end_ms, len(audio))
            clip   = audio[start_ms:end_ms]
            fmt    = output.suffix.lstrip(".")
            clip.export(str(output), format=fmt)
            return self._ok(output, len(clip) / 1000.0)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── Volume / Fade ─────────────────────────────────────────────────────

    def adjust(
        self,
        src:         Path,
        output:      Path,
        gain_db:     float = 0.0,
        fade_in_ms:  int   = 0,
        fade_out_ms: int   = 0,
    ) -> AudioResult:
        """Apply volume gain (dB) and optional fade in/out."""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(src))
            if gain_db != 0:
                audio = audio + gain_db
            if fade_in_ms > 0:
                audio = audio.fade_in(fade_in_ms)
            if fade_out_ms > 0:
                audio = audio.fade_out(fade_out_ms)
            fmt = output.suffix.lstrip(".")
            audio.export(str(output), format=fmt)
            return self._ok(output, len(audio) / 1000.0)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── EQ (bass / mid / treble) ──────────────────────────────────────────

    def apply_eq(
        self,
        src:       Path,
        output:    Path,
        bass_db:   float = 0.0,   # gain for <250 Hz
        mid_db:    float = 0.0,   # gain for 250–4000 Hz
        treble_db: float = 0.0,   # gain for >4000 Hz
    ) -> AudioResult:
        """Apply a 3-band shelving EQ using Butterworth filters. Requires scipy."""
        try:
            import soundfile as sf
            import numpy as np
            from scipy.signal import butter, sosfilt

            data, sr = sf.read(str(src), always_2d=True)

            def _gain(db: float) -> float:
                return 10 ** (db / 20.0)

            def _filter(lo: float | None, hi: float | None) -> np.ndarray:
                nyq = sr / 2.0
                if lo is None:
                    sos = butter(4, hi / nyq, btype="low",  output="sos")
                elif hi is None:
                    sos = butter(4, lo / nyq, btype="high", output="sos")
                else:
                    sos = butter(4, [lo / nyq, hi / nyq], btype="band", output="sos")
                return sosfilt(sos, data, axis=0)

            result = (
                _filter(None,  250.0) * _gain(bass_db)
                + _filter(250.0, 4000.0) * _gain(mid_db)
                + _filter(4000.0, None) * _gain(treble_db)
            )

            # Prevent clipping
            peak = np.max(np.abs(result))
            if peak > 1.0:
                result /= peak

            out_fmt = {".flac": "flac", ".wav": "WAV"}.get(output.suffix.lower(), "WAV")
            sf.write(str(output), result, sr, format=out_fmt)
            return self._ok(output, len(data) / float(sr))
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── Speed ─────────────────────────────────────────────────────────────

    def change_speed(
        self,
        src:    Path,
        output: Path,
        speed:  float = 1.0,
    ) -> AudioResult:
        """Change playback speed (pitch follows — use 0.5–2.0 range)."""
        try:
            from pydub import AudioSegment
            audio    = AudioSegment.from_file(str(src))
            new_rate = int(audio.frame_rate * speed)
            sped_up  = audio._spawn(
                audio.raw_data,
                overrides={"frame_rate": new_rate}
            ).set_frame_rate(audio.frame_rate)
            fmt = output.suffix.lstrip(".")
            sped_up.export(str(output), format=fmt)
            return self._ok(output, len(sped_up) / 1000.0)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── Waveform peaks ────────────────────────────────────────────────────

    def get_waveform_peaks(
        self,
        path:        Path,
        num_samples: int = 800,
    ) -> tuple[list[float], list[float]]:
        """
        Return (pos_peaks, neg_peaks) normalised to [0, 1].
        Fast: reads full file once, splits into N chunks, takes max/min per chunk.
        """
        try:
            import soundfile as sf
            import numpy as np

            data, _ = sf.read(str(path), always_2d=False)
            if data.ndim > 1:
                data = data.mean(axis=1)   # mix to mono

            chunks = np.array_split(data, num_samples)
            pos = [float(np.max(c))  if len(c) else 0.0 for c in chunks]
            neg = [float(np.min(c))  if len(c) else 0.0 for c in chunks]

            peak = max(max(abs(v) for v in pos + neg), 1e-6)
            return [v / peak for v in pos], [v / peak for v in neg]
        except Exception:
            return [0.0] * num_samples, [0.0] * num_samples

    # ── Stem separation (demucs) ──────────────────────────────────────────

    def separate_stems(
        self,
        src:         Path,
        output_dir:  Path,
        model:       str = "htdemucs",
        progress_cb: Callable[[str], None] | None = None,
    ) -> list[AudioResult]:
        """
        Separate a track into stems using demucs (external process).
        Outputs to output_dir/<model>/<track_name>/{vocals,drums,bass,other}.wav
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable, "-m", "demucs",
                "--out", str(output_dir),
                "-n",    model,
                str(src),
            ]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
            for line in (proc.stdout or []):
                line = line.strip()
                if line and progress_cb:
                    progress_cb(line)
            proc.wait()

            if proc.returncode != 0:
                return [AudioResult(output=None, success=False,
                                    error=f"demucs error (codice {proc.returncode}).")]

            stem_dir = output_dir / model / src.stem
            results  = [self._ok(f) for f in sorted(stem_dir.glob("*.wav"))
                        if f.is_file()]
            if not results:
                return [AudioResult(output=None, success=False,
                                    error="Nessuno stem trovato nell'output di demucs.")]
            return results
        except Exception as exc:
            return [AudioResult(output=None, success=False, error=str(exc))]

    # ── Metadata / Tags ───────────────────────────────────────────────────

    def read_tags(self, path: Path) -> dict[str, str]:
        """Read ID3/Vorbis/MP4/FLAC tags. Returns empty dict on failure."""
        try:
            import mutagen
            mf = mutagen.File(str(path), easy=True)
            if not mf:
                return {}
            result: dict[str, str] = {}
            for k in ("title", "artist", "album", "date",
                      "tracknumber", "genre", "comment"):
                v = mf.get(k)
                if v:
                    result[k] = str(v[0]) if isinstance(v, (list, tuple)) else str(v)
            return result
        except Exception:
            return {}

    def write_tags(
        self,
        path:     Path,
        tags:     dict[str, str],
        art_path: Path | None = None,
    ) -> AudioResult:
        """Write tags and optionally embed album art. Modifies file in place."""
        try:
            import mutagen
            mf = mutagen.File(str(path), easy=True)
            if not mf:
                return AudioResult(output=path, success=False,
                                   error="Formato non supportato da mutagen.")
            for k, v in tags.items():
                if v.strip():
                    mf[k] = [v.strip()]
                elif k in mf:
                    del mf[k]
            mf.save()

            if art_path and art_path.is_file():
                self._embed_art(path, art_path)

            return AudioResult(output=path, success=True)
        except Exception as exc:
            return AudioResult(output=path, success=False, error=str(exc))

    def _embed_art(self, audio_path: Path, art_path: Path) -> None:
        """Embed album art using format-specific mutagen API."""
        raw  = art_path.read_bytes()
        mime = ("image/jpeg" if art_path.suffix.lower() in (".jpg", ".jpeg")
                else "image/png")
        ext  = audio_path.suffix.lower()

        if ext == ".mp3":
            from mutagen.id3 import ID3, APIC
            try:
                tags = ID3(str(audio_path))
            except Exception:
                tags = ID3()
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=raw))
            tags.save(str(audio_path))

        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover
            tags = MP4(str(audio_path))
            fmt  = (MP4Cover.FORMAT_JPEG if "jpeg" in mime else MP4Cover.FORMAT_PNG)
            tags["covr"] = [MP4Cover(raw, imageformat=fmt)]
            tags.save()

        elif ext == ".flac":
            from mutagen.flac import FLAC, Picture
            tags    = FLAC(str(audio_path))
            pic     = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = raw
            tags.clear_pictures()
            tags.add_picture(pic)
            tags.save()

        elif ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            import base64
            from mutagen.flac import Picture
            tags    = OggVorbis(str(audio_path))
            pic     = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = raw
            tags["metadata_block_picture"] = [
                base64.b64encode(pic.write()).decode("ascii")]
            tags.save()

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _ok(output: Path, duration_s: float = 0.0) -> AudioResult:
        size = output.stat().st_size if output.exists() else 0
        return AudioResult(output=output, success=True,
                           duration_s=duration_s, file_size=size)
