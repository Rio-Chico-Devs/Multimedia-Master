"""
Format registry, codec parameters, and quality presets for the audio manager.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class FormatInfo:
    ext:   str    # file extension with dot
    codec: str    # ffmpeg/pydub codec name
    lossy: bool
    desc:  str


AUDIO_FORMATS: dict[str, FormatInfo] = {
    "mp3":  FormatInfo(".mp3",  "mp3",      True,  "MP3 — universalmente compatibile"),
    "aac":  FormatInfo(".m4a",  "ipod",     True,  "AAC — qualità superiore a MP3"),
    "ogg":  FormatInfo(".ogg",  "ogg",      True,  "OGG Vorbis — open source"),
    "opus": FormatInfo(".opus", "opus",     True,  "OPUS — massima efficienza, web/VoIP"),
    "flac": FormatInfo(".flac", "flac",     False, "FLAC — lossless, archivio"),
    "wav":  FormatInfo(".wav",  "wav",      False, "WAV — PCM non compresso"),
    "m4a":  FormatInfo(".m4a",  "ipod",     True,  "M4A — AAC in contenitore MP4"),
}

OUTPUT_FORMATS = list(AUDIO_FORMATS.keys())


@dataclass(frozen=True)
class PresetInfo:
    label:       str
    fmt:         str
    bitrate:     int | None   # kbps; None = lossless
    sample_rate: int | None   # Hz;   None = keep source
    channels:    int | None   # None = keep source
    desc:        str


PRESETS: dict[str, PresetInfo] = {
    "web":       PresetInfo("Web / Streaming",     "opus", 128,  None,  None, "OPUS 128k — ottimale per web e app"),
    "podcast":   PresetInfo("Podcast / Voce",      "mp3",  160,  44100, 1,    "MP3 160k mono — ideale per parlato"),
    "music":     PresetInfo("Musica",              "mp3",  320,  None,  None, "MP3 320k — alta qualità, ampia compatibilità"),
    "cinematic": PresetInfo("Cinematic / Video",   "aac",  256,  48000, None, "AAC 256k 48kHz — standard video professionale"),
    "lossless":  PresetInfo("Lossless / Archivio", "flac", None, None,  None, "FLAC — compressione senza perdita di qualità"),
    "max":       PresetInfo("Massima qualità",     "wav",  None, None,  None, "WAV PCM — nessuna compressione, file grandi"),
    "custom":    PresetInfo("Personalizzato",      "mp3",  192,  None,  None, "Imposta manualmente formato e parametri"),
}

PRESET_NAMES = list(PRESETS.keys())

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".ts",  ".mts", ".m2ts", ".vob", ".3gp", ".ogv", ".mxf",
}

AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav",
    ".wma", ".aiff", ".aif", ".ape", ".mka",  ".wv",  ".tta", ".caf",
}

ALL_MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
