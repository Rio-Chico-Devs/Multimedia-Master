import customtkinter as ctk
from pathlib import Path
from PIL import Image

from core.formats import ConversionResult


class FileRow(ctk.CTkFrame):
    """
    Displays a single queued file: thumbnail, name, size, dimensions,
    a remove button, and a status label updated after conversion.
    """

    THUMB_SIZE = 48

    def __init__(self, parent, file_path: Path, on_remove, **kw):
        super().__init__(parent, corner_radius=8, **kw)
        self.file_path = file_path
        self._build(on_remove)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_status(self, text: str, color: str = "gray") -> None:
        self._status_lbl.configure(text=text, text_color=color)

    def apply_result(self, result: ConversionResult) -> None:
        """Update the status label from a ConversionResult."""
        if not result.success:
            self.set_status("✗ errore", "#f44336")
            return
        d = result.delta_pct
        if d > 0:
            self.set_status(f"✓ -{d}%", "#4caf50")
        elif d < 0:
            self.set_status(f"✓ +{-d}%", "#ff9800")
        else:
            self.set_status("✓", "#4caf50")

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self, on_remove) -> None:
        self._add_thumbnail()
        self._add_info()
        self._status_lbl = ctk.CTkLabel(self, text="", width=80,
                                        font=ctk.CTkFont(size=12))
        self._status_lbl.pack(side="right", padx=6)
        ctk.CTkButton(
            self, text="✕", width=30, height=30,
            fg_color="transparent", hover_color="#3a3a3a",
            command=lambda: on_remove(self),
        ).pack(side="right", padx=(0, 8))

    def _add_thumbnail(self) -> None:
        s = self.THUMB_SIZE
        try:
            pil = Image.open(self.file_path)
            pil.thumbnail((s, s), Image.LANCZOS)
            self._thumb = ctk.CTkImage(pil, size=(min(s, pil.width), min(s, pil.height)))
            ctk.CTkLabel(self, image=self._thumb, text="").pack(
                side="left", padx=(10, 6), pady=8)
        except Exception:
            ctk.CTkLabel(self, text="🖼", font=ctk.CTkFont(size=22), width=s).pack(
                side="left", padx=(10, 6), pady=8)

    def _add_info(self) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            frame, text=self.file_path.name, anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(fill="x")

        ctk.CTkLabel(
            frame,
            text=self._subtitle(),
            anchor="w", text_color="gray",
            font=ctk.CTkFont(size=11),
        ).pack(fill="x")

    def _subtitle(self) -> str:
        size_b = self.file_path.stat().st_size
        size_str = (f"{size_b / 1024:.0f} KB" if size_b < 1_048_576
                    else f"{size_b / 1_048_576:.2f} MB")
        fmt = self.file_path.suffix[1:].upper()
        dims = self._dims()
        return f"{size_str}  ·  {fmt}  ·  {dims}"

    @staticmethod
    def _dims_from(path: Path) -> str:
        try:
            w, h = Image.open(path).size
            return f"{w}×{h} px"
        except Exception:
            return ""

    def _dims(self) -> str:
        return self._dims_from(self.file_path)
