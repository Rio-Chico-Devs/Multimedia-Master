import tkinter as tk
import customtkinter as ctk
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk

from core.formats import ConversionResult


class PreviewPanel(ctk.CTkFrame):
    """
    Full-width bottom strip with a draggable before/after comparison slider.
    Original is shown on the left half, converted on the right half.
    Drag the vertical divider to reveal more of either side.
    When only the source is available (not yet converted), fills the full width.
    """

    _BG = (28, 28, 28)

    def __init__(self, parent, height: int = 210, **kw):
        kw["height"] = height
        super().__init__(parent, **kw)
        self.grid_propagate(False)

        self._pil_left:  Image.Image | None = None
        self._pil_right: Image.Image | None = None
        self._info_left  = ""
        self._info_right = ""
        self._slider_x   = 0.5                           # normalised 0–1
        self._photo: ImageTk.PhotoImage | None = None    # GC anchor

        self._build()

    # ── Public API ─────────────────────────────────────────────────────────────

    def show_source(self, path: Path) -> None:
        """Display only the original; right placeholder until conversion runs."""
        self._pil_left, self._info_left = self._load_image(path)
        self._pil_right  = None
        self._info_right = "Converti per vedere il risultato"
        self._render()

    def show_result(self, result: ConversionResult) -> None:
        """Display both halves after a successful conversion."""
        self._pil_left, self._info_left = self._load_image(result.source)
        if result.success:
            self._pil_right, info_r = self._load_image(result.output)
            d    = result.delta_pct
            sign = "-" if d >= 0 else "+"
            self._info_right = f"{info_r}  ·  {sign}{abs(d)}%"
        else:
            self._pil_right  = None
            self._info_right = f"Errore: {result.error}"
        self._render()

    def clear(self) -> None:
        self._pil_left   = None
        self._pil_right  = None
        self._info_left  = ""
        self._info_right = ""
        self._render()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._canvas = tk.Canvas(
            self, bg="#1c1c1c",
            cursor="sb_h_double_arrow",
            highlightthickness=0,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew", padx=10, pady=(8, 2))
        self._canvas.bind("<Configure>", self._on_resize)
        self._canvas.bind("<B1-Motion>", self._on_drag)

        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        info_row.grid_columnconfigure(0, weight=1)
        info_row.grid_columnconfigure(1, weight=1)

        self._lbl_left = ctk.CTkLabel(
            info_row, text="",
            anchor="center", text_color="#666",
            font=ctk.CTkFont(size=10),
        )
        self._lbl_left.grid(row=0, column=0, sticky="ew")

        self._lbl_right = ctk.CTkLabel(
            info_row, text="",
            anchor="center", text_color="#666",
            font=ctk.CTkFont(size=10),
        )
        self._lbl_right.grid(row=0, column=1, sticky="ew")

    # ── Slider interaction ─────────────────────────────────────────────────────

    def _on_resize(self, _event) -> None:
        self._render()

    def _on_drag(self, event) -> None:
        if self._pil_right is None:
            return
        w = self._canvas.winfo_width()
        if w > 1:
            self._slider_x = max(0.02, min(0.98, event.x / w))
            self._render()

    # ── Composite rendering ────────────────────────────────────────────────────

    def _render(self) -> None:
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 4 or h < 4:
            return

        self._canvas.delete("all")

        if self._pil_left is None:
            self._canvas.create_text(
                w // 2, h // 2,
                text="Seleziona un file per l'anteprima",
                fill="#444", font=("", 11),
            )
            self._lbl_left.configure(text="")
            self._lbl_right.configure(text="")
            return

        img_l = self._fit_to(self._pil_left, w, h)

        if self._pil_right is not None:
            img_r = self._fit_to(self._pil_right, w, h)
            split = int(self._slider_x * w)

            def _plane(img: Image.Image) -> Image.Image:
                """Centre img on a canvas-sized plane."""
                p = Image.new("RGB", (w, h), self._BG)
                p.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
                return p

            composite = Image.new("RGB", (w, h), self._BG)
            lp = _plane(img_l)
            rp = _plane(img_r)
            if split > 0:
                composite.paste(lp.crop((0, 0, split, h)), (0, 0))
            if split < w:
                composite.paste(rp.crop((split, 0, w, h)), (split, 0))

            # Divider line
            draw = ImageDraw.Draw(composite)
            draw.line([(split, 0), (split, h)], fill=(190, 190, 190), width=2)

            # Circular drag handle
            cy, r = h // 2, 11
            draw.ellipse(
                [(split - r, cy - r), (split + r, cy + r)],
                fill=(210, 210, 210), outline=(130, 130, 130), width=1,
            )
            # Arrow triangles pointing left and right
            draw.polygon(
                [(split - 7, cy), (split - 2, cy - 4), (split - 2, cy + 4)],
                fill=(60, 60, 60),
            )
            draw.polygon(
                [(split + 7, cy), (split + 2, cy - 4), (split + 2, cy + 4)],
                fill=(60, 60, 60),
            )
        else:
            # Only source — fill full width
            composite = Image.new("RGB", (w, h), self._BG)
            composite.paste(img_l, ((w - img_l.width) // 2,
                                    (h - img_l.height) // 2))

        self._photo = ImageTk.PhotoImage(composite)
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)

        self._lbl_left.configure(text=self._info_left  or "Originale")
        self._lbl_right.configure(text=self._info_right or "—")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _fit_to(self, pil: Image.Image, max_w: int, max_h: int) -> Image.Image:
        """Thumbnail image within bounds and flatten alpha onto _BG."""
        img = pil.copy()
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, self._BG)
            bg.paste(img, mask=img.split()[3])
            return bg
        if img.mode != "RGB":
            return img.convert("RGB")
        return img

    @staticmethod
    def _load_image(path: Path) -> tuple[Image.Image | None, str]:
        """Open image + build info string; never raises."""
        try:
            pil = Image.open(path)
            orig_w, orig_h = pil.size   # size is available before full load
            # Hint the JPEG decoder to decode at ≤ half resolution —
            # a 20 MP photo needs ~70 MB uncompressed; draft() keeps it ≤ 18 MB.
            # This is a no-op for PNG, WebP, TIFF and other formats.
            pil.draft("RGB", (3840, 2160))
            # Decode into memory, then return a DETACHED copy so the file
            # handle can be released without breaking the returned image.
            # Image.close() destroys the decoded core (sets .im to a
            # DeferredError) — so the returned image must be an independent
            # copy(), and closing the original releases the OS file handle
            # (avoids the Windows source-file lock).
            pil.load()
            img = pil.copy()
            pil.close()
            size_b   = path.stat().st_size
            size_str = (f"{size_b / 1024:.0f} KB" if size_b < 1_048_576
                        else f"{size_b / 1_048_576:.2f} MB")
            return img, f"{orig_w}×{orig_h} px  ·  {size_str}"
        except Exception as exc:
            return None, f"Errore: {exc}"
