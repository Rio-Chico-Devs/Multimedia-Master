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
