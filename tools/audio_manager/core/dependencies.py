"""
Runtime dependency checker — called once at startup, results cached.

Checks both Python packages and system binaries.
All feature tabs receive a DepStatus and disable/warn accordingly.
"""
from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass


@dataclass
class DepStatus:
    ffmpeg:      bool   # system binary
    pydub:       bool   # pip
    soundfile:   bool   # pip
    noisereduce: bool   # pip
    numpy:       bool   # pip
    scipy:       bool   # pip
    mutagen:     bool   # pip
    demucs:      bool   # pip (optional — requires PyTorch)


def check() -> DepStatus:
    def _pkg(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    return DepStatus(
        ffmpeg=      shutil.which("ffmpeg") is not None,
        pydub=       _pkg("pydub"),
        soundfile=   _pkg("soundfile"),
        noisereduce= _pkg("noisereduce"),
        numpy=       _pkg("numpy"),
        scipy=       _pkg("scipy"),
        mutagen=     _pkg("mutagen"),
        demucs=      _pkg("demucs"),
    )


def missing_packages(status: DepStatus) -> list[str]:
    """Return list of pip package names that are missing."""
    missing = []
    if not status.pydub:       missing.append("pydub")
    if not status.soundfile:   missing.append("soundfile")
    if not status.numpy:       missing.append("numpy")
    return missing


def install_hint(status: DepStatus) -> str:
    """Human-readable installation guide for missing core deps."""
    lines = []
    m = missing_packages(status)
    if m:
        lines.append(f"pip install {' '.join(m)}")
    if not status.ffmpeg:
        lines.append(
            "ffmpeg: installa da https://ffmpeg.org  "
            "oppure  winget install ffmpeg  /  apt install ffmpeg"
        )
    return "\n".join(lines)
