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

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


# ── Safe tempfile helper ─────────────────────────────────────────────────────
# `tempfile.mktemp()` is deprecated (race condition + symlink attack surface).
# `mkstemp` atomically creates the file with 0600 permissions; we close the fd
# and return the Path. Callers are responsible for `unlink(missing_ok=True)`.

def safe_tempfile(suffix: str = "") -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(name)

# ── Creative voice-effect filter chains (all via ffmpeg) ─────────────────────
# Each entry: key → (human description, ffmpeg -af filter chain)
# Pitch shifts use asetrate+aresample+atempo so duration is preserved.
#   Lower pitch by factor F:  asetrate=int(44100*F), aresample=44100, atempo=1/F
#   Raise pitch by factor F:  asetrate=int(44100*F), aresample=44100, atempo=1/F
# atempo accepts [0.5, 2.0]; all chosen F values stay within that range.

VOICE_EFFECTS: dict[str, tuple[str, str]] = {
    "robot": (
        "🤖 Robotica  —  modulazione ad anello (AM 60 Hz) + eco metallico + phaser",
        # AM modulation at 60 Hz via tremolo simulates ring-modulator "buzz".
        # Heavy compressor first to flatten dynamics, making the modulation audible.
        # threshold=0.056 ≈ -25 dBFS (linear); makeup=2.51 ≈ +8 dB (linear).
        "acompressor=threshold=0.056:ratio=20:attack=5:release=100:makeup=2.51,"
        "tremolo=f=60:d=0.9,"
        "aphaser=in_gain=0.4:out_gain=0.74:delay=3:decay=0.4:speed=0.5:type=t,"
        "aecho=1:0.8:15|30:0.5|0.3,"
        "alimiter=level_out=0.9",
    ),
    "evil": (
        "😈 Malvagia  —  -8 semitoni, EQ scuro, riverbero abissale",
        # -8 semitones: F = 2^(-8/12) = 0.6300 → asetrate=27783, atempo=1.587
        "asetrate=27783,aresample=44100,atempo=1.587,"
        "lowpass=f=8000,bass=g=6,treble=g=-6,"
        "aecho=0.9:0.9:1200|2000|3000:0.4|0.3|0.2,"
        # threshold=0.1 ≈ -20 dBFS; makeup=1.41 ≈ +3 dB (linear, not dB string).
        "acompressor=threshold=0.1:ratio=4:attack=5:release=200:makeup=1.41,"
        "alimiter=level_out=0.9",
    ),
    "zombie": (
        "🧟 Zombie  —  -7 semitoni, bitcrusher, tremolo lento, riverbero decadente",
        # -7 semitones: F = 2^(-7/12) = 0.6674 → asetrate=29433, atempo=1.498
        "asetrate=29433,aresample=44100,atempo=1.498,"
        "acrusher=level_in=4:level_out=0.5:bits=14:mode=log:aa=1,"
        "tremolo=f=5:d=0.6,"
        "bass=g=3,"
        "aecho=0.8:0.85:400|800|1500:0.3|0.2|0.1,"
        "alimiter=level_out=0.9",
    ),
    "psychic": (
        "🌀 Telecinesi  —  +3 semitoni, vibrato, riverbero enorme, phaser etereo",
        # +3 semitones: F = 2^(3/12) = 1.1892 → asetrate=52444, atempo=0.841
        "asetrate=52444,aresample=44100,atempo=0.841,"
        "vibrato=f=3:d=0.3,"
        "aphaser=in_gain=0.6:out_gain=0.8:delay=3:decay=0.5:speed=0.3:type=q,"
        "aecho=0.95:0.95:500|1000|2000|3500:0.5|0.4|0.3|0.2,"
        "treble=g=2,"
        "alimiter=level_out=0.9",
    ),
    "chibi": (
        "🎀 Chibi  —  +8 semitoni, EQ brillante, chorus doppio kawaii",
        # +8 semitones: F = 2^(8/12) = 1.5874 → asetrate=70004, atempo=0.630
        "asetrate=70004,aresample=44100,atempo=0.630,"
        "treble=g=5,highpass=f=100,"
        "chorus=0.8:0.9:40|55:0.3|0.25:0.3|0.4:1.5|2,"
        "volume=1.5,"
        "alimiter=level_out=0.9",
    ),
    "virtual": (
        "👾 Ragazza virtuale  —  +5 semitoni, flanger digitale, chorus anime",
        # +5 semitones: F = 2^(5/12) = 1.3348 → asetrate=58867, atempo=0.749
        "asetrate=58867,aresample=44100,atempo=0.749,"
        "treble=g=3,"
        "flanger=delay=0:depth=3:speed=0.8:width=60:phase=25:shape=sinusoidal:interp=linear,"
        "chorus=0.6:0.9:45|60:0.3|0.25:0.25|0.35:1.5|2,"
        "alimiter=level_out=0.9",
    ),
}

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

# ID3v1 genre list (Winamp standard)
_ID3V1_GENRES = [
    "Blues","Classic Rock","Country","Dance","Disco","Funk","Grunge","Hip-Hop",
    "Jazz","Metal","New Age","Oldies","Other","Pop","R&B","Rap","Reggae","Rock",
    "Techno","Industrial","Alternative","Ska","Death Metal","Pranks","Soundtrack",
    "Euro-Techno","Ambient","Trip-Hop","Vocal","Jazz+Funk","Fusion","Trance",
    "Classical","Instrumental","Acid","House","Game","Sound Clip","Gospel","Noise",
    "Alt. Rock","Bass","Soul","Punk","Space","Meditative","Instrumental Pop",
    "Instrumental Rock","Ethnic","Gothic","Darkwave","Techno-Industrial","Electronic",
    "Pop-Folk","Eurodance","Dream","Southern Rock","Comedy","Cult","Gangsta Rap",
    "Top 40","Christian Rap","Pop/Funk","Jungle","Native American","Cabaret",
    "New Wave","Psychedelic","Rave","Showtunes","Trailer","Lo-Fi","Tribal",
    "Acid Punk","Acid Jazz","Polka","Retro","Musical","Rock & Roll","Hard Rock",
]

# MPEG side-info sizes: key=(mpeg_version_bits, channel_mode_bits)
_MPEG_SIDE_INFO: dict[tuple[int,int], int] = {
    (3,3):17, (3,2):32, (3,1):32, (3,0):32,  # MPEG1
    (2,3): 9, (2,2):17, (2,1):17, (2,0):17,  # MPEG2
    (0,3): 9, (0,2):17, (0,1):17, (0,0):17,  # MPEG2.5
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
                    timeout=15,
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
        proc: subprocess.Popen | None = None
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
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    try: proc.kill()
                    except Exception: pass

    # ── Enhance (noise reduction + normalize) ─────────────────────────────

    def enhance(
        self,
        src:           Path,
        output:        Path,
        denoise:       bool  = True,
        normalize:     bool  = True,
        highpass:      bool  = True,
        eq_presence:   bool  = True,
        compress:      bool  = True,
        prop_decrease: float = 0.75,
        progress_cb:   Callable[[float], None] | None = None,
    ) -> AudioResult:
        """Professional voice-enhancement pipeline.

        Steps (each independently togglable):
          1. Spectral-gating noise reduction  (noisereduce)
          2. High-pass filter 80 Hz           (ffmpeg – rumble removal)
          3. Presence EQ: -2 dB@300 Hz / +2.5 dB@3.5 kHz  (ffmpeg)
          4. Light compression 3:1 threshold -24 dB        (ffmpeg)
          5. LUFS -16 loudness normalisation  (ffmpeg loudnorm EBU R128)
        """
        _PCM_EXTS   = {".wav", ".flac", ".ogg", ".aiff", ".aif"}
        tmp_in:       Path | None = None
        tmp_denoised: Path | None = None
        try:
            # ── 1. Noise reduction (Python / noisereduce) ──────────────────
            if denoise:
                need_decode = src.suffix.lower() not in _PCM_EXTS
                if need_decode:
                    if not self._ffmpeg:
                        return AudioResult(output=output, success=False,
                                           error="ffmpeg richiesto per decodifica MP3/AAC")
                    tmp_in = safe_tempfile(suffix=".wav")
                    r = self.convert(src, tmp_in, "wav")
                    if not r.success:
                        return r
                    read_src = tmp_in
                else:
                    read_src = src

                import soundfile as sf
                import numpy as np
                data, sr = sf.read(str(read_src), always_2d=True)
                if progress_cb: progress_cb(0.15)

                try:
                    import noisereduce as nr
                    data = np.stack(
                        [nr.reduce_noise(y=data[:, c], sr=sr,
                                         prop_decrease=prop_decrease)
                         for c in range(data.shape[1])],
                        axis=1,
                    )
                except ImportError:
                    pass
                if progress_cb: progress_cb(0.60)

                tmp_denoised = safe_tempfile(suffix=".wav")
                sf.write(str(tmp_denoised), data, sr, format="WAV")
                ffmpeg_src = tmp_denoised
            else:
                ffmpeg_src = src

            if progress_cb: progress_cb(0.70)

            # ── 2–5. Professional ffmpeg filter chain ──────────────────────
            filters: list[str] = []
            if highpass:
                filters.append("highpass=f=80")
            if eq_presence:
                filters.append("equalizer=f=300:width_type=o:width=1:g=-2")
                filters.append("equalizer=f=3500:width_type=o:width=1.5:g=2.5")
            if compress:
                # threshold=0.063 ≈ -24 dBFS; makeup=1.26 ≈ +2 dB (linear).
                filters.append(
                    "acompressor=threshold=0.063:ratio=3:attack=5:release=100:makeup=1.26")
            if normalize:
                filters.append("loudnorm=I=-16:TP=-1.5:LRA=11:print_format=none")

            if not self._ffmpeg:
                return AudioResult(output=output, success=False,
                                   error="ffmpeg richiesto per il pipeline professionale")

            import subprocess as sp
            cmd = [self._ffmpeg, "-y", "-i", str(ffmpeg_src)]
            if filters:
                cmd += ["-af", ",".join(filters)]
            cmd.append(str(output))
            proc = sp.run(cmd, stdout=sp.DEVNULL, stderr=sp.PIPE,
                          encoding="utf-8", errors="replace")
            if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
                lines = (proc.stderr or "").strip().splitlines()
                return AudioResult(output=output, success=False,
                                   error=lines[-1] if lines else "ffmpeg error")

            if progress_cb: progress_cb(1.0)
            return self._ok(output, self.probe(output).duration_s)

        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))
        finally:
            for t in (tmp_in, tmp_denoised):
                if t:
                    try: t.unlink(missing_ok=True)
                    except Exception: pass

    # ── Voice cleaner (WAV → web-optimised MP3) ────────────────────────────

    def clean_voice(
        self,
        src:       Path,
        output:    Path,
        preset:    str = "normale",    # "leggero" | "normale" | "intenso"
        mp3_q:     int = 2,            # libmp3lame VBR: 0(best) – 9(worst); 2 ≈ 190 kbps
        to_mono:   bool = False,
        sample_rate: int = 44100,
    ) -> AudioResult:
        """
        Voice cleaner: removes rumble, reduces noise, normalises loudness to
        broadcast standard (EBU R128), and encodes to a web-optimised MP3.

        All filters are conservative to preserve the original voice character.
        Pipeline is pure ffmpeg, so there's no Python audio-processing risk of
        truncation, clipping or resampling artefacts.
        """
        if not self._ffmpeg:
            return AudioResult(output=output, success=False,
                               error="ffmpeg non trovato. pip install imageio-ffmpeg")

        # Filter chain per preset
        if preset == "leggero":
            afilter = (
                "highpass=f=60,"
                "loudnorm=I=-16:TP=-1.5:LRA=11"
            )
        elif preset == "intenso":
            afilter = (
                "highpass=f=85,"
                "afftdn=nr=20:nf=-20:tn=1,"
                "equalizer=f=3000:t=o:w=2:g=1.8,"
                "loudnorm=I=-16:TP=-1.5:LRA=11"
            )
        else:  # "normale" — balanced, safe default
            afilter = (
                "highpass=f=80,"
                "afftdn=nr=12:nf=-25:tn=1,"
                "loudnorm=I=-16:TP=-1.5:LRA=11"
            )

        try:
            cmd = [
                self._ffmpeg, "-y", "-i", str(src),
                "-af", afilter,
                "-ar", str(sample_rate),
            ]
            if to_mono:
                cmd += ["-ac", "1"]
            cmd += [
                "-c:a", "libmp3lame",
                "-q:a", str(mp3_q),
                "-map_metadata", "-1",   # strip metadata for clean web file
                str(output),
            ]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                err = proc.stderr.strip()[-400:] if proc.stderr else "Errore sconosciuto"
                return AudioResult(output=output, success=False, error=err)
            return self._ok(output)
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
        """
        Apply a 3-band shelving EQ using Butterworth filters. Requires scipy.
        For formats soundfile can't read (MP3/AAC), decodes to a temp WAV first,
        applies EQ, then re-encodes to the desired output format.
        """
        _PCM_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}
        tmp_in:  Path | None = None
        tmp_out: Path | None = None
        try:
            import soundfile as sf
            import numpy as np
            from scipy.signal import butter, sosfilt

            # If source can't be read directly, decode to temp WAV
            need_decode = src.suffix.lower() not in _PCM_EXTS
            if need_decode:
                if not self._ffmpeg:
                    return AudioResult(output=output, success=False,
                                       error="ffmpeg necessario per la EQ su MP3/AAC")
                tmp_in = safe_tempfile(suffix=".wav")
                r = self.convert(src, tmp_in, "wav")
                if not r.success:
                    return r
                read_src = tmp_in
            else:
                read_src = src

            data, sr = sf.read(str(read_src), always_2d=True)

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

            eq_data = (
                _filter(None,   250.0) * _gain(bass_db)
                + _filter(250.0, 4000.0) * _gain(mid_db)
                + _filter(4000.0, None)   * _gain(treble_db)
            )

            # Prevent clipping
            peak = np.max(np.abs(eq_data))
            if peak > 1.0:
                eq_data /= peak

            # If output must be a non-PCM format, write WAV first then convert
            need_encode = output.suffix.lower() not in _PCM_EXTS
            if need_encode:
                tmp_out = safe_tempfile(suffix=".wav")
                sf.write(str(tmp_out), eq_data, sr, format="WAV")
                return self.convert(tmp_out, output, output.suffix.lstrip("."))
            else:
                out_fmt = {".flac": "flac", ".wav": "WAV", ".ogg": "ogg"}.get(
                    output.suffix.lower(), "WAV")
                sf.write(str(output), eq_data, sr, format=out_fmt)
                return self._ok(output, len(data) / float(sr))
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))
        finally:
            for t in (tmp_in, tmp_out):
                if t:
                    t.unlink(missing_ok=True)

    # ── Split ─────────────────────────────────────────────────────────────

    def split(
        self,
        src:             Path,
        output_dir:      Path,
        split_points_ms: list[int],
    ) -> list[AudioResult]:
        """
        Split audio at the given millisecond positions.
        Produces N+1 files named <stem>_part01<ext>, _part02, …
        Returns a list of AudioResult (one per output file).
        """
        try:
            from pydub import AudioSegment
            audio    = AudioSegment.from_file(str(src))
            total_ms = len(audio)
            fmt      = src.suffix.lstrip(".")

            points = [0] + sorted(int(p) for p in split_points_ms) + [total_ms]
            results: list[AudioResult] = []
            for i, (a, b) in enumerate(zip(points, points[1:]), start=1):
                clip = audio[a:b]
                out  = output_dir / f"{src.stem}_part{i:02d}{src.suffix}"
                clip.export(str(out), format=fmt)
                results.append(self._ok(out, len(clip) / 1000.0))
            return results
        except Exception as exc:
            return [AudioResult(output=None, success=False, error=str(exc))]

    # ── Mute region ───────────────────────────────────────────────────────

    def mute_region(
        self,
        src:      Path,
        output:   Path,
        start_ms: int,
        end_ms:   int,
    ) -> AudioResult:
        """
        Silence the audio between start_ms and end_ms (replace with silence).
        The file length is preserved.
        """
        try:
            from pydub import AudioSegment
            audio    = AudioSegment.from_file(str(src))
            end_ms   = min(end_ms, len(audio))
            silence  = AudioSegment.silent(
                duration=end_ms - start_ms,
                frame_rate=audio.frame_rate,
            ).set_channels(audio.channels).set_sample_width(audio.sample_width)
            muted = audio[:start_ms] + silence + audio[end_ms:]
            fmt   = output.suffix.lstrip(".")
            muted.export(str(output), format=fmt)
            return self._ok(output, len(muted) / 1000.0)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    # ── Speed ─────────────────────────────────────────────────────────────

    def change_speed(
        self,
        src:    Path,
        output: Path,
        speed:  float = 1.0,
    ) -> AudioResult:
        """Change playback speed preserving pitch (ffmpeg atempo time-stretch)."""
        try:
            if speed == 1.0:
                import shutil
                shutil.copy2(str(src), str(output))
                return self._ok(output, self.probe(src).duration_s)

            # atempo only accepts [0.5, 2.0]; chain two filters outside that range
            if speed < 0.5:
                filters = [f"atempo={speed*2:.4f}", "atempo=0.5"]
            elif speed > 2.0:
                filters = [f"atempo={speed/2:.4f}", "atempo=2.0"]
            else:
                filters = [f"atempo={speed:.4f}"]

            import subprocess as sp
            proc = sp.run(
                [self._ffmpeg, "-y", "-i", str(src),
                 "-af", ",".join(filters),
                 str(output)],
                stdout=sp.DEVNULL, stderr=sp.PIPE,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
                lines = (proc.stderr or "").strip().splitlines()
                return AudioResult(output=output, success=False,
                                   error=lines[-1] if lines else "ffmpeg error")
            return self._ok(output, self.probe(output).duration_s)
        except Exception as exc:
            return AudioResult(output=output, success=False, error=str(exc))

    def apply_voice_effect(
        self,
        src:    Path,
        output: Path,
        effect: str,
    ) -> AudioResult:
        """Apply a creative voice effect via ffmpeg (see VOICE_EFFECTS dict)."""
        if effect not in VOICE_EFFECTS:
            return AudioResult(output=output, success=False,
                               error=f"Effetto sconosciuto: {effect}")
        _, filter_chain = VOICE_EFFECTS[effect]
        try:
            import subprocess as sp
            proc = sp.run(
                [self._ffmpeg, "-y", "-i", str(src),
                 "-af", filter_chain,
                 str(output)],
                stdout=sp.DEVNULL, stderr=sp.PIPE,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
                lines = (proc.stderr or "").strip().splitlines()
                return AudioResult(output=output, success=False,
                                   error=lines[-1] if lines else "ffmpeg error")
            return self._ok(output, self.probe(output).duration_s)
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
        Falls back to ffmpeg-decoded WAV for formats soundfile can't read (MP3/AAC…).
        """
        tmp: Path | None = None
        try:
            import soundfile as sf
            import numpy as np

            try:
                data, _ = sf.read(str(path), always_2d=False)
            except Exception:
                # soundfile can't read MP3/AAC — decode to a temp WAV via ffmpeg
                if not self._ffmpeg:
                    return [0.0] * num_samples, [0.0] * num_samples
                tmp = safe_tempfile(suffix=".wav")
                proc = subprocess.run(
                    [self._ffmpeg, "-y", "-i", str(path), str(tmp)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace",
                )
                if proc.returncode != 0 or tmp.stat().st_size == 0:
                    return [0.0] * num_samples, [0.0] * num_samples
                data, _ = sf.read(str(tmp), always_2d=False)

            if data.ndim > 1:
                data = data.mean(axis=1)   # mix to mono

            chunks = np.array_split(data, num_samples)
            pos = [float(np.max(c)) if len(c) else 0.0 for c in chunks]
            neg = [float(np.min(c)) if len(c) else 0.0 for c in chunks]

            peak = max(max(abs(v) for v in pos + neg), 1e-6)
            return [v / peak for v in pos], [v / peak for v in neg]
        except Exception:
            return [0.0] * num_samples, [0.0] * num_samples
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

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
        proc: subprocess.Popen | None = None
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
        finally:
            # Ensure demucs doesn't linger as an orphan on exception/cancel
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try: proc.kill()
                    except Exception: pass

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

            # Filesystem timestamps
            try:
                stat   = path.stat()
                fs_cre = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
                fs_mod = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                fs_acc = datetime.fromtimestamp(stat.st_atime).strftime("%Y-%m-%d %H:%M:%S")
                for rk, lbl, val in [
                    ("_fs_created",  "Data creazione file (filesystem)", fs_cre),
                    ("_fs_modified", "Data ultima modifica (filesystem)", fs_mod),
                    ("_fs_accessed", "Data ultimo accesso (filesystem)",  fs_acc),
                ]:
                    fields.append(self._field(rk, lbl, val, "info",
                                              editable=False, deletable=False))
            except Exception:
                pass

            # SHA-256 hash
            try:
                h = self.get_file_hash(path)
                fields.append(self._field(
                    "_sha256", "SHA-256 (integrità file)", h,
                    "info", editable=False, deletable=False))
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
        fields: list[dict] = []
        try:
            try:
                tags = ID3(str(path))
            except ID3NoHeaderError:
                tags = None

            if tags is not None:
                ver = f"ID3 v2.{tags.version[1]}.{tags.version[2]}"
                fields.append(self._field("_id3ver", "Versione ID3", ver,
                                          "info", editable=False, deletable=False))
                for key in sorted(tags.keys()):
                    frame = tags[key]
                    base  = key[:4]
                    dname, cat = _ID3_INFO.get(base, (f"Frame {base}", "custom"))
                    if base == "TXXX" and hasattr(frame, "desc") and frame.desc:
                        dname = f"Tag personalizzato: {frame.desc}"
                    if base == "APIC":
                        raw  = getattr(frame, "data", b"")
                        val  = (f"[{getattr(frame,'mime','?')}  {len(raw)//1024} KB]")
                        edit, dele = False, True
                    elif base in ("PRIV", "GEOB", "ENCR", "AENC"):
                        raw  = getattr(frame, "data", b"")
                        val  = f"[binario {len(raw)} B]  {raw[:16].hex()}"
                        edit, dele = False, True
                    elif hasattr(frame, "text") and frame.text:
                        val  = str(frame.text[0])
                        edit, dele = True, True
                    else:
                        val  = str(frame)
                        edit, dele = False, True
                    warn = "Rilevabile nel flusso audio" if base == "TSSE" else ""
                    fields.append(self._field(key, dname, val, cat,
                                              editable=edit, deletable=dele,
                                              warning=warn))

            # ID3v1 + LAME header (binary analysis)
            try:
                raw_data = path.read_bytes()
                # ID3v2 size for LAME parser
                id3v2_size = 0
                if raw_data[:3] == b"ID3":
                    id3v2_size = (10 + ((raw_data[6] & 0x7f) << 21
                                        | (raw_data[7] & 0x7f) << 14
                                        | (raw_data[8] & 0x7f) << 7
                                        | (raw_data[9] & 0x7f)))
                fields.extend(self._read_id3v1(raw_data))
                fields.extend(self._parse_lame_header(raw_data, id3v2_size))
            except Exception:
                pass
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

    # ── ID3v1 (binary, last 128 bytes of MP3) ─────────────────────────────

    def _read_id3v1(self, data: bytes) -> list[dict]:
        """Detect and parse ID3v1 tag (128 bytes at EOF)."""
        fields: list[dict] = []
        if len(data) < 128 or data[-128:-125] != b"TAG":
            return fields

        def _s(b: bytes) -> str:
            return b.rstrip(b"\x00").decode("latin-1", errors="replace").strip()

        title   = _s(data[-125:-95])
        artist  = _s(data[-95:-65])
        album   = _s(data[-65:-35])
        year    = _s(data[-35:-31])
        comment = _s(data[-31:-3]) if data[-2] != 0 else _s(data[-31:-3])
        track   = str(data[-1]) if data[-2] == 0 and data[-1] != 0 else ""
        genre_i = data[-1] if data[-2] != 0 else 0
        genre   = (_ID3V1_GENRES[genre_i]
                   if genre_i < len(_ID3V1_GENRES) else str(genre_i))

        fields.append(self._field(
            "_id3v1_present",
            "⚠ ID3v1 rilevato (coesiste con ID3v2)",
            "Il file è stato processato da almeno due software di tagging diversi",
            "history", editable=False, deletable=False,
            warning="Presenza simultanea ID3v1+ID3v2 indica modifiche successive alla creazione"))

        for raw_k, display, val in [
            ("_id3v1_title",   "ID3v1 · Titolo",   title),
            ("_id3v1_artist",  "ID3v1 · Artista",  artist),
            ("_id3v1_album",   "ID3v1 · Album",    album),
            ("_id3v1_year",    "ID3v1 · Anno",     year),
            ("_id3v1_comment", "ID3v1 · Commento", comment),
            ("_id3v1_track",   "ID3v1 · Traccia",  track),
            ("_id3v1_genre",   "ID3v1 · Genere",   genre),
        ]:
            if val:
                fields.append(self._field(raw_k, display, val, "history",
                                          editable=False, deletable=True))
        return fields

    # ── LAME / Xing header (binary, inside first MPEG frame) ──────────────

    def _parse_lame_header(self, data: bytes, id3v2_size: int) -> list[dict]:
        """Parse Xing/Info VBR marker and LAME encoder tag from MP3 stream."""
        fields: list[dict] = []
        try:
            offset = id3v2_size
            # Find first MPEG sync word within first 64 KB
            end = min(offset + 65536, len(data) - 4)
            while offset < end:
                if data[offset] == 0xff and (data[offset + 1] & 0xe0) == 0xe0:
                    break
                offset += 1
            else:
                return fields

            hdr        = data[offset: offset + 4]
            mpeg_ver   = (hdr[1] >> 3) & 3
            chan_mode  = (hdr[3] >> 6) & 3
            si_size    = _MPEG_SIDE_INFO.get((mpeg_ver, chan_mode), 17)

            xing_off = offset + 4 + si_size
            if xing_off + 4 > len(data):
                return fields

            marker = data[xing_off: xing_off + 4]
            if marker not in (b"Xing", b"Info"):
                return fields

            vbr_type = "VBR (Xing)" if marker == b"Xing" else "CBR (Info)"
            fields.append(self._field(
                "_xing_type", "⏱ Tipo encoding nel flusso (Xing/Info)",
                vbr_type, "history", editable=False, deletable=False,
                warning="Rilevabile nel flusso audio — non rimovibile senza ri-codifica"))

            # Parse frame/byte counts from Xing header flags
            flags = int.from_bytes(data[xing_off + 4: xing_off + 8], "big")
            pos   = xing_off + 8
            if flags & 0x01:  # frame count
                frames = int.from_bytes(data[pos: pos + 4], "big")
                fields.append(self._field("_xing_frames", "Frame audio totali",
                                          str(frames), "info",
                                          editable=False, deletable=False))
                pos += 4
            if flags & 0x02:  # byte count
                nbytes = int.from_bytes(data[pos: pos + 4], "big")
                fields.append(self._field("_xing_bytes", "Byte audio totali",
                                          str(nbytes), "info",
                                          editable=False, deletable=False))

            # Scan for LAME tag within first 512 bytes after Xing
            search_area = data[xing_off: xing_off + 512]
            lame_pos    = search_area.find(b"LAME")
            if lame_pos != -1:
                abs_pos  = xing_off + lame_pos
                ver_raw  = data[abs_pos + 4: abs_pos + 13]
                ver      = ver_raw.decode("latin-1", errors="replace").rstrip("\x00").strip()
                fields.append(self._field(
                    "_lame_ver", "⏱ Versione encoder LAME (stream)",
                    f"LAME {ver}", "history", editable=False, deletable=False,
                    warning="Impronta encoder nel flusso — non rimovibile senza ri-codifica"))
        except Exception:
            pass
        return fields

    # ── Album art (raw bytes → let UI render) ─────────────────────────────

    def get_album_art(self, path: Path) -> bytes | None:
        """Return raw album art bytes, or None if not found."""
        try:
            ext = path.suffix.lower()
            if ext == ".mp3":
                from mutagen.id3 import ID3
                tags = ID3(str(path))
                for key in tags.keys():
                    if key.startswith("APIC"):
                        return tags[key].data
            elif ext == ".flac":
                from mutagen.flac import FLAC
                audio = FLAC(str(path))
                if audio.pictures:
                    return audio.pictures[0].data
            elif ext in (".m4a", ".mp4"):
                from mutagen.mp4 import MP4
                audio = MP4(str(path))
                if audio.tags and "covr" in audio.tags:
                    return bytes(audio.tags["covr"][0])
            elif ext in (".ogg", ".opus"):
                import base64
                from mutagen.flac import Picture
                cls = (__import__("mutagen.oggopus", fromlist=["OggOpus"]).OggOpus
                       if ext == ".opus"
                       else __import__("mutagen.oggvorbis",
                                       fromlist=["OggVorbis"]).OggVorbis)
                audio = cls(str(path))
                if audio.tags:
                    raw_list = audio.tags.get("metadata_block_picture", [])
                    if raw_list:
                        pic = Picture(base64.b64decode(raw_list[0]))
                        return pic.data
        except Exception:
            pass
        return None

    # ── File hash (SHA-256) ───────────────────────────────────────────────

    @staticmethod
    def get_file_hash(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

    # ── Provenance analysis ───────────────────────────────────────────────

    def compute_provenance(self, path: Path, fields: list[dict]) -> dict:
        """
        Analyse all available signals and return a provenance report:
        {"verdict": str, "score": int 0-100, "signals": list[str],
         "hash": str, "fs_created": str, "fs_modified": str}
        score: 0 = probably original, 100 = heavily modified
        """
        signals: list[str] = []
        score = 0

        # ── Filesystem timestamps ─────────────────────────────────────────
        try:
            stat   = path.stat()
            fs_mod = datetime.fromtimestamp(stat.st_mtime)
            fs_cre = datetime.fromtimestamp(stat.st_ctime)
            fs_created  = fs_cre.strftime("%Y-%m-%d %H:%M:%S")
            fs_modified = fs_mod.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            fs_created = fs_modified = "N/D"

        # ── Signal analysis ───────────────────────────────────────────────
        def _val(raw_key: str) -> str | None:
            for f in fields:
                if f["raw_key"] == raw_key:
                    return f["value"]
            return None

        # ID3v1 + ID3v2 coexistence → strong modification signal
        if any(f["raw_key"] == "_id3v1_present" for f in fields):
            score += 35
            signals.append("ID3v1 + ID3v2 coesistono — il file è stato ritaggato "
                            "dopo la creazione originale")

        # TDTG: explicit tagging timestamp
        tdtg = _val("TDTG")
        if tdtg:
            score += 20
            signals.append(f"Tag scritti/modificati il: {tdtg}")

        # TENC / encoding software
        tenc = _val("TENC")
        if tenc:
            score += 10
            signals.append(f"Software di tagging/encoding: {tenc}")

        # TSSE: encoder settings (stored by some encoders)
        tsse = _val("TSSE")
        if tsse:
            score += 5
            signals.append(f"Impostazioni encoder: {tsse}")

        # LAME version in stream
        lame = _val("_lame_ver")
        if lame:
            signals.append(f"Encoder nel flusso audio: {lame}")

        # Vendor string (FLAC/OGG)
        vendor = _val("_vendor")
        if vendor:
            signals.append(f"Vendor string (tagging software): {vendor}")

        # TOFN: original filename stored in tag
        tofn = _val("TOFN")
        if tofn:
            score += 10
            signals.append(f"Nome file originale conservato nei tag: {tofn}")

        # iTunes custom atoms
        apple_count = sum(1 for f in fields
                          if f["raw_key"].startswith("----:"))
        if apple_count:
            score += 10
            signals.append(f"{apple_count} atom iTunes personalizzato/i "
                            "(tracce di iTunes/Music)")

        # Hidden/private frames
        hidden = [f for f in fields if f["category"] == "hidden"]
        if hidden:
            score += 10
            signals.append(f"{len(hidden)} campo/i nascosto/i "
                            "(PRIV, UFID, GEOB, …)")

        # Filesystem modification vs embedded recording year
        for rk in ("TDRC", "©day", "date", "_id3v1_year"):
            rec_year = _val(rk)
            if rec_year and fs_modified != "N/D":
                try:
                    ry = int(str(rec_year)[:4])
                    fy = datetime.strptime(fs_modified, "%Y-%m-%d %H:%M:%S").year
                    if fy > ry + 1:
                        score += 5
                        signals.append(
                            f"File modificato nel {fy}, "
                            f"ma data registrazione nei tag: {ry}")
                except Exception:
                    pass
                break

        # TPE4: remixed/modified by
        tpe4 = _val("TPE4")
        if tpe4:
            score += 5
            signals.append(f"Remixato / modificato da: {tpe4}")

        # ── Verdict ───────────────────────────────────────────────────────
        if score == 0 and not signals:
            verdict = ("🟢  Probabilmente originale — "
                       "nessuna traccia di modifiche ai metadati")
        elif score < 20:
            verdict = "🟡  Poche tracce — ritaggato in modo pulito"
        elif score < 50:
            verdict = "🟠  Modificato — presenti tracce di lavorazione"
        else:
            verdict = ("🔴  Pesantemente modificato — "
                       "molteplici strumenti hanno toccato il file")

        # File hash
        try:
            file_hash = self.get_file_hash(path)
        except Exception:
            file_hash = "N/D"

        return {
            "verdict":     verdict,
            "score":       min(score, 100),
            "signals":     signals,
            "hash":        file_hash,
            "fs_created":  fs_created,
            "fs_modified": fs_modified,
        }

    # ── Export metadata report ────────────────────────────────────────────

    def export_report(
        self,
        path:        Path,
        fields:      list[dict],
        provenance:  dict,
        output_path: Path,
    ) -> AudioResult:
        """Export full metadata report as TXT or JSON."""
        try:
            if output_path.suffix.lower() == ".json":
                data = {
                    "file":       str(path),
                    "analyzed":   datetime.now().isoformat(),
                    "provenance": provenance,
                    "fields": [
                        {"key": f["raw_key"], "name": f["display_name"],
                         "value": f["value"], "category": f["category"]}
                        for f in fields
                    ],
                }
                output_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")
            else:
                _CAT_LABELS_LOCAL = {
                    "standard":  "TAG STANDARD",
                    "technical": "TECNICI",
                    "history":   "STORICO / PROVENIENZA",
                    "hidden":    "DATI NASCOSTI / PRIVATI",
                    "custom":    "TAG PERSONALIZZATI",
                    "art":       "IMMAGINI INCORPORATE",
                    "info":      "INFORMAZIONI FILE",
                }
                lines = [
                    "═" * 60,
                    "  Multimedia Master — Report Metadati",
                    "═" * 60,
                    f"  File:       {path.name}",
                    f"  Percorso:   {path}",
                    f"  Analizzato: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"  SHA-256:    {provenance['hash']}",
                    f"  Creato:     {provenance['fs_created']}",
                    f"  Modificato: {provenance['fs_modified']}",
                    "",
                    "── PROVENIENZA " + "─" * 44,
                    f"  {provenance['verdict']}",
                    f"  Score: {provenance['score']}/100",
                ]
                if provenance["signals"]:
                    lines.append("")
                    for s in provenance["signals"]:
                        lines.append(f"  • {s}")
                lines.append("")

                current_cat = None
                for f in fields:
                    if f["category"] != current_cat:
                        current_cat = f["category"]
                        lbl = _CAT_LABELS_LOCAL.get(current_cat, current_cat.upper())
                        lines.append(f"── {lbl} " + "─" * max(1, 55 - len(lbl)))
                    val = f["value"]
                    if len(val) > 80:
                        val = val[:77] + "…"
                    lines.append(f"  {f['display_name']:<38} {val}")
                lines.append("")
                lines.append("═" * 60)
                output_path.write_text("\n".join(lines), encoding="utf-8")

            return AudioResult(output=output_path, success=True)
        except Exception as exc:
            return AudioResult(output=output_path, success=False, error=str(exc))

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
        tmp = safe_tempfile(suffix=path.suffix)
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
