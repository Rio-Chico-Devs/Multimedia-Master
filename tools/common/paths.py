"""
Frozen-build-aware path helpers.

A PyInstaller onefile build extracts bundled files to a temporary directory
(sys._MEIPASS) that is deleted the moment the process exits — fine for
reading bundled source/resources, useless for anything that must persist
(crash logs, settings). exe_dir() always resolves to the directory next to
the real .exe, stable across runs, in both dev mode and frozen builds
(onefile or onedir).
"""
from __future__ import annotations

import sys
from pathlib import Path


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # tools/common/paths.py -> repo root
    return Path(__file__).resolve().parent.parent.parent


def crash_log_path(tool_name: str) -> Path:
    """Stable, writable crash-log location for `tool_name`."""
    if getattr(sys, "frozen", False):
        log_dir = exe_dir() / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir / f"{tool_name}_crash.log"
        except OSError:
            # exe installed to a read-only location (e.g. Program Files
            # without admin rights) — fall back to a per-user writable dir
            # rather than crash before the crash logger even exists.
            import tempfile
            fallback = Path(tempfile.gettempdir()) / "MultimediaMaster" / "logs"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback / f"{tool_name}_crash.log"
    return exe_dir() / "tools" / tool_name / "crash.log"
