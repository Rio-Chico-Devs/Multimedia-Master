"""
Audio Engine — all business logic, zero UI dependencies.

Dependencies:
  required  : pydub, soundfile, numpy
  ffmpeg    : resolved automatically — system PATH first, then imageio-ffmpeg
              (pip install imageio-ffmpeg) so no manual install is needed
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
        self._ffmpeg: str | None = self._find_ffmpeg()
        if self._ffmpeg:
            try:
                from pydub import AudioSegment
                AudioSegment.converter = self._ffmpeg
                # ffprobe: imageio-ffmpeg ships only ffmpeg, not ffprobe.
                # pydub can fall back to ffmpeg -i for metadata, so leave
                # ffprobe unset rather than pointing to a non-existent path.
            except ImportError:
                pass

    @staticmethod
    def _find_ffmpeg() -> str | None:
        """
        Locate ffmpeg in order of preference:
          1. imageio-ffmpeg bundled binary  (pip install imageio-ffmpeg)
          2. System PATH  (fallback if imageio-ffmpeg is not installed)
        Returns the full path string or None if neither is available.
        """
        # 1 — imageio-ffmpeg (bundled static build, no system install needed)
        try:
            import imageio_ffmpeg
            path = imageio_ffmpeg.get_ffmpeg_exe()
            if path:
                return path
        except Exception:
            pass
        # 2 — system PATH fallback
        return shutil.which("ffmpeg")

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

        # ffmpeg fallback — handles mp3/aac/ogg etc. without needing ffprobe
        if duration_s == 0.0 and self._ffmpeg:
            try:
                result = subprocess.run(
                    [self._ffmpeg, "-i", str(path)],
                    stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    encoding="utf-8", errors="replace",
                )
                for line in result.stderr.splitlines():
                    if "Duration:" in line and duration_s == 0.0:
                        try:
                            t = line.split("Duration:")[1].split(",")[0].strip()
                            h, m, s = t.split(":")
                            duration_s = int(h) * 3600 + int(m) * 60 + float(s)
                        except Exception:
                            pass
                    if "Stream" in line and "Audio:" in line:
                        try:
                            parts = line.split("Audio:")[1].split(",")
                            if not sample_rate:
                                for p in parts:
                                    p = p.strip()
                                    if "Hz" in p:
                                        sample_rate = int(p.split()[0])
                                        break
                            if not channels:
                                for p in parts:
                                    if "stereo" in p.lower():
                                        channels = 2
                                    elif "mono" in p.lower():
                                        channels = 1
                        except Exception:
                            pass
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
        """Convert/compress audio to the target format using ffmpeg directly."""
        if not self._ffmpeg:
            return AudioResult(output=output, success=False,
                               error="ffmpeg non trovato. Esegui: pip install imageio-ffmpeg")
        try:
            cmd = [self._ffmpeg, "-y", "-i", str(src)]
            if sample_rate:
                cmd += ["-ar", str(sample_rate)]
            if channels:
                cmd += ["-ac", str(channels)]
            if bitrate and fmt not in ("wav", "flac", "aiff"):
                cmd += ["-b:a", f"{bitrate}k"]
            cmd.append(str(output))

            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                # Return last 300 chars of stderr for a useful error message
                err = proc.stderr.strip()[-300:] if proc.stderr else "Errore sconosciuto"
                return AudioResult(output=output, success=False, error=err)
            return self._ok(output)
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
                encoding="utf-8",
                errors="replace",
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
                encoding="utf-8",
                errors="replace",
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

    def strip_tags(self, path: Path) -> AudioResult:
        """Remove ALL metadata tags from the file (modifies in place)."""
        try:
            import mutagen
            mf = mutagen.File(str(path))
            if not mf:
                return AudioResult(output=path, success=False,
                                   error="Formato non supportato da mutagen.")
            if mf.tags:
                mf.tags.clear()
                mf.save()
            return AudioResult(output=path, success=True)
        except Exception as exc:
            return AudioResult(output=path, success=False, error=str(exc))

    def analyze_file(self, path: Path) -> dict:
        """
        Health and safety analysis of an audio file.
        Returns {"safe": bool, "issues": list[str], "details": list[str]}
        """
        issues:  list[str] = []
        details: list[str] = []

        # 1 — File size sanity
        try:
            size = path.stat().st_size
            if size == 0:
                issues.append("File vuoto (0 byte)")
            elif size < 512:
                issues.append(f"File sospettosamente piccolo ({size} byte)")
            else:
                details.append(f"Dimensione: {size / 1024:.1f} KB")
        except Exception as e:
            issues.append(f"Impossibile leggere il file: {e}")

        # 2 — Magic bytes vs extension
        _MAGIC: dict[str, list[tuple[int, bytes]]] = {
            ".mp3":  [(0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xfa"),
                      (0, b"\xff\xf3"), (0, b"\xff\xf2")],
            ".flac": [(0, b"fLaC")],
            ".ogg":  [(0, b"OggS")],
            ".opus": [(0, b"OggS")],
            ".wav":  [(0, b"RIFF")],
            ".m4a":  [(4, b"ftyp")],
            ".mp4":  [(4, b"ftyp")],
            ".aac":  [(0, b"\xff\xf1"), (0, b"\xff\xf9")],
        }
        try:
            header = path.read_bytes()[:12]
            ext    = path.suffix.lower()
            checks = _MAGIC.get(ext, [])
            if checks:
                ok = any(header[off:off + len(sig)] == sig
                         for off, sig in checks)
                if ok:
                    details.append("Intestazione file corretta")
                else:
                    issues.append(
                        f"Intestazione non corrisponde all'estensione {ext} "
                        "(il file potrebbe essere rinominato o corrotto)")
        except Exception as e:
            issues.append(f"Impossibile leggere l'intestazione: {e}")

        # 3 — Full decode check via ffmpeg
        if self._ffmpeg:
            try:
                res = subprocess.run(
                    [self._ffmpeg, "-v", "error", "-i", str(path),
                     "-f", "null", "-"],
                    stderr=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    encoding="utf-8", errors="replace",
                    timeout=60,
                )
                if res.returncode == 0:
                    details.append("Decodifica ffmpeg: nessun errore")
                else:
                    stderr = (res.stderr or "").strip()
                    snippet = stderr[-300:] if len(stderr) > 300 else stderr
                    issues.append(f"Errori di decodifica: {snippet}")
            except subprocess.TimeoutExpired:
                issues.append("Timeout verifica — file potenzialmente corrotto")
            except Exception as e:
                issues.append(f"Errore durante la verifica: {e}")
        else:
            details.append("ffmpeg non disponibile — verifica decodifica saltata")

        # 4 — Tag content safety
        try:
            import mutagen
            mf = mutagen.File(str(path), easy=True)
            if mf and mf.tags:
                n = len(mf.tags)
                details.append(f"Tag presenti: {n}")
                for key, value in mf.tags.items():
                    v = str(value[0]) if isinstance(value, (list, tuple)) else str(value)
                    if len(v) > 1000:
                        issues.append(
                            f"Tag '{key}' insolitamente lungo ({len(v)} caratteri)")
                    lower = v.lower()
                    if any(x in lower for x in
                           ("javascript:", "<script", "vbscript:")):
                        issues.append(
                            f"Tag '{key}' contiene contenuto script: {v[:80]}")
                    elif any(x in lower for x in ("http://", "https://")):
                        details.append(f"Tag '{key}' contiene URL (non pericoloso)")
            else:
                details.append("Nessun tag trovato")
        except Exception as e:
            details.append(f"Lettura tag non disponibile: {e}")

        return {
            "safe":    len(issues) == 0,
            "issues":  issues,
            "details": details,
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _ok(output: Path, duration_s: float = 0.0) -> AudioResult:
        size = output.stat().st_size if output.exists() else 0
        return AudioResult(output=output, success=True,
                           duration_s=duration_s, file_size=size)
