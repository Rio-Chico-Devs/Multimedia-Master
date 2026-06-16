"""
Shared window-geometry helper.

On small laptops (1366×768) and with Windows display scaling at 125–150 %,
a hard-coded geometry like "980x760" is taller than the usable desktop:
the bottom button bar ends up behind the taskbar or off-screen entirely.

fit_window() clamps the requested size to the usable screen area, centres
the window, and lowers minsize accordingly so the user can always shrink
the window enough to see everything.
"""
from __future__ import annotations


# Margins left free for OS chrome (taskbar, title bar, window borders).
_MARGIN_W = 60
_MARGIN_H = 110


def fit_window(win, want_w: int, want_h: int,
               min_w: int, min_h: int) -> None:
    """Size `win` to want_w×want_h, clamped to the screen, and centre it."""
    # CustomTkinter multiplies geometry()/minsize() values by the Windows
    # DPI scaling factor, while winfo_screen* returns physical pixels —
    # convert the screen size to the same logical units before clamping.
    try:
        from customtkinter import ScalingTracker
        scale = ScalingTracker.get_window_scaling(win)
    except Exception:
        scale = 1.0
    sw = int(win.winfo_screenwidth() / scale)
    sh = int(win.winfo_screenheight() / scale)

    w = max(320, min(want_w, sw - _MARGIN_W))
    h = max(240, min(want_h, sh - _MARGIN_H))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h - _MARGIN_H) // 2)

    win.geometry(f"{w}x{h}+{x}+{y}")
    # minsize must never exceed what the screen can show
    win.minsize(min(min_w, w), min(min_h, h))
