"""
Stems Tab — separate a music track into individual stems using Facebook's
demucs model (external process, no PyTorch import in main process).

Stems produced: vocals · drums · bass · other
Models: htdemucs (default, best quality), mdx_extra (faster)

If demucs is not installed, shows clear installation instructions.
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


_STEM_ICONS = {
    "vocals": "🎤",
    "drums":  "🥁",
    "bass":   "🎸",
    "other":  "🎹",
}


class StemsTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine = engine
        self._deps   = deps
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        if not self._deps.demucs:
            self._build_install_guide()
            return

        # File picker
        self._picker = MediaFilePicker(
            self, label="File audio",
            exts=AUDIO_EXTS,
            on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew",
                          padx=12, pady=(12, 0))

        # Options + stem preview
        body = ctk.CTkFrame(self, fg_color=("#111", "#111"), corner_radius=10)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 0))
        body.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Left: options
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        SectionLabel(left, "🎵  Separazione tracce").pack(fill="x", pady=(0, 8))

        SectionLabel(left, "Modello").pack(fill="x", pady=(0, 2))
        self._model_var = ctk.StringVar(value="htdemucs")
        ctk.CTkRadioButton(
            left, text="htdemucs  (migliore qualità)",
            variable=self._model_var, value="htdemucs",
        ).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(
            left, text="mdx_extra  (bilanciato)",
            variable=self._model_var, value="mdx_extra",
        ).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(
            left, text="htdemucs_ft  (fine-tuned)",
            variable=self._model_var, value="htdemucs_ft",
        ).pack(anchor="w", pady=2)

        Separator(left).pack(fill="x", pady=10)

        SectionLabel(left, "Cartella output").pack(fill="x", pady=(0, 2))
        self._dir_lbl = ctk.CTkLabel(
            left, text="(stessa cartella del file)",
            text_color="gray", font=ctk.CTkFont(size=10), anchor="w")
        self._dir_lbl.pack(fill="x")
        ctk.CTkButton(left, text="Scegli", height=28,
                      command=self._choose_dir).pack(fill="x", pady=(4, 0))
        self._out_dir: Path | None = None

        ctk.CTkLabel(
            left,
            text="\n⚠  La separazione richiede\npotenza di calcolo.\n"
                 "Tempo stimato: 2–10× la\ndurata del brano.",
            text_color="#aaa", font=ctk.CTkFont(size=10),
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

        # Right: stem cards
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        right.grid_columnconfigure((0, 1), weight=1)

        SectionLabel(right, "Tracce che verranno generate").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._stem_labels: dict[str, ctk.CTkLabel] = {}
        for i, (stem, icon) in enumerate(_STEM_ICONS.items()):
            card = ctk.CTkFrame(right, fg_color="#1a1a1a", corner_radius=8)
            card.grid(row=(i // 2) + 1, column=i % 2,
                      sticky="nsew", padx=4, pady=4)
            ctk.CTkLabel(card, text=icon,
                          font=ctk.CTkFont(size=28)).pack(pady=(10, 2))
            ctk.CTkLabel(card, text=stem.capitalize(),
                          font=ctk.CTkFont(size=12, weight="bold")).pack()
            status_lbl = ctk.CTkLabel(
                card, text="in attesa…",
                text_color="#555", font=ctk.CTkFont(size=10))
            status_lbl.pack(pady=(2, 10))
            self._stem_labels[stem] = status_lbl

        # Log output
        self._log = ctk.CTkTextbox(
            body, height=80, fg_color="#0a0a0a",
            font=ctk.CTkFont(family="Courier", size=10))
        self._log.grid(row=1, column=0, columnspan=2, sticky="ew",
                       padx=8, pady=(0, 8))
        self._log.configure(state="disabled")

        # Bottom bar
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)
        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")
        self._btn_run = ctk.CTkButton(
            bot, text="🎵  Separa tracce",
            width=160, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._run)
        self._btn_run.grid(row=0, column=1, padx=(8, 0))

    def _build_install_guide(self) -> None:
        frame = ctk.CTkFrame(self, fg_color=("#111", "#111"), corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(
            frame, text="🎵  Separazione tracce (Stems)",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(24, 4))
        ctk.CTkLabel(
            frame,
            text="Questa funzione usa demucs di Facebook Research per separare\n"
                 "automaticamente voce, batteria, basso e strumenti.",
            font=ctk.CTkFont(size=12), text_color="#aaa",
        ).pack(pady=(0, 16))

        ctk.CTkLabel(
            frame, text="⚠  demucs non è installato",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f44336",
        ).pack()

        ctk.CTkLabel(
            frame,
            text="Installa PyTorch poi demucs (circa 2 GB totali):",
            font=ctk.CTkFont(size=11), text_color="#aaa",
        ).pack(pady=(12, 4))

        for cmd in (
            "pip install torch torchaudio --index-url "
            "https://download.pytorch.org/whl/cpu",
            "pip install demucs",
        ):
            ctk.CTkLabel(
                frame, text=cmd,
                font=ctk.CTkFont(family="Courier", size=11),
                fg_color="#1a1a1a", corner_radius=4,
                text_color="#4fa8e0",
            ).pack(fill="x", padx=40, pady=3)

        ctk.CTkLabel(
            frame, text="Poi riavvia Multimedia Master.",
            font=ctk.CTkFont(size=11), text_color="#aaa",
        ).pack(pady=12)

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_file_change(self, path: Path | None) -> None:
        if hasattr(self, "_btn_run"):
            self._btn_run.configure(
                state="normal" if path else "disabled")
        if path:
            for lbl in self._stem_labels.values():
                lbl.configure(text="in attesa…", text_color="#555")

    def _choose_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(
                text=f"…/{Path(d).name}", text_color="white")

    def _log_append(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        src = self._picker.get_path()
        if not src:
            return

        out_dir = self._out_dir or src.parent
        model   = self._model_var.get()

        for lbl in self._stem_labels.values():
            lbl.configure(text="⏳ elaborazione…", text_color="#aaa")

        self._btn_run.configure(state="disabled")
        self._status.busy("Separazione in corso (può richiedere minuti)…")
        self._log_append(f"▶ {src.name}  —  modello: {model}")
        threading.Thread(
            target=self._worker, args=(src, out_dir, model), daemon=True
        ).start()

    def _worker(self, src: Path, out_dir: Path, model: str) -> None:
        def _prog(line: str) -> None:
            self.after(0, self._log_append, line)
            if "%" in line:
                self.after(0, self._status.busy,
                           f"Separazione… {line}")

        results = self._engine.separate_stems(src, out_dir, model, _prog)

        ok = [r for r in results if r.success]
        if ok:
            # Update stem cards
            for r in ok:
                stem = r.output.stem.lower()
                lbl  = self._stem_labels.get(stem)
                if lbl:
                    self.after(0, lambda l=lbl, n=r.output.name: l.configure(
                        text=f"✓ {n}", text_color="#4caf50"))
            self.after(0, self._status.ok,
                       f"{len(ok)} tracce salvate in: {out_dir}")
        else:
            err = results[0].error if results else "Errore sconosciuto"
            for lbl in self._stem_labels.values():
                self.after(0, lambda l=lbl: l.configure(
                    text="✗ errore", text_color="#f44336"))
            self.after(0, self._status.err, err)

        self.after(0, lambda: self._btn_run.configure(state="normal"))
