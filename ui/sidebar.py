import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog

from core.formats import (
    OUTPUT_FORMATS, QUALITY_DEFAULTS, QUALITY_HINTS,
    NO_QUALITY_FORMATS, ConversionConfig,
)
from ui.widgets import SectionLabel, Separator


class SettingsSidebar(ctk.CTkFrame):
    """
    Right panel — format selector, quality slider, optional resize,
    metadata toggle, and output directory chooser.
    Exposes a single get_config() method used by MainWindow.
    """

    def __init__(self, parent, **kw):
        kw.setdefault("width", 260)
        super().__init__(parent, **kw)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self._output_dir: Path | None = None
        self._build()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_config(self) -> ConversionConfig:
        """Snapshot the current UI state into a ConversionConfig dataclass."""
        return ConversionConfig(
            format=self._fmt_var.get(),
            quality=int(self._quality_slider.get()),
            target_w=self._parse_int(self._w_entry.get()),
            target_h=self._parse_int(self._h_entry.get()),
            strip_meta=self._strip_var.get(),
            output_dir=self._output_dir,
        )

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Impostazioni",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(18, 10), padx=18)

        self._build_format()
        self._build_quality()
        Separator(self).pack()
        self._build_resize()
        Separator(self).pack()
        self._build_options()
        Separator(self).pack()
        self._build_output_dir()

    def _build_format(self) -> None:
        SectionLabel(self, text="Formato output").pack(
            fill="x", padx=18, pady=(6, 2))
        self._fmt_var = ctk.StringVar(value="WebP")
        ctk.CTkOptionMenu(
            self, values=OUTPUT_FORMATS,
            variable=self._fmt_var,
            command=self._on_format_change,
            dynamic_resizing=False,
        ).pack(fill="x", padx=18, pady=(0, 4))

    def _build_quality(self) -> None:
        self._quality_lbl = SectionLabel(self, text="Qualità: 85")
        self._quality_lbl.pack(fill="x", padx=18, pady=(10, 2))

        self._quality_slider = ctk.CTkSlider(
            self, from_=1, to=100, number_of_steps=99,
            command=self._on_quality_change,
        )
        self._quality_slider.set(85)
        self._quality_slider.pack(fill="x", padx=18)

        self._quality_hint = ctk.CTkLabel(
            self, text=QUALITY_HINTS["WebP"],
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=220, justify="left",
        )
        self._quality_hint.pack(fill="x", padx=18, pady=(2, 6))

    def _build_resize(self) -> None:
        SectionLabel(self, text="Ridimensiona  (opzionale)").pack(
            fill="x", padx=18, pady=(10, 4))

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=18)
        grid.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(grid, text="Larghezza px", anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(grid, text="Altezza px", anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w")

        self._w_entry = ctk.CTkEntry(grid, placeholder_text="es. 1920")
        self._w_entry.grid(row=1, column=0, padx=(0, 4), pady=2, sticky="ew")
        self._h_entry = ctk.CTkEntry(grid, placeholder_text="es. 1080")
        self._h_entry.grid(row=1, column=1, pady=2, sticky="ew")

        ctk.CTkLabel(
            self, text="Mantiene proporzioni · non ingrandisce mai",
            text_color="gray", font=ctk.CTkFont(size=10), anchor="w",
        ).pack(fill="x", padx=18, pady=(2, 6))

    def _build_options(self) -> None:
        SectionLabel(self, text="Opzioni").pack(fill="x", padx=18, pady=(10, 4))
        self._strip_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self, text="Rimuovi metadati EXIF",
                        variable=self._strip_var).pack(fill="x", padx=18, pady=2)

    def _build_output_dir(self) -> None:
        SectionLabel(self, text="Cartella output").pack(
            fill="x", padx=18, pady=(10, 2))
        self._outdir_lbl = ctk.CTkLabel(
            self, text="Stessa cartella dei file originali",
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=220, justify="left",
        )
        self._outdir_lbl.pack(fill="x", padx=18, pady=(0, 4))

        ctk.CTkButton(self, text="Scegli cartella…", height=30,
                      command=self._choose_dir).pack(fill="x", padx=18, pady=(0, 4))
        ctk.CTkButton(self, text="Ripristina cartella originale",
                      height=28, fg_color="transparent", border_width=1,
                      command=self._reset_dir).pack(fill="x", padx=18)

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _on_format_change(self, fmt: str) -> None:
        q = QUALITY_DEFAULTS.get(fmt, 85)
        self._quality_slider.set(q)
        self._quality_lbl.configure(text=f"Qualità: {q}")
        self._quality_hint.configure(text=QUALITY_HINTS.get(fmt, ""))
        self._quality_slider.configure(
            state="disabled" if fmt in NO_QUALITY_FORMATS else "normal")

    def _on_quality_change(self, val) -> None:
        self._quality_lbl.configure(text=f"Qualità: {int(val)}")

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory(title="Scegli cartella di output")
        if d:
            self._output_dir = Path(d)
            self._outdir_lbl.configure(text=str(self._output_dir))

    def _reset_dir(self) -> None:
        self._output_dir = None
        self._outdir_lbl.configure(text="Stessa cartella dei file originali")

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_int(value: str) -> int | None:
        try:
            v = int(value.strip())
            return v if v > 0 else None
        except (ValueError, AttributeError):
            return None
