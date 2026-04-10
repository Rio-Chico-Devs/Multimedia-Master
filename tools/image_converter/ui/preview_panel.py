import customtkinter as ctk
from pathlib import Path
from PIL import Image

from core.formats import ConversionResult


class PreviewPanel(ctk.CTkFrame):
    """
    Full-width bottom panel showing original vs converted image side by side.
    Activated by clicking any file row; updates again after conversion.
    """

    _MAX = 180   # max thumbnail dimension in the panel

    def __init__(self, parent, **kw):
        kw.setdefault("height", 210)
        super().__init__(parent, **kw)
        self.grid_propagate(False)
        self._build()

    # ── Public API ─────────────────────────────────────────────────────────────

    def show_source(self, path: Path) -> None:
        """Display only the original — called when a row is selected."""
        self._load_side(self._left, path)
        self._clear_side(self._right, placeholder="Converti per vedere il risultato")

    def show_result(self, result: ConversionResult) -> None:
        """Display both sides — called after a successful conversion."""
        self._load_side(self._left, result.source)
        if result.success:
            d = result.delta_pct
            tag = f"  ·  {'-' if d >= 0 else '+'}{abs(d)}%"
            self._load_side(self._right, result.output, extra=tag)
        else:
            self._clear_side(self._right, placeholder=f"Errore: {result.error}")

    def clear(self) -> None:
        self._clear_side(self._left,  placeholder="Seleziona un file per l'anteprima")
        self._clear_side(self._right, placeholder="—")

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._left  = self._make_side("Originale")
        self._arrow = ctk.CTkLabel(self, text="→", font=ctk.CTkFont(size=22),
                                   text_color="#555")
        self._right = self._make_side("Convertita")

        self._left.grid( row=0, column=0, sticky="nsew", padx=(10, 4), pady=8)
        self._arrow.grid(row=0, column=1, padx=6)
        self._right.grid(row=0, column=2, sticky="nsew", padx=(4, 10), pady=8)

        self.clear()

    def _make_side(self, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, corner_radius=8, fg_color="#1c1c1c")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(frame, text=title,
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#888").grid(row=0, column=0, pady=(8, 2))

        frame._img_lbl  = ctk.CTkLabel(frame, text="")
        frame._img_lbl.grid(row=1, column=0, pady=4)

        frame._info_lbl = ctk.CTkLabel(frame, text="—",
                                       text_color="#666",
                                       font=ctk.CTkFont(size=10))
        frame._info_lbl.grid(row=2, column=0, pady=(2, 8))

        return frame

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _load_side(self, frame, path: Path, extra: str = "") -> None:
        try:
            pil = Image.open(path)
            orig_w, orig_h = pil.size
            pil.thumbnail((self._MAX, self._MAX), Image.LANCZOS)
            img = ctk.CTkImage(pil, size=(pil.width, pil.height))

            frame._img_lbl.configure(image=img, text="")
            frame._img_lbl._ctk_img = img   # prevent GC

            size_b   = path.stat().st_size
            size_str = (f"{size_b / 1024:.0f} KB" if size_b < 1_048_576
                        else f"{size_b / 1_048_576:.2f} MB")
            frame._info_lbl.configure(
                text=f"{orig_w}×{orig_h} px  ·  {size_str}{extra}"
            )
        except Exception as exc:
            self._clear_side(frame, placeholder=f"Errore: {exc}")

    @staticmethod
    def _clear_side(frame, placeholder: str = "—") -> None:
        frame._img_lbl.configure(image=None, text=placeholder,
                                 text_color="#555",
                                 font=ctk.CTkFont(size=11))
        frame._info_lbl.configure(text="")
