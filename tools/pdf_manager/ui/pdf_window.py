"""
PDF Manager main window.
Seven tabs inside a CTkTabview:
  1. Modifica    — visual editor (snip, drag, insert space)
  2. Converti    — images → PDF (with optional OCR)
  3. Traduci     — in-place translation, same layout
  4. Unisci      — merge multiple PDFs
  5. Dividi      — split by ranges or every N pages
  6. Proteggi    — encrypt / decrypt
  7. Analizza    — text, metadata, form fields, summary
"""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from common.ui.geometry import fit_window
from common.ui.icon import apply_icon
from common.ui.about import add_about_button

from .edit_tab      import EditTab
from .convert_tab   import ConvertTab
from .translate_tab import TranslateTab
from .merge_tab     import MergeTab
from .split_tab     import SplitTab
from .protect_tab   import ProtectTab
from .analyze_tab   import AnalyzeTab

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif",
              ".tiff", ".tif", ".bmp", ".gif"}


class PdfWindow(ctk.CTk):
    """Root window for the PDF Manager tool."""

    def __init__(self):
        super().__init__()
        self.title("Gestione PDF — Multimedia Master")
        apply_icon(self)
        fit_window(self, 960, 680, 760, 520)
        add_about_button(self, "Gestione PDF")
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

        active_tab = None
        if hasattr(self, "_tabs"):
            try:
                active_tab = self._tabs.get()
            except Exception:
                pass

        if pdfs and active_tab == "Traduci" and hasattr(self, "_translate_tab"):
            self._translate_tab.set_file(pdfs[0])
        elif pdfs and hasattr(self, "_merge_list"):
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

        for name in ("Modifica", "Converti", "Traduci", "Unisci",
                     "Dividi", "Proteggi", "Analizza"):
            tabs.add(name)

        # Modifica tab (visual editor) — first so it's prominent
        EditTab(tabs.tab("Modifica")).pack(fill="both", expand=True)

        # Instantiate each tab and keep references to their file lists
        convert = ConvertTab(tabs.tab("Converti"))
        convert.pack(fill="both", expand=True)
        self._img_list = convert._file_list          # ImageFileList

        translate = TranslateTab(tabs.tab("Traduci"))
        translate.pack(fill="both", expand=True)
        self._translate_tab = translate
        self._tabs = tabs

        merge = MergeTab(tabs.tab("Unisci"))
        merge.pack(fill="both", expand=True)
        self._merge_list = merge._pdf_list           # PdfMergeList

        SplitTab  (tabs.tab("Dividi"))  .pack(fill="both", expand=True)
        ProtectTab(tabs.tab("Proteggi")).pack(fill="both", expand=True)
        AnalyzeTab(tabs.tab("Analizza")).pack(fill="both", expand=True)
