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
        kw.setdefault("padx", 18)
        kw.setdefault("pady", 4)
        super().pack(**kw)
