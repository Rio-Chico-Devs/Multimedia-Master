"""
Enhance Tab — noise reduction and loudness normalisation.

Pipeline (all optional, user-selectable):
  1. Noise reduction   — spectral gating via noisereduce
  2. Peak normalisation — scales to -0.45 dBFS headroom
  3. Export to original format (or choose a new one)
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine
from core.dependencies import DepStatus
from core.formats import AUDIO_EXTS
from .widgets import MediaFilePicker


class EnhanceTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine = engine
        self._deps   = deps
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        # File picker
        self._picker = MediaFilePicker(
            self, label="File audio",
            exts=AUDIO_EXTS,
            on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))

        # Options
        opts = ctk.CTkFrame(self, fg_color=("#111", "#111"), corner_radius=10)
        opts.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 0))
        opts.grid_columnconfigure(0, weight=1)
        opts.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Denoise column ────────────────────────────────────────────────
        left = ctk.CTkFrame(opts, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        SectionLabel(left, "🎛  Riduzione rumore").pack(fill="x", pady=(0, 6))

        nr_ok = self._deps.noisereduce and self._deps.soundfile and self._deps.numpy
        if not nr_ok:
            ctk.CTkLabel(
                left,
                text="⚠  Richiede: pip install noisereduce soundfile numpy",
                text_color="#f44336", font=ctk.CTkFont(size=10),
                anchor="w",
            ).pack(fill="x", pady=(0, 8))

        self._denoise_var = ctk.BooleanVar(value=nr_ok)
        ctk.CTkCheckBox(
            left, text="Riduci rumore di fondo",
            variable=self._denoise_var,
            state="normal" if nr_ok else "disabled",
        ).pack(anchor="w", pady=2)

        SectionLabel(left, "Intensità rimozione rumore").pack(
            fill="x", pady=(10, 2))
        self._strength_lbl = ctk.CTkLabel(
            left, text="75%", anchor="w",
            font=ctk.CTkFont(size=11))
        self._strength_lbl.pack(anchor="w")
        self._strength = ctk.CTkSlider(
            left, from_=0.1, to=1.0, number_of_steps=18,
            state="normal" if nr_ok else "disabled",
            command=lambda v: self._strength_lbl.configure(
                text=f"{int(v*100)}%"))
        self._strength.set(0.75)
        self._strength.pack(fill="x", pady=(2, 0))

        ctk.CTkLabel(
            left,
            text="Valori alti rimuovono più rumore\n"
                 "ma possono alterare il suono.",
            text_color="#777", font=ctk.CTkFont(size=10),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # ── Normalise column ──────────────────────────────────────────────
        right = ctk.CTkFrame(opts, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)

        SectionLabel(right, "📊  Normalizzazione").pack(fill="x", pady=(0, 6))

        self._norm_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            right, text="Normalizza volume (peak)",
            variable=self._norm_var,
        ).pack(anchor="w", pady=2)

        ctk.CTkLabel(
            right,
            text="Porta il volume al massimo possibile\n"
                 "senza distorsioni (-0.45 dBFS).",
            text_color="#777", font=ctk.CTkFont(size=10),
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        Separator(right).pack(fill="x", pady=12)

        SectionLabel(right, "Formato output").pack(fill="x", pady=(0, 4))
        self._out_fmt_var = ctk.StringVar(value="Stesso del file")
        ctk.CTkOptionMenu(
            right, variable=self._out_fmt_var,
            values=["Stesso del file", "WAV", "FLAC", "MP3", "OGG"],
            dynamic_resizing=False,
        ).pack(fill="x")

        SectionLabel(right, "Cartella output").pack(fill="x", pady=(12, 2))
        self._dir_lbl = ctk.CTkLabel(
            right, text="(stessa cartella del file)",
            text_color="gray", font=ctk.CTkFont(size=10), anchor="w")
        self._dir_lbl.pack(fill="x")
        ctk.CTkButton(right, text="Scegli", height=28,
                      command=self._choose_dir).pack(fill="x", pady=(4, 0))
        self._out_dir: Path | None = None

        # Bottom bar
        self._progress = ctk.CTkProgressBar(self, height=6, corner_radius=3)
        self._progress.set(0)
        self._progress.grid(row=2, column=0, sticky="ew",
                            padx=12, pady=(8, 0))

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)
        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")
        self._btn_run = ctk.CTkButton(
            bot, text="✨  Migliora",
            width=130, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._run)
        self._btn_run.grid(row=0, column=1, padx=(8, 0))

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_file_change(self, path: Path | None) -> None:
        if hasattr(self, "_btn_run"):
            self._btn_run.configure(
                state="normal" if path else "disabled")

    def _choose_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(
                text=f"…/{Path(d).name}", text_color="white")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        src = self._picker.get_path()
        if not src:
            return

        fmt_choice = self._out_fmt_var.get()
        if fmt_choice == "Stesso del file":
            ext = src.suffix.lower()
        else:
            ext_map = {"WAV": ".wav", "FLAC": ".flac",
                       "MP3": ".mp3", "OGG": ".ogg"}
            ext = ext_map.get(fmt_choice, src.suffix.lower())

        out_dir = self._out_dir or src.parent
        output  = out_dir / (src.stem + "_enhanced" + ext)

        self._btn_run.configure(state="disabled")
        self._progress.set(0)
        self._status.busy("Elaborazione in corso…")
        threading.Thread(
            target=self._worker,
            args=(src, output),
            daemon=True,
        ).start()

    def _worker(self, src: Path, output: Path) -> None:
        def _prog(p: float) -> None:
            self.after(0, self._progress.set, p)
            self.after(0, self._status.busy,
                       f"Elaborazione… {int(p*100)}%")

        result = self._engine.enhance(
            src=src,
            output=output,
            denoise=self._denoise_var.get(),
            normalize=self._norm_var.get(),
            prop_decrease=self._strength.get(),
            progress_cb=_prog,
        )
        if result.success:
            self.after(0, self._status.ok, f"Salvato: {output.name}")
            self.after(0, self._progress.set, 1.0)
        else:
            self.after(0, self._status.err, result.error)
        self.after(0, self._btn_run.configure, {"state": "normal"})
