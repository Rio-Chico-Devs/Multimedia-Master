"""
Shared crash logger for every Multimedia Master tool.

On Windows each tool runs as a subprocess with no visible console, so
without this file ALL exceptions — including C-extension crashes — are
silently lost.  Call install(log_path) as the FIRST thing in app.py.
"""
from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

_log_path: Path | None = None


def _write(header: str, text: str) -> None:
    if _log_path is None:
        return
    try:
        with _log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 70}\n")
            f.write(f"{header}  [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
            f.write(f"{'=' * 70}\n")
            f.write(text + "\n")
    except Exception:
        pass


class _TeeStream:
    """Mirror writes to the real stream AND the crash log."""

    def __init__(self, real):
        self._real = real

    def write(self, s: str) -> None:
        try:
            self._real.write(s)
            self._real.flush()
        except Exception:
            pass
        if s.strip():
            _write("STDERR", s)

    def flush(self) -> None:
        try:
            self._real.flush()
        except Exception:
            pass

    def fileno(self):
        return self._real.fileno()


def install(log_path: Path) -> None:
    """Wire up stderr tee + main/thread exception hooks."""
    global _log_path
    _log_path = log_path

    sys.stderr = _TeeStream(sys.stderr)

    def _main_hook(exc_type, exc_value, exc_tb):
        _write("UNCAUGHT EXCEPTION (main thread)",
               "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _main_hook

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        _write(f"UNCAUGHT EXCEPTION (thread: {args.thread})",
               "".join(traceback.format_exception(
                   args.exc_type, args.exc_value, args.exc_traceback)))

    threading.excepthook = _thread_hook

    _write("STARTUP", f"Python {sys.version}\nCWD: {Path.cwd()}")


def log(header: str, text: str = "") -> None:
    """Manual checkpoint logging for debugging."""
    _write(header, text)
