"""
Clean Tab — batch voice cleaner: WAV → web-optimised MP3.

Pipeline (all pure ffmpeg, no Python audio math to avoid artefacts):
  1. highpass  — removes rumble & handling noise
  2. afftdn    — FFT-based noise reduction (voice-friendly)
  3. loudnorm  — EBU R128 broadcast-standard loudness (-16 LUFS)
  4. libmp3lame VBR — high-quality web-ready MP3

Preserves the original filename (only the extension changes to .mp3).
Processes many files in one go with per-file + overall progress.
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine


_BTN_INACTIVE = "#2a2a2a"

# libmp3lame VBR quality levels (-q:a); lower is better quality
_MP3_QUALITY = {
    "alta":    (2, "Alta qualità (~190 kbps VBR)"),
    "web":     (4, "Web ottimale (~165 kbps VBR)"),
    "leggera": (6, "Leggera (~130 kbps VBR)"),
}

_PRESETS = {
    "leggero":  "Leggero  ·  solo normalizza, mantiene naturalezza totale",
    "normale":  "Normale  ·  rimozione rumore bilanciata (consigliato)",
    "intenso":  "Intenso  ·  pulizia profonda + boost presenza voce",
}


class CleanTab(ctk.CTkFrame):
    """Batch voice-cleaner: accepts many WAV files, outputs .mp3 with same name."""

    def __init__(self, parent, engine: AudioEngine, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine = engine
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
        ctk.CTkButton(tb, text="＋ Aggiungi WAV", width=130, height=28,
                      command=self._add_files).pack(side="left", padx=(0, 4))
        ctk.CTkButton(tb, text="Rimuovi", width=80, height=28,
                      fg_color=_BTN_INACTIVE, hover_color="#3a3a3a",
                      command=self._remove_last).pack(side="left", padx=2)
        ctk.CTkButton(tb, text="Pulisci lista", width=110, height=28,
                      fg_color=_BTN_INACTIVE, hover_color="#3a3a3a",
                      command=self._clear).pack(side="left", padx=2)

        self._list_sf = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._list_sf.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        self._empty_lbl = ctk.CTkLabel(
            self._list_sf,
            text="Nessun file  ·  clicca ＋ Aggiungi WAV",
            text_color="#555", font=ctk.CTkFont(size=11))
        self._empty_lbl.pack(expand=True, pady=20)

        # ── Right: options ────────────────────────────────────────────────
        right = ctk.CTkScrollableFrame(self, fg_color=("#111", "#111"),
                                        corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        SectionLabel(right, "🧼  Intensità pulizia").pack(
            fill="x", padx=12, pady=(12, 6))

        self._preset_var = ctk.StringVar(value="normale")
        for key, desc in _PRESETS.items():
            ctk.CTkRadioButton(
                right, text=desc,
                variable=self._preset_var, value=key,
                command=self._on_preset_change,
            ).pack(anchor="w", padx=16, pady=2)

        self._preset_hint = ctk.CTkLabel(
            right,
            text="La voce originale viene sempre preservata —\n"
                 "vengono rimossi solo rumore e squilibri volume.",
            text_color="#777", font=ctk.CTkFont(size=10),
            anchor="w", justify="left", wraplength=220)
        self._preset_hint.pack(fill="x", padx=16, pady=(6, 8))

        Separator(right).pack()

        SectionLabel(right, "🎧  Qualità MP3").pack(
            fill="x", padx=12, pady=(10, 6))

        self._quality_var = ctk.StringVar(value="alta")
        for key, (_, label) in _MP3_QUALITY.items():
            ctk.CTkRadioButton(
                right, text=label,
                variable=self._quality_var, value=key,
            ).pack(anchor="w", padx=16, pady=2)

        Separator(right).pack(pady=(8, 0))

        SectionLabel(right, "🔊  Canali").pack(
            fill="x", padx=12, pady=(10, 4))
        self._mono_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            right, text="Converti a mono (file più piccolo)",
            variable=self._mono_var,
        ).pack(anchor="w", padx=16, pady=2)
        ctk.CTkLabel(
            right,
            text="Consigliato solo per voce solista.",
            text_color="#777", font=ctk.CTkFont(size=10),
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(2, 8))

        Separator(right).pack()

        SectionLabel(right, "📁  Cartella di destinazione").pack(
            fill="x", padx=12, pady=(10, 2))
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
            bot, text="✨  Pulisci e Converti",
            width=180, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._run)
        self._btn_run.grid(row=0, column=1, padx=(8, 0))

    # ── File list ──────────────────────────────────────────────────────────

    def _add_files(self) -> None:
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Seleziona file WAV",
            filetypes=[
                ("WAV", "*.wav"),
                ("Audio", "*.wav *.flac *.aiff *.aif"),
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
        preset = self._preset_var.get()
        hints = {
            "leggero": "Solo normalizzazione del volume.\n"
                        "Nessun intervento sul timbro.",
            "normale": "Rumore di fondo ridotto delicatamente,\n"
                        "volume uniformato (standard podcast).",
            "intenso": "Pulizia più spinta + leggero boost\n"
                        "della presenza vocale (2–5 kHz).",
        }
        self._preset_hint.configure(text=hints.get(preset, ""))

    def _choose_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Cartella di destinazione")
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(text=f"…/{Path(d).name}", text_color="white")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if not self._file_rows:
            self._status.err("Aggiungi almeno un file WAV.")
            return

        preset    = self._preset_var.get()
        mp3_q     = _MP3_QUALITY[self._quality_var.get()][0]
        to_mono   = self._mono_var.get()

        self._btn_run.configure(state="disabled")
        self._progress.set(0)
        self._status.busy(f"Avvio pulizia (0/{len(self._file_rows)})…")
        threading.Thread(
            target=self._worker, args=(preset, mp3_q, to_mono), daemon=True,
        ).start()

    def _worker(self, preset: str, mp3_q: int, to_mono: bool) -> None:
        import sys
        total  = len(self._file_rows)
        ok     = 0
        errors: list[str] = []

        for i, (path, _, lbl) in enumerate(self._file_rows):
            out_dir = self._out_dir or path.parent
            output  = out_dir / (path.stem + ".mp3")

            # Safety: never overwrite the source file if source is already .mp3
            if output.resolve() == path.resolve():
                err_msg = "Il file sorgente è già un MP3 con lo stesso nome."
                errors.append(f"{path.name}: {err_msg}")
                self.after(0, lambda l=lbl: l.configure(
                    text="✗", text_color="#f44336"))
                self.after(0, lambda p=(i + 1) / total: self._progress.set(p))
                continue

            self.after(0, lambda l=lbl: l.configure(
                text="⏳", text_color="#aaa"))
            result = self._engine.clean_voice(
                src=path, output=output,
                preset=preset, mp3_q=mp3_q, to_mono=to_mono,
            )
            if result.success:
                ok += 1
                self.after(0, lambda l=lbl: l.configure(
                    text="✓", text_color="#4caf50"))
            else:
                err_msg = result.error or "Errore sconosciuto"
                errors.append(f"{path.name}: {err_msg}")
                print(f"[ERRORE] {path.name}\n{err_msg}\n", file=sys.stderr)
                self.after(0, lambda l=lbl: l.configure(
                    text="✗", text_color="#f44336"))
            self.after(0, lambda p=(i + 1) / total: self._progress.set(p))
            self.after(0, self._status.busy,
                       f"In corso ({i+1}/{total})…")

        if ok == total:
            self.after(0, self._status.ok,
                       f"{ok}/{total} puliti e salvati in MP3")
        else:
            first_err = errors[0] if errors else ""
            self.after(0, self._status.err,
                       f"{ok}/{total} completati · {total-ok} errori — {first_err}")
        self.after(0, lambda: self._btn_run.configure(state="normal"))
