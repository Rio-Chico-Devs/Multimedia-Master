"""
Split Tab — divide a PDF into parts.
  • By page ranges  ("1-3, 5, 7-10")
  • Every N pages
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from .file_widgets import SingleFilePicker
from .widgets      import SectionLabel, Separator, StatusBar
from core.pdf_engine import PdfEngine


class SplitTab(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine   = PdfEngine()
        self._out_dir: Path | None = None
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # File picker
        self._picker = SingleFilePicker(self, label="File PDF da dividere",
                                        on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Main area
        main = ctk.CTkFrame(self, corner_radius=10,
                             fg_color=("#1a1a1a", "#1a1a1a"))
        main.grid(row=1, column=0, sticky="nsew")
        main.grid_columnconfigure((0, 1), weight=1)

        # ── Ranges mode ────────────────────────────────────────────────────
        left = ctk.CTkFrame(main, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)

        SectionLabel(left, "Dividi per intervalli di pagine").pack(
            fill="x", pady=(0, 4))
        ctk.CTkLabel(left,
                     text='Es.  "1-3, 5, 7-10"  (pagine 1-indexed)',
                     text_color="gray",
                     font=ctk.CTkFont(size=10),
                     anchor="w").pack(fill="x", pady=(0, 6))
        self._ranges_entry = ctk.CTkEntry(left,
                                           placeholder_text="1-3, 5, 7-10")
        self._ranges_entry.pack(fill="x", pady=(0, 8))
        self._btn_ranges = ctk.CTkButton(left, text="Dividi per intervalli",
                                          height=36,
                                          command=self._run_ranges)
        self._btn_ranges.pack(fill="x")

        # Separator between two modes
        ctk.CTkFrame(main, width=1, fg_color="#333").grid(
            row=0, column=0, rowspan=2, sticky="nse", padx=(0, 0))

        # ── Every-N mode ────────────────────────────────────────────────────
        right = ctk.CTkFrame(main, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)

        SectionLabel(right, "Dividi ogni N pagine").pack(
            fill="x", pady=(0, 4))
        ctk.CTkLabel(right,
                     text="Ogni parte conterrà al massimo N pagine.",
                     text_color="gray",
                     font=ctk.CTkFont(size=10),
                     anchor="w",
                     wraplength=200).pack(fill="x", pady=(0, 6))

        n_row = ctk.CTkFrame(right, fg_color="transparent")
        n_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(n_row, text="N =", font=ctk.CTkFont(size=12),
                     width=36).pack(side="left")
        self._n_entry = ctk.CTkEntry(n_row, width=80, placeholder_text="10")
        self._n_entry.insert(0, "10")
        self._n_entry.pack(side="left", padx=(4, 0))

        self._btn_n = ctk.CTkButton(right, text="Dividi ogni N pagine",
                                     height=36,
                                     command=self._run_every_n)
        self._btn_n.pack(fill="x")

        # Output directory (shared)
        Separator(main).grid(row=1, column=0, columnspan=2, sticky="ew",
                             padx=12, pady=4)
        out_frame = ctk.CTkFrame(main, fg_color="transparent")
        out_frame.grid(row=2, column=0, columnspan=2, sticky="ew",
                       padx=12, pady=(0, 12))
        out_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(out_frame, text="Destinazione:",
                     font=ctk.CTkFont(size=11), width=90,
                     anchor="w").grid(row=0, column=0)
        self._dir_lbl = ctk.CTkLabel(out_frame,
                                      text="(stessa cartella del file)",
                                      anchor="w", text_color="gray",
                                      font=ctk.CTkFont(size=10))
        self._dir_lbl.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkButton(out_frame, text="Sfoglia", width=72, height=26,
                      command=self._browse_dir).grid(row=0, column=2,
                                                     padx=(6, 0))

        # Status bar
        self._status = StatusBar(self)
        self._status.grid(row=2, column=0, sticky="ew", padx=4, pady=(4, 0))

        self._set_buttons_state("disabled")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _on_file_change(self, path):
        self._set_buttons_state("normal" if path else "disabled")

    def _set_buttons_state(self, state: str):
        self._btn_ranges.configure(state=state)
        self._btn_n.configure(state=state)

    def _browse_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Cartella di destinazione")
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(text=str(self._out_dir), text_color="white")

    def _resolve_out_dir(self) -> Path:
        pdf = self._picker.get_path()
        return self._out_dir or (pdf.parent if pdf else Path.home())

    # ── Run: ranges ───────────────────────────────────────────────────────

    def _run_ranges(self):
        pdf = self._picker.get_path()
        if not pdf:
            return
        ranges = self._ranges_entry.get().strip()
        if not ranges:
            self._status.err("Inserisci gli intervalli di pagine.")
            return

        out_dir = self._resolve_out_dir()
        self._status.busy("Divisione in corso…")
        self.update_idletasks()

        threading.Thread(
            target=self._worker_ranges,
            args=(pdf, ranges, out_dir),
            daemon=True,
        ).start()

    def _worker_ranges(self, pdf, ranges, out_dir):
        try:
            results = self._engine.split_by_ranges(pdf, ranges, out_dir)
            ok   = [r for r in results if r.success]
            fail = [r for r in results if not r.success]
            msg  = f"{len(ok)} file creati in {out_dir.name}"
            if fail:
                msg += f"  |  {len(fail)} errori: {fail[0].error}"
            self.after(0, self._status.ok if not fail else self._status.err, msg)
        except Exception as exc:
            self.after(0, self._status.err, str(exc))

    # ── Run: every N ──────────────────────────────────────────────────────

    def _run_every_n(self):
        pdf = self._picker.get_path()
        if not pdf:
            return
        try:
            n = int(self._n_entry.get().strip())
            if n < 1:
                raise ValueError
        except ValueError:
            self._status.err("N deve essere un numero intero positivo.")
            return

        out_dir = self._resolve_out_dir()
        self._status.busy("Divisione in corso…")
        self.update_idletasks()

        threading.Thread(
            target=self._worker_n,
            args=(pdf, n, out_dir),
            daemon=True,
        ).start()

    def _worker_n(self, pdf, n, out_dir):
        try:
            results = self._engine.split_every_n(pdf, n, out_dir)
            ok   = [r for r in results if r.success]
            fail = [r for r in results if not r.success]
            msg  = f"{len(ok)} parti create in {out_dir.name}"
            if fail:
                msg += f"  |  {len(fail)} errori: {fail[0].error}"
            self.after(0, self._status.ok if not fail else self._status.err, msg)
        except Exception as exc:
            self.after(0, self._status.err, str(exc))
