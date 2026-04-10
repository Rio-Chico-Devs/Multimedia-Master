"""
Analyze Tab — extract text, metadata, form fields, and generate a summary.
  • Pick a PDF (with optional password)
  • Click "Analizza"
  • Results appear in scrollable panels:
      - Stats (pages, words, characters, encrypted, form fields)
      - Metadata (author, title, creator, …)
      - Detected form fields
      - Extractive summary
      - Full text (collapsible)
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from .file_widgets  import SingleFilePicker
from .widgets       import SectionLabel, Separator, StatusBar
from core.pdf_engine import PdfEngine, PdfAnalysis


class AnalyzeTab(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine = PdfEngine()
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Top bar: file picker + password ──────────────────────────────
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.grid_columnconfigure(0, weight=1)

        self._picker = SingleFilePicker(top, label="File PDF da analizzare",
                                        on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew", columnspan=3)

        pw_row = ctk.CTkFrame(top, fg_color="transparent")
        pw_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ctk.CTkLabel(pw_row, text="Password (se protetto):",
                     font=ctk.CTkFont(size=11), anchor="w",
                     width=160).pack(side="left")
        self._pw_entry = ctk.CTkEntry(pw_row, width=160,
                                       placeholder_text="lascia vuoto se non protetto",
                                       show="•")
        self._pw_entry.pack(side="left", padx=(6, 0))
        self._btn_analyze = ctk.CTkButton(pw_row, text="Analizza PDF",
                                           width=120, height=32,
                                           font=ctk.CTkFont(size=12, weight="bold"),
                                           command=self._run,
                                           state="disabled")
        self._btn_analyze.pack(side="right")

        # ── Results area ─────────────────────────────────────────────────
        self._results = ctk.CTkScrollableFrame(self, corner_radius=10,
                                                fg_color=("#1a1a1a", "#1a1a1a"))
        self._results.grid(row=1, column=0, sticky="nsew")
        self._results.grid_columnconfigure(0, weight=1)

        self._placeholder = ctk.CTkLabel(
            self._results,
            text='Seleziona un PDF e clicca "Analizza PDF" per iniziare.',
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self._placeholder.pack(pady=40)

        # Status bar
        self._status = StatusBar(self)
        self._status.grid(row=2, column=0, sticky="ew", padx=4, pady=(4, 0))

    # ── Helpers ───────────────────────────────────────────────────────────

    def _on_file_change(self, path):
        self._btn_analyze.configure(
            state="normal" if path else "disabled")

    def _clear_results(self):
        for w in self._results.winfo_children():
            w.destroy()

    # ── Run ───────────────────────────────────────────────────────────────

    def _run(self):
        pdf = self._picker.get_path()
        if not pdf:
            return
        password = self._pw_entry.get()
        self._status.busy("Analisi in corso…")
        self._clear_results()
        ctk.CTkLabel(self._results,
                     text="⏳  Analisi in corso, attendere…",
                     text_color="gray",
                     font=ctk.CTkFont(size=12)).pack(pady=30)
        self.update_idletasks()

        threading.Thread(
            target=self._worker,
            args=(pdf, password),
            daemon=True,
        ).start()

    def _worker(self, pdf: Path, password: str):
        try:
            analysis = self._engine.analyze(pdf, password)
            self.after(0, self._show_results, analysis)
            self.after(0, self._status.ok, "Analisi completata.")
        except Exception as exc:
            self.after(0, self._status.err, str(exc))
            self.after(0, self._clear_results)

    # ── Display results ───────────────────────────────────────────────────

    def _show_results(self, a: PdfAnalysis):
        self._clear_results()
        r = self._results

        # ── Stats ────────────────────────────────────────────────────────
        SectionLabel(r, "Statistiche").pack(fill="x", padx=12, pady=(12, 4))
        Separator(r).pack()
        stats = [
            ("Pagine",           str(a.page_count)),
            ("Parole",           f"{a.word_count:,}"),
            ("Caratteri",        f"{a.char_count:,}"),
            ("Crittografato",    "Sì" if a.encrypted else "No"),
            ("Modulo AcroForm",  "Sì" if a.has_acroform else "No"),
        ]
        for label, value in stats:
            row = ctk.CTkFrame(r, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=1)
            ctk.CTkLabel(row, text=label + ":", width=130,
                         anchor="w",
                         font=ctk.CTkFont(size=11),
                         text_color="gray").pack(side="left")
            ctk.CTkLabel(row, text=value, anchor="w",
                         font=ctk.CTkFont(size=11)).pack(side="left")

        # ── Metadata ─────────────────────────────────────────────────────
        if a.metadata:
            SectionLabel(r, "Metadati").pack(fill="x", padx=12, pady=(12, 4))
            Separator(r).pack()
            for k, v in a.metadata.items():
                row = ctk.CTkFrame(r, fg_color="transparent")
                row.pack(fill="x", padx=16, pady=1)
                ctk.CTkLabel(row, text=k + ":", width=130,
                             anchor="w", text_color="gray",
                             font=ctk.CTkFont(size=11)).pack(side="left")
                # Truncate very long values
                disp = v if len(v) < 80 else v[:77] + "…"
                ctk.CTkLabel(row, text=disp, anchor="w",
                             font=ctk.CTkFont(size=11)).pack(side="left")

        # ── Form fields ──────────────────────────────────────────────────
        all_fields = list(dict.fromkeys(a.form_fields + a.suggested_fields))
        if all_fields:
            SectionLabel(r, "Campi modulo rilevati").pack(
                fill="x", padx=12, pady=(12, 4))
            Separator(r).pack()
            text = ",  ".join(all_fields)
            ctk.CTkLabel(r, text=text, anchor="w", wraplength=520,
                         font=ctk.CTkFont(size=11),
                         padx=16).pack(fill="x", pady=4)

        # ── Summary ──────────────────────────────────────────────────────
        if a.summary:
            SectionLabel(r, "Sintesi estrattiva").pack(
                fill="x", padx=12, pady=(12, 4))
            Separator(r).pack()
            txt_box = ctk.CTkTextbox(r, height=120, corner_radius=6,
                                      font=ctk.CTkFont(size=11),
                                      wrap="word", state="normal")
            txt_box.pack(fill="x", padx=12, pady=(4, 0))
            txt_box.insert("1.0", a.summary)
            txt_box.configure(state="disabled")

        # ── Full text ────────────────────────────────────────────────────
        if a.full_text.strip():
            SectionLabel(r, "Testo completo").pack(
                fill="x", padx=12, pady=(12, 4))
            Separator(r).pack()

            self._full_text_visible = ctk.BooleanVar(value=False)
            self._full_text_content = a.full_text

            toggle_btn = ctk.CTkButton(
                r, text="Mostra testo completo ▼",
                height=28, fg_color="#2a2a2a", hover_color="#3a3a3a",
                font=ctk.CTkFont(size=11),
                command=lambda: self._toggle_full_text(toggle_btn, txt_full))
            toggle_btn.pack(fill="x", padx=12, pady=(4, 0))

            txt_full = ctk.CTkTextbox(r, height=300, corner_radius=6,
                                       font=ctk.CTkFont(family="Courier", size=10),
                                       wrap="word", state="normal")
            txt_full.insert("1.0", a.full_text)
            txt_full.configure(state="disabled")
            # Hidden by default
            self._full_text_box = txt_full

        # Padding at bottom
        ctk.CTkFrame(r, fg_color="transparent", height=20).pack()

    def _toggle_full_text(self, btn, box):
        if self._full_text_visible.get():
            box.pack_forget()
            btn.configure(text="Mostra testo completo ▼")
            self._full_text_visible.set(False)
        else:
            box.pack(fill="x", padx=12, pady=(4, 0))
            btn.configure(text="Nascondi testo completo ▲")
            self._full_text_visible.set(True)
