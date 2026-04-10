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

import customtkinter as ctk

from .convert_tab import ConvertTab
from .merge_tab   import MergeTab
from .split_tab   import SplitTab
from .protect_tab import ProtectTab
from .analyze_tab import AnalyzeTab


class PdfWindow(ctk.CTk):
    """Root window for the PDF Manager tool."""

    def __init__(self):
        super().__init__()
        self.title("Gestione PDF — Multimedia Master")
        self.geometry("960x680")
        self.minsize(800, 560)
        self._build()

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

        # Instantiate each tab inside its CTkTabview frame
        ConvertTab(tabs.tab("Converti")).pack(fill="both", expand=True)
        MergeTab  (tabs.tab("Unisci"))  .pack(fill="both", expand=True)
        SplitTab  (tabs.tab("Dividi"))  .pack(fill="both", expand=True)
        ProtectTab(tabs.tab("Proteggi")).pack(fill="both", expand=True)
        AnalyzeTab(tabs.tab("Analizza")).pack(fill="both", expand=True)
