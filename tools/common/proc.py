"""
Subprocess helpers shared across tools.

The single reason this module exists: on Windows, console programs like
ffmpeg.exe and powershell.exe pop a black console window for a fraction of
a second on every invocation — even when the parent app is built --windowed.
That looks broken in a shipped product. NO_WINDOW carries the platform flag
that suppresses it; it's an empty dict everywhere except Windows, so call
sites can splat it unconditionally:

    subprocess.run([...], **NO_WINDOW)
"""
from __future__ import annotations

import subprocess
import sys

NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32" else {}
)


def harden_subprocess_stdin() -> None:
    """
    Force every subprocess.Popen call that doesn't explicitly set stdin to
    get DEVNULL instead of inheriting the parent's stdin handle.

    Only matters in a frozen --windowed build: there is no console, so the
    process's stdin handle is invalid. Dependencies that shell out without
    passing stdin= explicitly (pydub's AudioSegment.from_file -> ffmpeg,
    pytesseract -> tesseract.exe) inherit that broken handle and the child
    hangs forever waiting on it — no exception is ever raised, so nothing
    reaches crashlog; the UI just looks stuck. Call once at startup, before
    any such dependency is used.
    """
    if not getattr(sys, "frozen", False):
        return
    _real_init = subprocess.Popen.__init__

    def _patched_init(self, *args, **kwargs):
        if kwargs.get("stdin") is None:
            kwargs["stdin"] = subprocess.DEVNULL
        _real_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init
