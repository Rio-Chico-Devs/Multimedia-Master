"""
Convert Tab — batch audio format conversion with quality presets.

Features:
  • Add multiple audio files (browse or drag & drop)
  • Quick presets: Web, Podcast, Music, Cinematic, Lossless, Max, Custom
  • Custom mode: format, bitrate, sample rate, channels
  • Progress per-file + overall progress bar
  • Threaded — UI never freezes
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine
from core.formats import AUDIO_FORMATS, PRESETS, AUDIO_EXTS


_BTN_INACTIVE = "#2a2a2a"


class ConvertTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine   = engine
        self._out_dir: Path | None = None
        self._file_rows: list[tuple[Path, ctk.CTkFrame, ctk.CTkLabel]] = []
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # ── Left: file list ──────────────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color=("#111", "#111"), corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        tb = ctk.CTkFrame(left, fg_color="transparent")
        tb.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        ctk.CTkButton(tb, text="＋ Aggiungi", width=100, height=28,
                      command=self._add_files).pack(side="left", padx=(0, 4))
        ctk.CTkButton(tb, text="Rimuovi", width=80, height=28,
                      fg_color=_BTN_INACTIVE, hover_color="#3a3a3a",
                      command=self._remove_last).pack(side="left", padx=2)
        ctk.CTkButton(tb, text="Pulisci", width=70, height=28,
                      fg_color=_BTN_INACTIVE, hover_color="#3a3a3a",
                      command=self._clear).pack(side="left", padx=2)

        self._list_sf = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._list_sf.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._list_sf.grid_columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._list_sf,
            text="Nessun file  ·  clicca ＋ Aggiungi",
            text_color="#555", font=ctk.CTkFont(size=11))
        self._empty_lbl.pack(expand=True, pady=20)

        # ── Right: options ────────────────────────────────────────────────
        right = ctk.CTkScrollableFrame(self, fg_color=("#111", "#111"),
                                        corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        SectionLabel(right, "Preset").pack(fill="x", padx=12, pady=(12, 6))

        self._preset_var = ctk.StringVar(value="music")
        for key, info in PRESETS.items():
            if key == "custom":
                continue
            ctk.CTkRadioButton(
                right, text=info.label,
                variable=self._preset_var, value=key,
                command=self._on_preset_change,
            ).pack(anchor="w", padx=16, pady=2)
        ctk.CTkRadioButton(
            right, text="Personalizzato",
            variable=self._preset_var, value="custom",
            command=self._on_preset_change,
        ).pack(anchor="w", padx=16, pady=2)

        self._preset_desc = ctk.CTkLabel(
            right, text=PRESETS["music"].desc,
            text_color="#777", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=200, justify="left")
        self._preset_desc.pack(fill="x", padx=16, pady=(4, 8))

        Separator(right).pack()

        # Custom panel
        self._custom_frame = ctk.CTkFrame(right, fg_color="transparent")
        self._custom_frame.grid_columnconfigure(0, weight=1)

        SectionLabel(self._custom_frame, "Formato").pack(
            fill="x", padx=12, pady=(8, 2))
        self._fmt_var = ctk.StringVar(value="mp3")
        ctk.CTkOptionMenu(
            self._custom_frame, variable=self._fmt_var,
            values=list(AUDIO_FORMATS.keys()),
            command=self._on_fmt_change,
            dynamic_resizing=False,
        ).pack(fill="x", padx=12, pady=(0, 6))

        self._bitrate_lbl = ctk.CTkLabel(
            self._custom_frame, text="Bitrate: 192 kbps",
            anchor="w", font=ctk.CTkFont(size=11, weight="bold"))
        self._bitrate_lbl.pack(fill="x", padx=12)
        self._bitrate_slider = ctk.CTkSlider(
            self._custom_frame, from_=32, to=320, number_of_steps=29,
            command=lambda v: self._bitrate_lbl.configure(
                text=f"Bitrate: {int(v)} kbps"))
        self._bitrate_slider.set(192)
        self._bitrate_slider.pack(fill="x", padx=12, pady=(2, 6))

        SectionLabel(self._custom_frame, "Sample rate").pack(
            fill="x", padx=12, pady=(4, 2))
        self._sr_var = ctk.StringVar(value="Originale")
        ctk.CTkOptionMenu(
            self._custom_frame, variable=self._sr_var,
            values=["Originale", "44100 Hz", "48000 Hz", "96000 Hz"],
            dynamic_resizing=False,
        ).pack(fill="x", padx=12, pady=(0, 4))

        SectionLabel(self._custom_frame, "Canali").pack(
            fill="x", padx=12, pady=(4, 2))
        self._ch_var = ctk.StringVar(value="Originale")
        ctk.CTkOptionMenu(
            self._custom_frame, variable=self._ch_var,
            values=["Originale", "Mono (1)", "Stereo (2)"],
            dynamic_resizing=False,
        ).pack(fill="x", padx=12, pady=(0, 8))

        Separator(right).pack()

        # Output dir
        SectionLabel(right, "Cartella di destinazione").pack(
            fill="x", padx=12, pady=(8, 2))
        self._dir_lbl = ctk.CTkLabel(
            right, text="(stessa cartella dei file)",
            text_color="gray", font=ctk.CTkFont(size=10), anchor="w")
        self._dir_lbl.pack(fill="x", padx=12)
        ctk.CTkButton(right, text="Scegli cartella", height=28,
                      command=self._choose_dir).pack(
            fill="x", padx=12, pady=(4, 12))

        # ── Bottom bar ───────────────────────────────────────────────────
        self._progress = ctk.CTkProgressBar(self, height=6, corner_radius=3)
        self._progress.set(0)
        self._progress.grid(row=1, column=0, columnspan=2,
                            sticky="ew", pady=(6, 0))

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        bot.grid_columnconfigure(0, weight=1)
        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")
        self._btn_run = ctk.CTkButton(
            bot, text="▶  Converti",
            width=130, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._run)
        self._btn_run.grid(row=0, column=1, padx=(8, 0))

        self._on_preset_change()

    # ── File list ──────────────────────────────────────────────────────────

    def _add_files(self) -> None:
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Seleziona file audio",
            filetypes=[
                ("Audio", " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))),
                ("Tutti i file", "*.*"),
            ])
        self._add_paths([Path(p) for p in paths])

    def _add_paths(self, paths: list[Path]) -> None:
        existing = {r[0] for r in self._file_rows}
        for p in paths:
            if p not in existing:
                self._add_row(p)
        self._refresh_empty()

    def _add_row(self, path: Path) -> None:
        idx = len(self._file_rows)
        row = ctk.CTkFrame(self._list_sf, fg_color="#222", corner_radius=6)
        row.grid(row=idx, column=0, sticky="ew", pady=2)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=path.name, anchor="w",
                     font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, padx=(8, 4), pady=4, sticky="ew")
        status = ctk.CTkLabel(row, text="—", width=36,
                               text_color="gray",
                               font=ctk.CTkFont(size=11))
        status.grid(row=0, column=1, padx=(0, 8))
        self._file_rows.append((path, row, status))

    def _remove_last(self) -> None:
        if self._file_rows:
            _, row, _ = self._file_rows.pop()
            row.destroy()
            self._refresh_empty()

    def _clear(self) -> None:
        for _, row, _ in self._file_rows:
            row.destroy()
        self._file_rows.clear()
        self._refresh_empty()

    def _refresh_empty(self) -> None:
        if self._file_rows:
            self._empty_lbl.pack_forget()
        else:
            self._empty_lbl.pack(expand=True, pady=20)

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_preset_change(self, *_) -> None:
        key  = self._preset_var.get()
        info = PRESETS.get(key)
        if info:
            self._preset_desc.configure(text=info.desc)
        if key == "custom":
            self._custom_frame.pack(fill="x")
        else:
            self._custom_frame.pack_forget()

    def _on_fmt_change(self, fmt: str) -> None:
        lossy = AUDIO_FORMATS.get(fmt, AUDIO_FORMATS["mp3"]).lossy
        self._bitrate_slider.configure(
            state="normal" if lossy else "disabled")

    def _choose_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Cartella di destinazione")
        if d:
            self._out_dir = Path(d)
            name = Path(d).name
            self._dir_lbl.configure(text=f"…/{name}", text_color="white")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if not self._file_rows:
            self._status.err("Aggiungi almeno un file audio.")
            return

        key    = self._preset_var.get()
        preset = PRESETS[key]

        if key == "custom":
            fmt     = self._fmt_var.get()
            lossy   = AUDIO_FORMATS[fmt].lossy
            bitrate = int(self._bitrate_slider.get()) if lossy else None
            sr_str  = self._sr_var.get()
            sr      = int(sr_str.split()[0]) if sr_str != "Originale" else None
            ch_str  = self._ch_var.get()
            ch      = (1 if "Mono" in ch_str else 2 if "Stereo" in ch_str else None)
        else:
            fmt     = preset.fmt
            bitrate = preset.bitrate
            sr      = preset.sample_rate
            ch      = preset.channels

        self._btn_run.configure(state="disabled")
        self._progress.set(0)
        self._status.busy(f"Avvio conversione (0/{len(self._file_rows)})…")
        threading.Thread(
            target=self._worker, args=(fmt, bitrate, sr, ch), daemon=True
        ).start()

    def _worker(self, fmt: str, bitrate, sr, ch) -> None:
        ext   = AUDIO_FORMATS[fmt].ext
        total = len(self._file_rows)
        ok    = 0

        for i, (path, _, lbl) in enumerate(self._file_rows):
            out_dir = self._out_dir or path.parent
            output  = out_dir / (path.stem + ext)
            self.after(0, lbl.configure, {"text": "⏳", "text_color": "#aaa"})
            result = self._engine.convert(path, output, fmt, bitrate, sr, ch)
            if result.success:
                ok += 1
                self.after(0, lbl.configure,
                           {"text": "✓", "text_color": "#4caf50"})
            else:
                self.after(0, lbl.configure,
                           {"text": "✗", "text_color": "#f44336"})
            self.after(0, self._progress.set, (i + 1) / total)
            self.after(0, self._status.busy,
                       f"In corso ({i+1}/{total})…")

        msg = f"{ok}/{total} convertiti"
        if ok < total:
            self.after(0, self._status.err, msg + f" · {total-ok} errori")
        else:
            self.after(0, self._status.ok, msg)
        self.after(0, self._btn_run.configure, {"state": "normal"})
