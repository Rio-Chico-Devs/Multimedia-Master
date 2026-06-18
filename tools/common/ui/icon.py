"""
Shared window-icon helper.

iconbitmap() with a .ico path is the only call that reliably works across
Tk/CTk windows on Windows; it raises on platforms/Tk builds that don't
support .ico (e.g. some Linux Tk installs), so failures are swallowed —
a missing window icon is cosmetic, never worth crashing a tool over.
"""
from __future__ import annotations

from common.paths import icon_path


def apply_icon(win) -> None:
    path = icon_path()
    if not path.is_file():
        return
    try:
        win.iconbitmap(str(path))
    except Exception:
        pass
