import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog

from common.settings import Settings
from core.formats import (
    OUTPUT_FORMATS, QUALITY_DEFAULTS, QUALITY_HINTS,
    NO_QUALITY_FORMATS, ConversionConfig,
)
from core.profiles import PROFILE_NAMES, get_profile
from ui.widgets import SectionLabel, Separator, adaptive_wraplength


class SettingsSidebar(ctk.CTkScrollableFrame):
    """
    Right panel — profile selector, format, quality, optional resize,
    metadata toggle, output directory chooser.
    Scrollable: on short windows every section stays reachable instead of
    being clipped at the bottom.
    Exposes get_config() → ConversionConfig used by MainWindow.

    Settings persist across sessions via common.settings, so the tool reopens
    with the user's last format, quality, metadata choice and output folder.
    """

    def __init__(self, parent, **kw):
        kw.setdefault("width", 248)
        super().__init__(parent, **kw)
        self._output_dir: Path | None = None
        self._applying_profile = False   # guard against recursive callbacks
        self._settings = Settings("image_converter")
        self._build()
        self._restore()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_config(self) -> ConversionConfig:
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
            pady=(18, 6), padx=18)

        self._build_profiles()
        Separator(self).pack()
        self._build_format()
        self._build_quality()
        Separator(self).pack()
        self._build_resize()
        Separator(self).pack()
        self._build_options()
        Separator(self).pack()
        self._build_output_dir()

    def _build_profiles(self) -> None:
        SectionLabel(self, text="Profilo").pack(fill="x", padx=18, pady=(6, 2))

        self._profile_var = ctk.StringVar(value="Personalizzato")
        ctk.CTkOptionMenu(
            self, values=PROFILE_NAMES,
            variable=self._profile_var,
            command=self._on_profile_change,
            dynamic_resizing=False,
        ).pack(fill="x", padx=18, pady=(0, 2))

        self._profile_hint = ctk.CTkLabel(
            self, text="Usa le impostazioni manuali",
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=220, justify="left",
        )
        self._profile_hint.pack(fill="x", padx=18, pady=(0, 4))
        adaptive_wraplength(self._profile_hint)

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
        adaptive_wraplength(self._quality_hint)

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
        self._w_entry.bind("<FocusOut>", lambda _: self._validate_dim(self._w_entry))
        self._h_entry = ctk.CTkEntry(grid, placeholder_text="es. 1080")
        self._h_entry.grid(row=1, column=1, pady=2, sticky="ew")
        self._h_entry.bind("<FocusOut>", lambda _: self._validate_dim(self._h_entry))

        ctk.CTkLabel(
            self, text="Mantiene proporzioni · non ingrandisce mai",
            text_color="gray", font=ctk.CTkFont(size=10), anchor="w",
        ).pack(fill="x", padx=18, pady=(2, 6))

    def _build_options(self) -> None:
        SectionLabel(self, text="Opzioni").pack(fill="x", padx=18, pady=(10, 4))
        self._strip_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self, text="Rimuovi metadati (EXIF/GPS)",
                        variable=self._strip_var,
                        command=self._on_manual_change).pack(
            fill="x", padx=18, pady=2)
        ctk.CTkLabel(
            self,
            text="L'orientamento viene sempre applicato ai pixel,\n"
                 "quindi le foto non escono mai ruotate male.",
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", justify="left",
        ).pack(fill="x", padx=18, pady=(0, 4))

    def _build_output_dir(self) -> None:
        SectionLabel(self, text="Cartella output").pack(
            fill="x", padx=18, pady=(10, 2))
        self._outdir_lbl = ctk.CTkLabel(
            self, text="Stessa cartella dei file originali",
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=220, justify="left",
        )
        self._outdir_lbl.pack(fill="x", padx=18, pady=(0, 4))
        adaptive_wraplength(self._outdir_lbl)

        ctk.CTkButton(self, text="Scegli cartella…", height=30,
                      command=self._choose_dir).pack(fill="x", padx=18, pady=(0, 4))
        ctk.CTkButton(self, text="Ripristina cartella originale",
                      height=28, fg_color="transparent", border_width=1,
                      command=self._reset_dir).pack(fill="x", padx=18,
                                                    pady=(0, 14))

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _on_profile_change(self, name: str) -> None:
        profile = get_profile(name)
        if not profile or name == "Personalizzato":
            self._profile_hint.configure(text="Usa le impostazioni manuali")
            return

        self._applying_profile = True
        cfg = profile.config

        # format
        self._fmt_var.set(cfg.format)
        self._on_format_change(cfg.format)

        # quality
        self._quality_slider.set(cfg.quality)
        self._quality_lbl.configure(text=f"Qualità: {cfg.quality}")

        # resize
        self._w_entry.delete(0, "end")
        self._h_entry.delete(0, "end")
        if cfg.target_w:
            self._w_entry.insert(0, str(cfg.target_w))
        if cfg.target_h:
            self._h_entry.insert(0, str(cfg.target_h))

        # metadata
        self._strip_var.set(cfg.strip_meta)

        self._profile_hint.configure(text=profile.description)
        self._applying_profile = False

    def _on_format_change(self, fmt: str) -> None:
        q = QUALITY_DEFAULTS.get(fmt, 85)
        self._quality_slider.set(q)
        self._quality_lbl.configure(text=f"Qualità: {q}")
        self._quality_hint.configure(text=QUALITY_HINTS.get(fmt, ""))
        self._quality_slider.configure(
            state="disabled" if fmt in NO_QUALITY_FORMATS else "normal")
        self._on_manual_change()

    def _on_quality_change(self, val) -> None:
        self._quality_lbl.configure(text=f"Qualità: {int(val)}")
        self._on_manual_change()

    def _on_manual_change(self) -> None:
        """Any manual edit switches the profile selector to 'Personalizzato'."""
        if not self._applying_profile:
            self._profile_var.set("Personalizzato")
            self._profile_hint.configure(text="Usa le impostazioni manuali")
            self._persist()

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory(title="Scegli cartella di output")
        if d:
            self._output_dir = Path(d)
            self._outdir_lbl.configure(text=str(self._output_dir))
            self._persist()

    def _reset_dir(self) -> None:
        self._output_dir = None
        self._outdir_lbl.configure(text="Stessa cartella dei file originali")
        self._persist()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Save the current settings so the next session starts where this ended."""
        self._settings.set(
            format=self._fmt_var.get(),
            quality=int(self._quality_slider.get()),
            strip_meta=bool(self._strip_var.get()),
            target_w=self._parse_int(self._w_entry.get()),
            target_h=self._parse_int(self._h_entry.get()),
            output_dir=str(self._output_dir) if self._output_dir else None,
        )

    def _restore(self) -> None:
        """Reapply the previous session's settings. Missing keys keep defaults."""
        # Guard so restore-time callbacks don't fire a redundant _persist().
        self._applying_profile = True
        try:
            fmt = self._settings.get("format")
            if fmt in OUTPUT_FORMATS:
                self._fmt_var.set(fmt)
                self._on_format_change(fmt)   # default quality + hint + state

            q = self._settings.get("quality")
            if isinstance(q, int) and 1 <= q <= 100:
                self._quality_slider.set(q)
                self._quality_lbl.configure(text=f"Qualità: {q}")

            sm = self._settings.get("strip_meta")
            if isinstance(sm, bool):
                self._strip_var.set(sm)

            for key, entry in (("target_w", self._w_entry),
                               ("target_h", self._h_entry)):
                v = self._settings.get(key)
                if isinstance(v, int) and v > 0:
                    entry.delete(0, "end")
                    entry.insert(0, str(v))

            od = self._settings.get("output_dir")
            if od:
                p = Path(od)
                if p.is_dir():
                    self._output_dir = p
                    self._outdir_lbl.configure(text=str(p))
        finally:
            self._applying_profile = False

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _validate_dim(self, entry: ctk.CTkEntry) -> None:
        """Highlight entry in red if value is non-empty and non-numeric."""
        val = entry.get().strip()
        if val and self._parse_int(val) is None:
            entry.configure(border_color="#f44336")   # red
        else:
            entry.configure(border_color=["#979DA2", "#565B5E"])  # CTk default
            self._persist()   # persist valid resize dimensions

    @staticmethod
    def _parse_int(value: str) -> int | None:
        try:
            v = int(value.strip())
            return v if v > 0 else None
        except (ValueError, AttributeError):
            return None
