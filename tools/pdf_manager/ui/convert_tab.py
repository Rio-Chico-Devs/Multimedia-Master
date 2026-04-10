"""
Convert Tab — images → PDF
  • Select multiple images (browse / folder / drag-and-drop)
  • Optional: one PDF per image vs. single merged PDF
  • Optional: OCR (pytesseract, needs Tesseract installed)
  • Output directory chooser
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from .file_widgets import ImageFileList
from .widgets      import SectionLabel, Separator, StatusBar
from core.pdf_engine import PdfEngine


class ConvertTab(ctk.CTkFrame):
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

        # Left — file list
        self._file_list = ImageFileList(self)
        self._file_list.grid(row=0, column=0, sticky="nsew",
                             padx=(0, 8), pady=0)

        # Right — options
        right = ctk.CTkScrollableFrame(self, corner_radius=10,
                                        fg_color=("#1a1a1a", "#1a1a1a"))
        right.grid(row=0, column=1, sticky="nsew")

        SectionLabel(right, "Opzioni di conversione").pack(
            fill="x", padx=12, pady=(12, 4))
        Separator(right).pack()

        # Output mode
        SectionLabel(right, "Modalità output").pack(
            fill="x", padx=12, pady=(8, 2))
        self._mode = ctk.StringVar(value="single")
        ctk.CTkRadioButton(right, text="Un unico PDF",
                           variable=self._mode, value="single").pack(
            anchor="w", padx=16, pady=2)
        ctk.CTkRadioButton(right, text="Un PDF per immagine",
                           variable=self._mode, value="per_file").pack(
            anchor="w", padx=16, pady=2)

        Separator(right).pack(pady=(8, 0))

        # OCR
        SectionLabel(right, "OCR (testo ricercabile)").pack(
            fill="x", padx=12, pady=(8, 2))
        self._ocr_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(right,
                        text="Attiva OCR  (richiede Tesseract)",
                        variable=self._ocr_var).pack(
            anchor="w", padx=16, pady=2)

        # OCR language
        lang_row = ctk.CTkFrame(right, fg_color="transparent")
        lang_row.pack(fill="x", padx=16, pady=(4, 0))
        ctk.CTkLabel(lang_row, text="Lingua OCR:",
                     font=ctk.CTkFont(size=11), width=80,
                     anchor="w").pack(side="left")
        self._lang_entry = ctk.CTkEntry(lang_row, width=120,
                                         placeholder_text="ita+eng")
        self._lang_entry.insert(0, "ita+eng")
        self._lang_entry.pack(side="left", padx=(6, 0))

        Separator(right).pack(pady=(8, 0))

        # Output name (only for single mode)
        SectionLabel(right, "Nome file output").pack(
            fill="x", padx=12, pady=(8, 2))
        self._name_entry = ctk.CTkEntry(right, placeholder_text="output.pdf")
        self._name_entry.pack(fill="x", padx=12, pady=(0, 4))
        self._name_entry.insert(0, "output.pdf")

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

        # Actions
        ctk.CTkButton(right, text="Converti",
                      height=38,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._run).pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkButton(right, text="Pulisci lista",
                      height=30, fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self._file_list.clear).pack(
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
        images = self._file_list.get_paths()
        if not images:
            self._status.err("Nessuna immagine selezionata.")
            return

        # Resolve output directory
        out_dir = self._out_dir or images[0].parent

        # Output path (used only in "single" mode)
        name = self._name_entry.get().strip() or "output.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        output = out_dir / name

        ocr        = self._ocr_var.get()
        one_per    = self._mode.get() == "per_file"
        lang       = self._lang_entry.get().strip() or "ita+eng"

        self._status.busy("Conversione in corso…")
        self.update_idletasks()

        threading.Thread(
            target=self._worker,
            args=(images, output, ocr, one_per, lang),
            daemon=True,
        ).start()

    def _worker(self, images, output, ocr, one_per, lang):
        try:
            results = self._engine.images_to_pdf(
                images=images,
                output=output,
                ocr=ocr,
                one_per_file=one_per,
                lang=lang,
            )
            ok    = [r for r in results if r.success]
            fail  = [r for r in results if not r.success]
            msg   = f"{len(ok)} file creati"
            if fail:
                msg += f"  |  {len(fail)} errori: {fail[0].error}"
            self.after(0, self._status.ok if not fail else self._status.err, msg)
        except Exception as exc:
            self.after(0, self._status.err, str(exc))
