"""
Shared UI primitives used by all Multimedia Master tools.

Both app.py files add tools/ to sys.path so this is importable as:
    from common.ui.widgets import SectionLabel, Separator, StatusBar
"""
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
    Keep a CTkLabel's wraplength in sync with its real width, so the text
    reflows when the window is resized — no more clipping on small screens
    and no narrow text column when maximised.

    The label must be laid out with fill="x" / sticky="ew" so its width
    tracks the container.
    """
    def _on_resize(event) -> None:
        w = event.width
        try:
            # CTk scales wraplength by the widget DPI factor on configure();
            # event.width is physical px, so reverse the scaling first.
            rev = getattr(label, "_reverse_widget_scaling", None)
            if rev is not None:
                w = rev(w)
            w = max(80, int(w) - margin)
            current = int(label.cget("wraplength") or 0)
            if abs(w - current) > 10:        # avoid resize feedback loops
                label.configure(wraplength=w)
        except Exception:
            pass

    label.bind("<Configure>", _on_resize, add="+")
