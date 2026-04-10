"""
Merge Tab — join multiple PDFs into one.
  • Reorderable list (↑ ↓ buttons + drag-and-drop to add)
  • Choose output directory and file name
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from .file_widgets import PdfMergeList
from .widgets      import SectionLabel, Separator, StatusBar
from ..core.pdf_engine import PdfEngine


class MergeTab(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine   = PdfEngine()
        self._out_dir: Path | None = None
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # Left — PDF list (reorderable)
        self._pdf_list = PdfMergeList(self)
        self._pdf_list.grid(row=0, column=0, sticky="nsew",
                            padx=(0, 8), pady=0)

        # Right — options
        right = ctk.CTkScrollableFrame(self, corner_radius=10,
                                        fg_color=("#1a1a1a", "#1a1a1a"))
        right.grid(row=0, column=1, sticky="nsew")

        SectionLabel(right, "Opzioni di unione").pack(
            fill="x", padx=12, pady=(12, 4))
        Separator(right).pack()

        # Output name
        SectionLabel(right, "Nome file output").pack(
            fill="x", padx=12, pady=(8, 2))
        self._name_entry = ctk.CTkEntry(right, placeholder_text="unito.pdf")
        self._name_entry.insert(0, "unito.pdf")
        self._name_entry.pack(fill="x", padx=12, pady=(0, 4))

        # Output directory
        SectionLabel(right, "Cartella di destinazione").pack(
            fill="x", padx=12, pady=(8, 2))
        dir_row = ctk.CTkFrame(right, fg_color="transparent")
        dir_row.pack(fill="x", padx=12, pady=(0, 4))
        dir_row.grid_columnconfigure(0, weight=1)
        self._dir_lbl = ctk.CTkLabel(dir_row, text="(stessa cartella del primo file)",
                                      anchor="w", text_color="gray",
                                      font=ctk.CTkFont(size=10))
        self._dir_lbl.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(dir_row, text="Sfoglia", width=72, height=26,
                      command=self._browse_dir).grid(row=0, column=1, padx=(6, 0))

        Separator(right).pack(pady=(8, 0))

        # Hint
        ctk.CTkLabel(right,
                     text="Ordina i file nella lista\ncon i tasti ↑ ↓ prima di unire.",
                     text_color="gray",
                     font=ctk.CTkFont(size=11),
                     justify="left").pack(fill="x", padx=12, pady=(4, 0))

        Separator(right).pack(pady=(8, 0))

        # Actions
        ctk.CTkButton(right, text="Unisci PDF",
                      height=38,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._run).pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkButton(right, text="Pulisci lista",
                      height=30, fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self._pdf_list.clear).pack(
            fill="x", padx=12, pady=(0, 8))

        # Status bar
        self._status = StatusBar(self)
        self._status.grid(row=1, column=0, columnspan=2,
                          sticky="ew", padx=4, pady=(4, 0))

    # ── Directory picker ──────────────────────────────────────────────────

    def _browse_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Cartella di destinazione")
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(text=str(self._out_dir), text_color="white")

    # ── Run ───────────────────────────────────────────────────────────────

    def _run(self):
        pdfs = self._pdf_list.get_paths()
        if len(pdfs) < 2:
            self._status.err("Seleziona almeno 2 PDF da unire.")
            return

        out_dir = self._out_dir or pdfs[0].parent
        name    = self._name_entry.get().strip() or "unito.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        output = out_dir / name

        self._status.busy("Unione in corso…")
        self.update_idletasks()

        threading.Thread(
            target=self._worker,
            args=(pdfs, output),
            daemon=True,
        ).start()

    def _worker(self, pdfs, output):
        try:
            result = self._engine.merge(pdfs, output)
            if result.success:
                size = f"{result.file_size / 1024:.0f} KB"
                self.after(0, self._status.ok,
                           f"Salvato: {output.name}  ({size})")
            else:
                self.after(0, self._status.err, result.error)
        except Exception as exc:
            self.after(0, self._status.err, str(exc))
