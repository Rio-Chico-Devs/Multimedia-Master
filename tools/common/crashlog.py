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
    """
    Mirror writes to the real stream AND the crash log.

    On Windows, a windowed (console=False) build has sys.stdout AND
    sys.stderr set to None by the PyInstaller bootloader — any code or
    third-party library that calls .write()/.isatty()/.fileno() on them
    without a None-check crashes the whole process. Wrapping both streams
    here (not just stderr) means that crash can't happen, and isatty()/
    fileno() answer the way a library would expect from "no real terminal"
    instead of raising AttributeError.
    """

    def __init__(self, real, label: str):
        self._real = real
        self._label = label

    def write(self, s: str) -> None:
        if self._real is not None:
            try:
                self._real.write(s)
                self._real.flush()
            except Exception:
                pass
        if s.strip():
            _write(self._label, s)

    def flush(self) -> None:
        if self._real is not None:
            try:
                self._real.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    def fileno(self):
        if self._real is not None:
            try:
                return self._real.fileno()
            except Exception:
                pass
        raise OSError("no underlying stream (windowed build has none)")


def install(log_path: Path) -> None:
    """Wire up stdout/stderr tee + main/thread exception hooks."""
    global _log_path
    _log_path = log_path

    sys.stdout = _TeeStream(sys.stdout, "STDOUT")
    sys.stderr = _TeeStream(sys.stderr, "STDERR")

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


def run_gui(factory, tool_label: str) -> None:
    """
    Build and run a CTk app, turning any fatal startup/mainloop crash into a
    logged entry + a visible error dialog instead of a window that silently
    vanishes. `factory` is a zero-arg callable returning the root window.

    Re-raises after reporting, so the process still exits non-zero (the
    launcher uses that to flag the failure too).
    """
    try:
        app = factory()
        app.mainloop()
    except Exception:
        tb = traceback.format_exc()
        _write(f"FATAL — {tool_label} crashed", tb)
        try:
            from tkinter import Tk, messagebox
            # The crashing app's root may be unusable; use a throwaway root.
            _root = Tk()
            _root.withdraw()
            messagebox.showerror(
                f"{tool_label} — errore irreversibile",
                "Si è verificato un errore e lo strumento deve chiudersi.\n\n"
                f"Dettagli salvati in:\n{_log_path}",
            )
            _root.destroy()
        except Exception:
            pass
        raise
