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
