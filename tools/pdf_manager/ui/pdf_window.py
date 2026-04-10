"""
PDF Manager main window.
Five tabs inside a CTkTabview:
  1. Converti    — images → PDF (with optional OCR)
  2. Unisci      — merge multiple PDFs
  3. Dividi      — split by ranges or every N pages
  4. Proteggi    — encrypt / decrypt
  5. Analizza    — text, metadata, form fields, summary
"""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from .convert_tab import ConvertTab
from .merge_tab   import MergeTab
from .split_tab   import SplitTab
from .protect_tab import ProtectTab
from .analyze_tab import AnalyzeTab

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif",
              ".tiff", ".tif", ".bmp", ".gif"}


class PdfWindow(ctk.CTk):
    """Root window for the PDF Manager tool."""

    def __init__(self):
        super().__init__()
        self.title("Gestione PDF — Multimedia Master")
        self.geometry("960x680")
        self.minsize(800, 560)
        self._init_dnd()
        self._build()

    # ── Drag & drop (window-level, avoids CTkScrollableFrame canvas issue) ──

    def _init_dnd(self) -> None:
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES
            TkinterDnD._require(self)
            self.tk.call("tkdnd::drop_target", "register", self._w, DND_FILES)
            self.bind("<<Drop>>", self._on_window_drop)
        except Exception:
            pass

    def _on_window_drop(self, event) -> None:
        """Route dropped files to the active tab's widget."""
        raw = event.data or ""
        paths = [Path(t.strip("{}")) for t in raw.strip().split()
                 if t.strip("{}")]

        # Detect type of first file and forward accordingly
        pdfs   = [p for p in paths if p.suffix.lower() == ".pdf" and p.is_file()]
        images = [p for p in paths if p.suffix.lower() in IMAGE_EXTS and p.is_file()]

        if pdfs and hasattr(self, "_merge_list"):
            self._merge_list._add_paths(pdfs)
        elif images and hasattr(self, "_img_list"):
            self._img_list._add_paths(images)

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 0))
        ctk.CTkLabel(header, text="📄  Gestione PDF",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkLabel(header, text="100% offline  ·  nessun cloud",
                     text_color="#555",
                     font=ctk.CTkFont(size=11),
                     anchor="e").pack(side="right")

        # Tab view
        tabs = ctk.CTkTabview(self, corner_radius=10)
        tabs.pack(fill="both", expand=True, padx=16, pady=(10, 16))

        for name in ("Converti", "Unisci", "Dividi", "Proteggi", "Analizza"):
            tabs.add(name)

        # Instantiate each tab and keep references to their file lists
        convert = ConvertTab(tabs.tab("Converti"))
        convert.pack(fill="both", expand=True)
        self._img_list = convert._file_list          # ImageFileList

        merge = MergeTab(tabs.tab("Unisci"))
        merge.pack(fill="both", expand=True)
        self._merge_list = merge._pdf_list           # PdfMergeList

        SplitTab  (tabs.tab("Dividi"))  .pack(fill="both", expand=True)
        ProtectTab(tabs.tab("Proteggi")).pack(fill="both", expand=True)
        AnalyzeTab(tabs.tab("Analizza")).pack(fill="both", expand=True)
