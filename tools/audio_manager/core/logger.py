"""
Minimal crash-safe logger shared across all audio-manager modules.
call logger.setup(path) once at startup; then logger.log(header, text) anywhere.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

_log_path: Path | None = None


def setup(path: Path) -> None:
    global _log_path
    _log_path = path


def log(header: str, text: str = "") -> None:
    if not _log_path:
        return
    try:
        with _log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"{header}  [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]\n")
            if text:
                f.write(text.rstrip() + "\n")
    except Exception:
        pass
