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
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ── ID3 frame → (display_name, category) ─────────────────────────────────────
# category: standard | technical | history | hidden | custom | art | info
_ID3_INFO: dict[str, tuple[str, str]] = {
    "TIT2": ("Titolo",                        "standard"),
    "TIT1": ("Raggruppamento",                "standard"),
    "TIT3": ("Sottotitolo / Versione",        "standard"),
    "TPE1": ("Artista",                       "standard"),
    "TPE2": ("Artista album",                 "standard"),
    "TPE3": ("Direttore / Presentatore",      "standard"),
    "TALB": ("Album",                         "standard"),
    "TRCK": ("N° traccia",                    "standard"),
    "TPOS": ("N° disco",                      "standard"),
    "TCON": ("Genere",                        "standard"),
    "TDRC": ("Data registrazione",            "standard"),
    "TDRL": ("Data rilascio",                 "standard"),
    "COMM": ("Commento",                      "standard"),
    "USLT": ("Lyrics",                        "standard"),
    "TCOM": ("Compositore",                   "standard"),
    "TEXT": ("Autore testo",                  "standard"),
    "TPUB": ("Publisher / Etichetta",         "standard"),
    "TCOP": ("Copyright",                     "standard"),
    "TLAN": ("Lingua",                        "standard"),
    "TBPM": ("BPM",                           "standard"),
    "TKEY": ("Tonalità",                      "standard"),
    "TSRC": ("ISRC",                          "standard"),
    "TMOO": ("Mood / Atmosfera",              "standard"),
    "TPRO": ("Prodotto (℗)",                  "standard"),
    "TRSN": ("Stazione radio",                "standard"),
    # Technical
    "TENC": ("Codificato da (software)",      "technical"),
    "TSSE": ("Impostazioni encoder",          "technical"),
    "TFLT": ("Tipo file audio",               "technical"),
    "TMED": ("Supporto originale",            "technical"),
    "TLEN": ("Durata dichiarata (ms)",        "technical"),
    "WOAS": ("URL sorgente audio",            "technical"),
    "WCOM": ("URL info commerciali",          "technical"),
    "WCOP": ("URL copyright",                 "technical"),
    # History / Provenance
    "TDTG": ("⏱ Data scrittura tag",          "history"),
    "TOFN": ("Nome file originale",           "history"),
    "TOAL": ("Album originale",               "history"),
    "TOPE": ("Artista originale",             "history"),
    "TDOR": ("Data pubblicazione originale",  "history"),
    "TOWN": ("Proprietario / Licenziatario",  "history"),
    "TPE4": ("Remixato / modificato da",      "history"),
    # Custom
    "TXXX": ("Tag personalizzato",            "custom"),
    "WXXX": ("URL personalizzato",            "custom"),
    # Art
    "APIC": ("Copertina album",               "art"),
    # Hidden / Private
    "PRIV": ("Dati privati",                  "hidden"),
    "UFID": ("ID univoco file",               "hidden"),
    "GEOB": ("Oggetto incapsulato",           "hidden"),
    "COMR": ("Frame commerciale",             "hidden"),
    "ENCR": ("Metodo cifratura",              "hidden"),
    "AENC": ("Cifratura audio",               "hidden"),
    "RVA2": ("Aggiust. volume",               "hidden"),
    "RVRB": ("Riverbero",                     "hidden"),
    "SIGN": ("Firma gruppo",                  "hidden"),
    "OWNE": ("Frame proprietà",               "hidden"),
    "USER": ("Termini d'uso",                 "hidden"),
    "SYLT": ("Testo sincronizzato",           "hidden"),
    "ETCO": ("Codici evento",                 "hidden"),
    "POSS": ("Sincronizz. posizione",         "hidden"),
}

_MP4_INFO: dict[str, tuple[str, str]] = {
    "©nam": ("Titolo",                        "standard"),
    "©ART": ("Artista",                       "standard"),
    "©alb": ("Album",                         "standard"),
    "aART": ("Artista album",                 "standard"),
    "©day": ("Anno",                          "standard"),
    "trkn": ("N° traccia",                    "standard"),
    "disk": ("N° disco",                      "standard"),
    "©gen": ("Genere",                        "standard"),
    "©cmt": ("Commento",                      "standard"),
    "©wrt": ("Compositore",                   "standard"),
    "©lyr": ("Lyrics",                        "standard"),
    "cprt": ("Copyright",                     "standard"),
    "©too": ("⏱ Encoder / Tool creazione",    "history"),
    "soal": ("Ordinamento album",             "technical"),
    "soar": ("Ordinamento artista",           "technical"),
    "sonm": ("Ordinamento titolo",            "technical"),
    "tvsh": ("Show TV",                       "technical"),
    "tves": ("Episodio TV",                   "technical"),
    "covr": ("Copertina album",               "art"),
    "pgap": ("Gapless playback",              "technical"),
}

_VORBIS_STANDARD = {
    "title", "artist", "album", "date", "tracknumber", "genre",
    "comment", "albumartist", "composer", "lyrics", "description",
    "discnumber", "isrc", "copyright", "language", "bpm",
}


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

    def deep_read_tags(self, path: Path) -> list[dict]:
        """
        Read ALL metadata down to frame/atom level.
        Returns a list of field dicts:
          raw_key, display_name, value, category, editable, deletable, warning
        Categories: standard | technical | history | hidden | custom | art | info
        """
        ext = path.suffix.lower()
        fields: list[dict] = []
        try:
            if ext == ".mp3":
                fields = self._deep_id3(path)
            elif ext == ".flac":
                fields = self._deep_flac(path)
            elif ext in (".ogg", ".opus"):
                fields = self._deep_ogg(path)
            elif ext in (".m4a", ".mp4", ".aac"):
                fields = self._deep_mp4(path)
            else:
                import mutagen
                mf = mutagen.File(str(path), easy=False)
                if mf and mf.tags:
                    for k, v in mf.tags.items():
                        fields.append(self._field(k, k, str(v), "custom"))

            # File-level technical info (read-only)
            try:
                import mutagen
                mf = mutagen.File(str(path))
                if mf:
                    info = mf.info
                    for attr, label in [
                        ("length",          "Durata (s)"),
                        ("bitrate",         "Bitrate (bps)"),
                        ("sample_rate",     "Sample rate (Hz)"),
                        ("channels",        "Canali"),
                        ("bits_per_sample", "Bit per campione"),
                        ("encoder_info",    "⏱ Info encoder (stream)"),
                        ("encoder_settings","⏱ Impostazioni encoder (stream)"),
                        ("codec",           "Codec"),
                    ]:
                        val = getattr(info, attr, None)
                        if val is not None and str(val).strip():
                            w = ("Rilevabile nel flusso audio — non rimovibile senza ri-codifica"
                                 if "encoder" in attr else "")
                            fields.append(self._field(
                                f"_info_{attr}", label, str(val),
                                "history" if "encoder" in attr else "info",
                                editable=False, deletable=False, warning=w))
            except Exception:
                pass
        except Exception as e:
            fields.append(self._field("_err", "Errore lettura", str(e),
                                      "info", editable=False, deletable=False))
        return fields

    def _field(self, raw_key: str, display_name: str, value: str,
               category: str, editable: bool = True,
               deletable: bool = True, warning: str = "") -> dict:
        if not warning:
            if category == "history":
                warning = "Rivela la storia / provenienza del file"
            elif category == "hidden":
                warning = "Dato non standard — possibile traccia identificativa"
        return {
            "raw_key": raw_key, "display_name": display_name,
            "value": value, "category": category,
            "editable": editable, "deletable": deletable, "warning": warning,
        }

    def _deep_id3(self, path: Path) -> list[dict]:
        from mutagen.id3 import ID3, ID3NoHeaderError
        fields = []
        try:
            try:
                tags = ID3(str(path))
            except ID3NoHeaderError:
                return []
            ver = f"ID3 v2.{tags.version[1]}.{tags.version[2]}"
            fields.append(self._field("_id3ver", "Versione ID3", ver,
                                      "info", editable=False, deletable=False))
            for key in sorted(tags.keys()):
                frame = tags[key]
                base  = key[:4]
                dname, cat = _ID3_INFO.get(base, (f"Frame {base}", "custom"))
                # TXXX includes description
                if base == "TXXX" and hasattr(frame, "desc") and frame.desc:
                    dname = f"Tag personalizzato: {frame.desc}"
                # Value extraction
                if base == "APIC":
                    data = getattr(frame, "data", b"")
                    val  = (f"[{getattr(frame,'mime','?')}  "
                            f"{len(data)//1024} KB]")
                    edit, dele = False, True
                elif base in ("PRIV", "GEOB", "ENCR", "AENC"):
                    data = getattr(frame, "data", b"")
                    val  = f"[binario {len(data)} B]  {data[:16].hex()}"
                    edit, dele = False, True
                elif hasattr(frame, "text") and frame.text:
                    val  = str(frame.text[0])
                    edit, dele = True, True
                else:
                    val  = str(frame)
                    edit, dele = False, True
                warn = ("Rilevabile nel flusso audio" if base == "TSSE"
                        else "")
                fields.append(self._field(key, dname, val, cat,
                                          editable=edit, deletable=dele,
                                          warning=warn))
        except Exception:
            pass
        return fields

    def _deep_flac(self, path: Path) -> list[dict]:
        from mutagen.flac import FLAC
        fields = []
        try:
            audio = FLAC(str(path))
            # Vendor string — history
            if audio.tags and hasattr(audio.tags, "vendor"):
                v = audio.tags.vendor or ""
                fields.append(self._field(
                    "_vendor", "⏱ Vendor string (encoder)",
                    v, "history", editable=False, deletable=False,
                    warning="Rilevabile nel contenitore FLAC — non rimovibile senza ri-codifica"))
            if audio.tags:
                for key, values in audio.tags.as_dict().items():
                    val = "; ".join(str(v) for v in values)
                    cat = "standard" if key.lower() in _VORBIS_STANDARD else "custom"
                    fields.append(self._field(key, key.capitalize(), val, cat))
            if audio.pictures:
                for pic in audio.pictures:
                    fields.append(self._field(
                        "_flac_pic", "Copertina album",
                        f"[{pic.mime}  {len(pic.data)//1024} KB]",
                        "art", editable=False))
        except Exception:
            pass
        return fields

    def _deep_ogg(self, path: Path) -> list[dict]:
        fields = []
        try:
            ext = path.suffix.lower()
            if ext == ".opus":
                from mutagen.oggopus import OggOpus as Cls
            else:
                from mutagen.oggvorbis import OggVorbis as Cls
            audio = Cls(str(path))
            if audio.tags and hasattr(audio.tags, "vendor"):
                v = audio.tags.vendor or ""
                fields.append(self._field(
                    "_vendor", "⏱ Vendor string (encoder)",
                    v, "history", editable=False, deletable=False,
                    warning="Rilevabile nel flusso — non rimovibile senza ri-codifica"))
            if audio.tags:
                for key, values in audio.tags.as_dict().items():
                    val = "; ".join(str(v) for v in values)
                    cat = "standard" if key.lower() in _VORBIS_STANDARD else "custom"
                    fields.append(self._field(key, key.capitalize(), val, cat))
        except Exception:
            pass
        return fields

    def _deep_mp4(self, path: Path) -> list[dict]:
        fields = []
        try:
            from mutagen.mp4 import MP4
            audio = MP4(str(path))
            if audio.tags:
                for key, value in audio.tags.items():
                    dname, cat = _MP4_INFO.get(
                        key[:4] if key.startswith("----") else key,
                        (f"Atom {key}", "hidden" if key.startswith("----") else "custom"))
                    if key.startswith("----"):
                        # custom iTunes atoms — often contain hidden data
                        raw = value[0] if value else b""
                        val = (raw.decode("utf-8", errors="replace")
                               if isinstance(raw, bytes) else str(raw))
                        warn = "Atom proprietario Apple/iTunes — possibile dato identificativo"
                        fields.append(self._field(key, f"Atom: {key}", val,
                                                   "hidden", editable=False,
                                                   warning=warn))
                        continue
                    if key == "covr":
                        val  = f"[immagine  {len(value[0])//1024 if value else 0} KB]"
                        edit = False
                    elif isinstance(value, list):
                        val  = str(value[0]) if value else ""
                        edit = True
                    else:
                        val  = str(value)
                        edit = True
                    fields.append(self._field(key, dname, val, cat, editable=edit))
        except Exception:
            pass
        return fields

    def save_meta_changes(
        self,
        path:      Path,
        changes:   dict[str, str],   # raw_key → new value
        deletions: set[str],         # raw_keys to remove
    ) -> AudioResult:
        """Write edited fields and remove deleted ones. Modifies file in place."""
        try:
            import mutagen
            ext = path.suffix.lower()

            if ext == ".mp3":
                from mutagen.id3 import ID3, ID3NoHeaderError
                try:
                    tags = ID3(str(path))
                except ID3NoHeaderError:
                    tags = ID3()
                # Deletions
                for key in deletions:
                    if not key.startswith("_") and key in tags:
                        del tags[key]
                # Changes — use easy interface for standard fields
                mf_easy = mutagen.File(str(path), easy=True)
                if mf_easy:
                    _easy_map = {
                        "TIT2": "title", "TPE1": "artist", "TALB": "album",
                        "TDRC": "date",  "TRCK": "tracknumber", "TCON": "genre",
                        "COMM": "comment",
                    }
                    for raw_key, val in changes.items():
                        if raw_key.startswith("_"):
                            continue
                        easy_key = _easy_map.get(raw_key[:4])
                        if easy_key and mf_easy:
                            if val:
                                mf_easy[easy_key] = [val]
                            elif easy_key in mf_easy:
                                del mf_easy[easy_key]
                    mf_easy.save()
                else:
                    tags.save(str(path))

            elif ext == ".flac":
                from mutagen.flac import FLAC
                audio = FLAC(str(path))
                if audio.tags is None:
                    audio.add_tags()
                for key in deletions:
                    if not key.startswith("_") and key in audio.tags:
                        del audio.tags[key]
                for key, val in changes.items():
                    if key.startswith("_"):
                        continue
                    if val:
                        audio.tags[key] = [val]
                    elif key in audio.tags:
                        del audio.tags[key]
                audio.save()

            elif ext in (".ogg", ".opus"):
                if ext == ".opus":
                    from mutagen.oggopus import OggOpus as Cls
                else:
                    from mutagen.oggvorbis import OggVorbis as Cls
                audio = Cls(str(path))
                if audio.tags is None:
                    audio.add_tags()
                for key in deletions:
                    if not key.startswith("_") and key in audio.tags:
                        del audio.tags[key]
                for key, val in changes.items():
                    if key.startswith("_"):
                        continue
                    if val:
                        audio.tags[key] = [val]
                    elif key in audio.tags:
                        del audio.tags[key]
                audio.save()

            elif ext in (".m4a", ".mp4"):
                from mutagen.mp4 import MP4
                audio = MP4(str(path))
                if audio.tags is None:
                    audio.add_tags()
                for key in deletions:
                    if not key.startswith("_") and key in audio.tags:
                        del audio.tags[key]
                for key, val in changes.items():
                    if key.startswith("_") or key.startswith("----"):
                        continue
                    if val:
                        audio.tags[key] = [val]
                    elif key in audio.tags:
                        del audio.tags[key]
                audio.save()

            else:
                mf = mutagen.File(str(path), easy=True)
                if mf:
                    for k in deletions:
                        if not k.startswith("_") and k in mf:
                            del mf[k]
                    for k, v in changes.items():
                        if k.startswith("_"):
                            continue
                        if v:
                            mf[k] = [v]
                        elif k in mf:
                            del mf[k]
                    mf.save()

            return AudioResult(output=path, success=True)
        except Exception as exc:
            return AudioResult(output=path, success=False, error=str(exc))

    def forensic_wipe(self, path: Path) -> AudioResult:
        """
        Remove ALL metadata traces (modifies file in place).
        Step 1 — ffmpeg remux with -map_metadata -1 (strips container metadata)
        Step 2 — mutagen clear any remaining tags
        Note: encoder fingerprints embedded IN the audio stream (LAME header,
        FLAC STREAMINFO encoder field, OGG vendor string) cannot be removed
        without re-encoding, which would degrade quality in lossy formats.
        """
        tmp = Path(tempfile.mktemp(suffix=path.suffix))
        try:
            if self._ffmpeg:
                res = subprocess.run(
                    [self._ffmpeg, "-y", "-i", str(path),
                     "-map_metadata", "-1",
                     "-map_chapters", "-1",
                     "-c:a", "copy",
                     str(tmp)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace",
                )
                if res.returncode != 0:
                    return AudioResult(
                        output=path, success=False,
                        error=f"ffmpeg: {(res.stderr or '').strip()[-200:]}")
            else:
                shutil.copy2(str(path), str(tmp))

            # Second pass: mutagen strip
            try:
                import mutagen
                mf = mutagen.File(str(tmp))
                if mf and mf.tags:
                    mf.tags.clear()
                    mf.save()
            except Exception:
                pass

            shutil.move(str(tmp), str(path))
            return AudioResult(output=path, success=True)
        except Exception as exc:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            return AudioResult(output=path, success=False, error=str(exc))

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
