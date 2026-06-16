"""
Shared UI primitives used by all Multimedia Master tools.

Both app.py files add tools/ to sys.path so this is importable as:
    from common.ui.widgets import SectionLabel, Separator, StatusBar
"""
import time

import customtkinter as ctk


class SectionLabel(ctk.CTkLabel):
    """Bold section header, left-aligned."""

    def __init__(self, parent, text: str, **kw):
        kw.setdefault("anchor", "w")
        kw.setdefault("font", ctk.CTkFont(size=12, weight="bold"))
        super().__init__(parent, text=text, **kw)


class Separator(ctk.CTkFrame):
    """Thin horizontal divider line."""

    def __init__(self, parent, **kw):
        kw.setdefault("height", 1)
        kw.setdefault("fg_color", "#2a2a2a")
        super().__init__(parent, **kw)

    def pack(self, **kw):
        kw.setdefault("fill", "x")
        kw.setdefault("padx", 12)
        kw.setdefault("pady", 6)
        super().pack(**kw)


class StatusBar(ctk.CTkLabel):
    """One-line status label at the bottom of a tab or window."""

    def __init__(self, parent, **kw):
        kw.setdefault("anchor", "w")
        kw.setdefault("font", ctk.CTkFont(size=11))
        kw.setdefault("text_color", "gray")
        super().__init__(parent, text="", **kw)

    def ok(self,   msg: str) -> None: self.configure(text=f"✓  {msg}", text_color="#4caf50")
    def err(self,  msg: str) -> None: self.configure(text=f"✗  {msg}", text_color="#f44336")
    def info(self, msg: str) -> None: self.configure(text=msg,          text_color="gray")
    def busy(self, msg: str) -> None: self.configure(text=f"⏳  {msg}", text_color="#aaa")
    def clear(self)          -> None: self.configure(text="")


def adaptive_wraplength(label: ctk.CTkLabel, margin: int = 16) -> None:
    """
    Keep a CTkLabel's wraplength roughly in sync with its width, so text
    reflows when the window is resized — no clipping on small screens, no
    over-narrow column when maximised.

    SAFE BY DESIGN — three independent guards make it impossible for this to
    hang the app, even if the label is laid out in a way where its width
    depends on its own wraplength (a feedback loop):

      1. DEBOUNCE   — bursts of <Configure> events are coalesced into a single
                      update ~120 ms after motion stops, so dragging a window
                      edge does almost no work.
      2. HYSTERESIS — sub-threshold width changes (≤ 24 px) are ignored, so the
                      wraplength never thrashes by a pixel or two.
      3. CIRCUIT BREAKER — if more than a handful of updates fire within one
                      second the only possible cause is a feedback loop, so the
                      handler permanently switches itself off. Worst case the
                      text simply stops reflowing; it can NEVER spin the CPU or
                      trip an OS watchdog.

    The label should be laid out with fill="x" / sticky="ew" so its width
    tracks its container.
    """
    st = {"after_id": None, "last": None, "times": [], "frozen": False}

    def _compute(width_px: int) -> int:
        w = width_px
        # CTk re-applies the DPI factor when we set wraplength; event.width is
        # physical px, so reverse the scaling first to avoid double-scaling.
        rev = getattr(label, "_reverse_widget_scaling", None)
        if rev is not None:
            try:
                w = rev(w)
            except Exception:
                pass
        return max(80, int(w) - margin)

    def _apply(target: int) -> None:
        st["after_id"] = None
        if st["frozen"]:
            return
        if st["last"] is not None and abs(target - st["last"]) <= 24:
            return                                    # guard 2: hysteresis
        now = time.monotonic()
        st["times"] = [t for t in st["times"] if now - t < 1.0]
        st["times"].append(now)
        if len(st["times"]) >= 6:                     # guard 3: circuit breaker
            st["frozen"] = True
            return
        st["last"] = target
        try:
            label.configure(wraplength=target)
        except Exception:
            pass

    def _on_resize(event) -> None:
        if st["frozen"]:
            return
        target = _compute(event.width)
        if st["after_id"] is not None:                # guard 1: debounce
            try:
                label.after_cancel(st["after_id"])
            except Exception:
                pass
        try:
            st["after_id"] = label.after(120, lambda: _apply(target))
        except Exception:
            st["after_id"] = None

    label.bind("<Configure>", _on_resize, add="+")
