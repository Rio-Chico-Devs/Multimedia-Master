"""
Enhance Tab — batch noise reduction + loudness normalisation.

Pipeline (all optional, user-selectable):
  1. Noise reduction   — spectral gating via noisereduce
  2. Peak normalisation — scales to -0.45 dBFS headroom
  3. Export: stesso nome, stessa o nuova estensione

Works on any format (MP3/AAC are decoded to temp WAV internally).
Keeps the original filename; only the extension changes if a new format is chosen.
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine
from core.dependencies import DepStatus
from core.formats import AUDIO_EXTS


_BTN_INACTIVE = "#2a2a2a"

_EXT_MAP = {
    "Stesso del file": None,
    "WAV":  ".wav",
    "FLAC": ".flac",
    "MP3":  ".mp3",
    "OGG":  ".ogg",
}


class EnhanceTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine  = engine
        self._deps    = deps
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

        # Denoise
        SectionLabel(right, "🎛  Riduzione rumore").pack(
            fill="x", padx=12, pady=(12, 6))

        nr_ok = self._deps.noisereduce and self._deps.soundfile and self._deps.numpy
        if not nr_ok:
            ctk.CTkLabel(
                right,
                text="⚠  pip install noisereduce soundfile numpy",
                text_color="#f44336", font=ctk.CTkFont(size=10),
                anchor="w",
            ).pack(fill="x", padx=16, pady=(0, 6))

        self._denoise_var = ctk.BooleanVar(value=nr_ok)
        ctk.CTkCheckBox(right, text="Riduci rumore di fondo",
                        variable=self._denoise_var,
                        state="normal" if nr_ok else "disabled",
                        ).pack(anchor="w", padx=16, pady=2)

        SectionLabel(right, "Intensità").pack(fill="x", padx=12, pady=(8, 2))
        self._strength_lbl = ctk.CTkLabel(right, text="75%", anchor="w",
                                           font=ctk.CTkFont(size=11))
        self._strength_lbl.pack(anchor="w", padx=16)
        self._strength = ctk.CTkSlider(
            right, from_=0.1, to=1.0, number_of_steps=18,
            state="normal" if nr_ok else "disabled",
            command=lambda v: self._strength_lbl.configure(
                text=f"{int(v*100)}%"))
        self._strength.set(0.75)
        self._strength.pack(fill="x", padx=16, pady=(2, 0))
        ctk.CTkLabel(right,
                     text="Valori alti rimuovono più rumore\n"
                          "ma possono alterare il suono.",
                     text_color="#777", font=ctk.CTkFont(size=10),
                     justify="left",
                     ).pack(anchor="w", padx=16, pady=(4, 8))

        Separator(right).pack()

        # Normalise
        SectionLabel(right, "📊  Normalizzazione").pack(
            fill="x", padx=12, pady=(10, 6))
        self._norm_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(right, text="Normalizza volume (peak -0.45 dBFS)",
                        variable=self._norm_var,
                        ).pack(anchor="w", padx=16, pady=2)

        Separator(right).pack(pady=(8, 0))

        # Format
        SectionLabel(right, "Formato output").pack(
            fill="x", padx=12, pady=(10, 4))
        self._out_fmt_var = ctk.StringVar(value="Stesso del file")
        ctk.CTkOptionMenu(
            right, variable=self._out_fmt_var,
            values=list(_EXT_MAP.keys()),
            dynamic_resizing=False,
        ).pack(fill="x", padx=12)
        ctk.CTkLabel(right,
                     text="Il nome del file viene preservato;\n"
                          "cambia solo l'estensione se selezioni\n"
                          "un formato diverso.",
                     text_color="#777", font=ctk.CTkFont(size=10),
                     justify="left",
                     ).pack(anchor="w", padx=12, pady=(4, 8))

        Separator(right).pack()

        # Output dir
        SectionLabel(right, "📁  Cartella output").pack(
            fill="x", padx=12, pady=(10, 2))
        self._dir_lbl = ctk.CTkLabel(
            right, text="(stessa cartella dei file)",
            text_color="gray", font=ctk.CTkFont(size=10), anchor="w")
        self._dir_lbl.pack(fill="x", padx=12)
        ctk.CTkButton(right, text="Scegli", height=28,
                      command=self._choose_dir,
                      ).pack(fill="x", padx=12, pady=(4, 12))

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
            bot, text="✨  Migliora",
            width=130, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._run)
        self._btn_run.grid(row=0, column=1, padx=(8, 0))

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
        row = ctk.CTkFrame(self._list_sf, fg_color="#222", corner_radius=6)
        row.pack(fill="x", pady=2)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=path.name, anchor="w",
                     font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, padx=(8, 4), pady=4, sticky="ew")
        status = ctk.CTkLabel(row, text="—", width=36,
                               text_color="gray", font=ctk.CTkFont(size=11))
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

    def _choose_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(
                text=f"…/{Path(d).name}", text_color="white")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if not self._file_rows:
            self._status.err("Aggiungi almeno un file audio.")
            return

        fmt_choice = self._out_fmt_var.get()
        new_ext    = _EXT_MAP[fmt_choice]   # None = keep original ext

        self._btn_run.configure(state="disabled")
        self._progress.set(0)
        self._status.busy(f"Avvio (0/{len(self._file_rows)})…")
        threading.Thread(
            target=self._worker, args=(new_ext,), daemon=True,
        ).start()

    def _worker(self, new_ext: str | None) -> None:
        import sys
        total  = len(self._file_rows)
        ok     = 0
        errors: list[str] = []

        def _prog(p: float, i: int) -> None:
            overall = (i + p) / total
            self.after(0, self._progress.set, overall)

        for i, (path, _, lbl) in enumerate(self._file_rows):
            ext     = new_ext or path.suffix.lower()
            out_dir = self._out_dir or path.parent
            output  = out_dir / (path.stem + ext)

            self.after(0, lbl.configure, {"text": "⏳", "text_color": "#aaa"})
            result = self._engine.enhance(
                src=path,
                output=output,
                denoise=self._denoise_var.get(),
                normalize=self._norm_var.get(),
                prop_decrease=self._strength.get(),
                progress_cb=lambda p, _i=i: _prog(p, _i),
            )
            if result.success:
                ok += 1
                self.after(0, lbl.configure,
                           {"text": "✓", "text_color": "#4caf50"})
            else:
                err = result.error or "Errore sconosciuto"
                errors.append(f"{path.name}: {err}")
                print(f"[ERRORE] {path.name}\n{err}\n", file=sys.stderr)
                self.after(0, lbl.configure,
                           {"text": "✗", "text_color": "#f44336"})
            self.after(0, self._status.busy, f"In corso ({i+1}/{total})…")

        if ok == total:
            self.after(0, self._status.ok, f"{ok}/{total} migliorati")
        else:
            first_err = errors[0] if errors else ""
            self.after(0, self._status.err,
                       f"{ok}/{total} completati · {total-ok} errori — {first_err}")
        self.after(0, self._progress.set, 1.0)
        self.after(0, lambda: self._btn_run.configure(state="normal"))
