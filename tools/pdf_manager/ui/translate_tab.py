"""
Translate Tab — translates a PDF in place: same layout, page text replaced.

Uses an offline neural MT engine (argostranslate, see core/translate_engine.py)
so the document never leaves the machine. Two one-time, optional, internet-
using actions exist outside the translation flow itself: downloading a
language-pair package, and a per-document glossary to pin sector-specific
terminology that the small offline model would otherwise translate loosely.
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from common.settings import Settings
from .file_widgets import SingleFilePicker
from .widgets       import SectionLabel, Separator, StatusBar, adaptive_wraplength
from .translate_review_dialog import SectionReviewDialog
from core.pdf_translator_engine import (
    PdfTranslatorEngine, apply_translation, extract_sections, translate_sections,
)
from core import translate_engine as te
from core import mbart_engine as me
from core.glossary_presets import AGRICULTURAL_EN_IT

_GLOSSARY_KEY = "translate_glossary"
_ENGINE_LABELS = {
    "argos": "Argos Translate (predefinito, veloce)",
    "mbart": "mBART-50 (modello più ampio, più lento, sperimentale)",
}


# ── Glossary dialog ──────────────────────────────────────────────────────────

class _GlossaryDialog(ctk.CTkToplevel):
    """Edit the term -> forced-translation overrides used during translation."""

    def __init__(self, parent, settings: Settings):
        super().__init__(parent)
        self._settings = settings
        self.title("Glossario terminologico")
        self.geometry("420x420")
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(
            self, text="Termini con traduzione forzata\n"
                       "(utile per nomi di prodotto, acronimi, gergo di settore)",
            font=ctk.CTkFont(size=11), text_color="#888", justify="center",
        ).pack(pady=(14, 8), padx=16)

        self._rows_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._rows_frame.pack(fill="both", expand=True, padx=16)
        self._rows: list[tuple[ctk.CTkEntry, ctk.CTkEntry, ctk.CTkFrame]] = []

        for term, repl in settings.get(_GLOSSARY_KEY, {}).items():
            self._add_row(term, repl)
        if not self._rows:
            self._add_row()

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkButton(btn_row, text="+ Aggiungi termine", height=28,
                      command=lambda: self._add_row()).pack(side="left")
        ctk.CTkButton(btn_row, text="Carica preset macchine agricole (EN→IT)",
                      height=28, fg_color="#2a3a2a", hover_color="#3a4a3a",
                      command=self._load_preset).pack(side="left", padx=(8, 0))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=14)
        ctk.CTkButton(bottom, text="Annulla", height=32, width=90,
                      fg_color="#333", command=self.destroy).pack(side="right")
        ctk.CTkButton(bottom, text="Salva", height=32, width=90,
                      command=self._save).pack(side="right", padx=(0, 8))

    def _add_row(self, term: str = "", repl: str = "") -> None:
        row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
        row.pack(fill="x", pady=3)
        e_term = ctk.CTkEntry(row, placeholder_text="termine originale")
        e_term.pack(side="left", fill="x", expand=True, padx=(0, 4))
        e_term.insert(0, term)
        e_repl = ctk.CTkEntry(row, placeholder_text="traduzione forzata")
        e_repl.pack(side="left", fill="x", expand=True, padx=(4, 4))
        e_repl.insert(0, repl)
        ctk.CTkButton(row, text="✕", width=28, height=28,
                      fg_color="#3a1f1f", hover_color="#5c2a2a",
                      command=lambda: self._remove_row(row)).pack(side="left")
        self._rows.append((e_term, e_repl, row))

    def _remove_row(self, row) -> None:
        self._rows = [r for r in self._rows if r[2] is not row]
        row.destroy()

    def _load_preset(self) -> None:
        """Add the starter agricultural (EN->IT) terms that aren't already
        present, without touching or duplicating existing rows."""
        existing = {e_term.get().strip().lower() for e_term, _, _ in self._rows}
        for term, repl in AGRICULTURAL_EN_IT.items():
            if term.lower() not in existing:
                self._add_row(term, repl)

    def _save(self) -> None:
        glossary = {}
        for e_term, e_repl, _ in self._rows:
            term = e_term.get().strip()
            repl = e_repl.get().strip()
            if term and repl:
                glossary[term] = repl
        self._settings.set(**{_GLOSSARY_KEY: glossary})
        self.destroy()


# ── Language-pack manager dialog ────────────────────────────────────────────

class _LanguagePackDialog(ctk.CTkToplevel):
    """Download additional offline language packages (requires internet, once)."""

    def __init__(self, parent, on_change):
        super().__init__(parent)
        self._on_change = on_change
        self.title("Lingue installate")
        self.geometry("440x420")
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(self, text="Lingue installate (offline da qui in poi)",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(14, 4))
        self._installed_box = ctk.CTkTextbox(self, height=100)
        self._installed_box.pack(fill="x", padx=16)
        self._refresh_installed()

        Separator(self).pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(self, text="Scarica una nuova coppia di lingue",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(0, 4))
        ctk.CTkLabel(
            self, text="Richiede connessione internet, una sola volta.\n"
                       "Dopo il download la traduzione resta sempre offline.",
            font=ctk.CTkFont(size=10), text_color="#888", justify="center",
        ).pack(pady=(0, 8))

        self._status = StatusBar(self)
        self._status.pack(fill="x", padx=16, pady=(0, 6))

        self._pairs_var = ctk.StringVar(value="")
        self._pairs_menu = ctk.CTkOptionMenu(self, variable=self._pairs_var,
                                              values=["Carica elenco..."])
        self._pairs_menu.pack(fill="x", padx=16)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=10)
        ctk.CTkButton(row, text="Aggiorna elenco", height=30,
                      command=self._fetch_available).pack(side="left", expand=True,
                                                           fill="x", padx=(0, 4))
        ctk.CTkButton(row, text="Scarica e installa", height=30,
                      command=self._install_selected).pack(side="left", expand=True,
                                                            fill="x", padx=(4, 0))

        ctk.CTkButton(self, text="Chiudi", height=30, width=90,
                      command=self._close).pack(pady=(4, 14))

        self._available: list[tuple[str, str, str, str]] = []

    def _refresh_installed(self) -> None:
        pairs = te.installed_pairs()
        self._installed_box.delete("1.0", "end")
        if pairs:
            for f, fn, t, tn in pairs:
                self._installed_box.insert("end", f"{fn} ({f}) → {tn} ({t})\n")
        else:
            self._installed_box.insert("end", "Nessuna lingua installata ancora.")
        self._installed_box.configure(state="disabled")

    def _fetch_available(self) -> None:
        self._status.busy("Recupero elenco lingue disponibili…")
        threading.Thread(target=self._worker_fetch, daemon=True).start()

    def _worker_fetch(self) -> None:
        try:
            pairs = te.list_downloadable_pairs()
            self.after(0, self._fetch_done, pairs, None)
        except Exception as exc:
            self.after(0, self._fetch_done, [], str(exc))

    def _fetch_done(self, pairs, error) -> None:
        if error:
            self._status.err(f"Errore: {error}")
            return
        self._available = pairs
        labels = [f"{fn} ({f}) → {tn} ({t})" for f, fn, t, tn in pairs]
        self._pairs_menu.configure(values=labels or ["Nessuna lingua trovata"])
        if labels:
            self._pairs_var.set(labels[0])
        self._status.ok(f"{len(pairs)} coppie disponibili")

    def _install_selected(self) -> None:
        if not self._available:
            self._status.err("Aggiorna prima l'elenco.")
            return
        sel = self._pairs_var.get()
        labels = [f"{fn} ({f}) → {tn} ({t})" for f, fn, t, tn in self._available]
        if sel not in labels:
            # The dropdown's current value no longer matches any entry in the
            # latest catalog (e.g. it was re-fetched in the meantime) — abort
            # rather than silently falling back to index 0 and downloading a
            # pair the user never selected.
            self._status.err("Selezione non valida: aggiorna l'elenco e riprova.")
            return
        src, _, tgt, _ = self._available[labels.index(sel)]
        self._status.busy(f"Download {src}→{tgt}…")
        threading.Thread(target=self._worker_install, args=(src, tgt), daemon=True).start()

    def _worker_install(self, src: str, tgt: str) -> None:
        try:
            te.install_pair(src, tgt)
            self.after(0, self._install_done, src, tgt, None)
        except Exception as exc:
            self.after(0, self._install_done, src, tgt, str(exc))

    def _install_done(self, src, tgt, error) -> None:
        if error:
            self._status.err(f"Errore: {error}")
            return
        self._status.ok(f"Installato {src}→{tgt}")
        self._refresh_installed()
        self._on_change()

    def _close(self) -> None:
        self._on_change()
        self.destroy()


# ── Main tab ─────────────────────────────────────────────────────────────────

class TranslateTab(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._settings = Settings("pdf_manager")
        self._engine   = PdfTranslatorEngine()
        self._out_dir: Path | None = None
        self._busy     = False
        self._cancel_event = threading.Event()
        self._pairs:      list = []
        self._src_labels: dict = {}
        self._tgt_labels: dict = {}
        self._mbart_codes: dict = {}
        self._mt_engine:  str = "argos"
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        try:
            import argostranslate  # noqa: F401
        except ImportError:
            from common.depmsg import pip_hint
            ctk.CTkLabel(
                self,
                text="🌐  Traduttore PDF\n\n"
                     f"Componente non disponibile — {pip_hint('argostranslate')}",
                font=ctk.CTkFont(size=13), text_color="#f44336", justify="center",
            ).grid(row=0, column=0, padx=40, pady=60, sticky="n")
            return

        self._picker = SingleFilePicker(self, label="PDF da tradurre",
                                        on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        main = ctk.CTkFrame(self, corner_radius=10, fg_color=("#1a1a1a", "#1a1a1a"))
        main.grid(row=1, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)

        SectionLabel(main, "Motore di traduzione").pack(fill="x", padx=12, pady=(12, 4))
        engine_row = ctk.CTkFrame(main, fg_color="transparent")
        engine_row.pack(fill="x", padx=12, pady=(0, 4))
        self._engine_var = ctk.StringVar(value=_ENGINE_LABELS["argos"])
        ctk.CTkOptionMenu(engine_row, variable=self._engine_var,
                           values=list(_ENGINE_LABELS.values()),
                           command=self._on_engine_change, width=320,
                           ).pack(side="left")
        self._engine_note = ctk.CTkLabel(
            main, text="", text_color="#888", font=ctk.CTkFont(size=10),
            justify="left")
        self._engine_note.pack(fill="x", padx=12)
        adaptive_wraplength(self._engine_note)

        SectionLabel(main, "Lingue").pack(fill="x", padx=12, pady=(12, 4))

        lang_row = ctk.CTkFrame(main, fg_color="transparent")
        lang_row.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(lang_row, text="Da:", width=30).pack(side="left")
        self._src_var = ctk.StringVar(value="")
        self._src_menu = ctk.CTkOptionMenu(lang_row, variable=self._src_var,
                                            values=["—"], width=160,
                                            command=self._on_src_change)
        self._src_menu.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(lang_row, text="A:", width=20).pack(side="left")
        self._tgt_var = ctk.StringVar(value="")
        self._tgt_menu = ctk.CTkOptionMenu(lang_row, variable=self._tgt_var,
                                            values=["—"], width=160)
        self._tgt_menu.pack(side="left")

        self._manage_lang_btn = ctk.CTkButton(
            lang_row, text="Gestisci lingue", height=28,
            command=self._open_language_dialog)
        self._manage_lang_btn.pack(side="right")

        self._no_lang_lbl = ctk.CTkLabel(
            main, text="", text_color="#f44336",
            font=ctk.CTkFont(size=11), justify="left")
        self._no_lang_lbl.pack(fill="x", padx=12)
        adaptive_wraplength(self._no_lang_lbl)

        Separator(main).pack(fill="x", padx=12, pady=8)

        opts_row = ctk.CTkFrame(main, fg_color="transparent")
        opts_row.pack(fill="x", padx=12, pady=(0, 4))
        self._ocr_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts_row, text="Includi pagine scansionate (OCR)",
                        variable=self._ocr_var).pack(side="left")
        ctk.CTkButton(opts_row, text="Glossario", height=28,
                      command=self._open_glossary_dialog).pack(side="right")

        review_row = ctk.CTkFrame(main, fg_color="transparent")
        review_row.pack(fill="x", padx=12, pady=(0, 4))
        self._review_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            review_row, text="Revisione manuale (controlla ed edita le sezioni "
                              "prima di generare il PDF)",
            variable=self._review_var).pack(side="left")

        # Output directory
        out_frame = ctk.CTkFrame(main, fg_color="transparent")
        out_frame.pack(fill="x", padx=12, pady=(8, 4))
        out_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(out_frame, text="Destinazione:", font=ctk.CTkFont(size=11),
                     width=90, anchor="w").grid(row=0, column=0)
        self._dir_lbl = ctk.CTkLabel(out_frame, text="(stessa cartella del file)",
                                      anchor="w", text_color="gray",
                                      font=ctk.CTkFont(size=10))
        self._dir_lbl.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkButton(out_frame, text="Sfoglia", width=72, height=26,
                      command=self._browse_dir).grid(row=0, column=2, padx=(6, 0))

        self._progress = ctk.CTkProgressBar(main, height=6, corner_radius=3)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=12, pady=(8, 4))

        run_row = ctk.CTkFrame(main, fg_color="transparent")
        run_row.pack(fill="x", padx=12, pady=(0, 12))
        self._btn_translate = ctk.CTkButton(run_row, text="Traduci", height=36,
                                            command=self._run)
        self._btn_translate.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._btn_cancel = ctk.CTkButton(run_row, text="Annulla", height=36,
                                         width=90, fg_color="#3a1f1f",
                                         hover_color="#5c2a2a",
                                         command=self._cancel, state="disabled")
        self._btn_cancel.pack(side="left")

        self._status = StatusBar(self)
        self._status.grid(row=2, column=0, sticky="ew", padx=4, pady=(4, 0))

        self._refresh_languages()
        self._set_buttons_state("disabled")

    # ── Language list ─────────────────────────────────────────────────────

    def _refresh_languages(self) -> None:
        pairs = te.installed_pairs()
        self._pairs = pairs
        sources = sorted({(f, fn) for f, fn, _, _ in pairs}, key=lambda x: x[1])
        if not sources:
            self._no_lang_lbl.configure(
                text="Nessuna lingua installata. Usa 'Gestisci lingue' per "
                     "scaricare una coppia (richiede connessione, una sola volta).")
            self._src_menu.configure(values=["—"])
            self._tgt_menu.configure(values=["—"])
            self._src_var.set("—")
            self._tgt_var.set("—")
            return
        self._no_lang_lbl.configure(text="")
        self._src_labels = {f"{fn} ({f})": f for f, fn in sources}
        self._src_menu.configure(values=list(self._src_labels.keys()))
        if self._src_var.get() not in self._src_labels:
            self._src_var.set(next(iter(self._src_labels)))
        self._on_src_change(self._src_var.get())

    def _on_src_change(self, _label: str) -> None:
        src_code = self._src_labels.get(self._src_var.get())
        if self._mt_engine == "mbart":
            targets = sorted((c, me.display_name(c))
                              for c in self._mbart_codes if c != src_code)
        else:
            targets = sorted({(t, tn) for f, _, t, tn in self._pairs if f == src_code},
                             key=lambda x: x[1])
        self._tgt_labels = {f"{tn} ({t})": t for t, tn in targets}
        self._tgt_menu.configure(values=list(self._tgt_labels.keys()) or ["—"])
        if targets:
            self._tgt_var.set(next(iter(self._tgt_labels)))

    def _open_language_dialog(self) -> None:
        _LanguagePackDialog(self, on_change=self._refresh_languages)

    def _open_glossary_dialog(self) -> None:
        _GlossaryDialog(self, self._settings)

    # ── Engine selection ───────────────────────────────────────────────────

    def _on_engine_change(self, label: str) -> None:
        self._mt_engine = "mbart" if label == _ENGINE_LABELS["mbart"] else "argos"
        self._manage_lang_btn.configure(
            state="disabled" if self._mt_engine == "mbart" else "normal")
        if self._mt_engine == "mbart":
            self._engine_note.configure(
                text="Il modello (~2.3 GB) viene scaricato una sola volta al "
                     "primo utilizzo; da quel momento la traduzione resta "
                     "sempre offline, anche se Hugging Face non è raggiungibile.")
            self._no_lang_lbl.configure(text="")
            self._status.busy("Carico le lingue di mBART-50…")
            threading.Thread(target=self._worker_load_mbart_langs, daemon=True).start()
        else:
            self._engine_note.configure(text="")
            self._refresh_languages()

    def _worker_load_mbart_langs(self) -> None:
        try:
            codes = me.language_codes()
            self.after(0, self._mbart_langs_loaded, codes, None)
        except Exception as exc:
            self.after(0, self._mbart_langs_loaded, {}, str(exc))

    def _mbart_langs_loaded(self, codes: dict, error: str | None) -> None:
        if error or not codes:
            from common.depmsg import pip_hint
            self._no_lang_lbl.configure(
                text="mBART-50 non disponibile — "
                     f"{pip_hint('transformers torch sentencepiece')}")
            self._src_menu.configure(values=["—"])
            self._tgt_menu.configure(values=["—"])
            self._src_var.set("—")
            self._tgt_var.set("—")
            self._status.err("mBART-50 non disponibile." + (f" {error}" if error else ""))
            return
        self._mbart_codes = codes
        self._src_labels = {f"{me.display_name(c)} ({c})": c for c in codes}
        self._src_menu.configure(values=list(self._src_labels.keys()))
        self._src_var.set(next(iter(self._src_labels)))
        self._on_src_change(self._src_var.get())
        self._status.ok(f"{len(codes)} lingue disponibili con mBART-50")

    # ── File / dir ─────────────────────────────────────────────────────────

    def set_file(self, path: Path) -> None:
        """Set the PDF to translate (used for window-level drag & drop)."""
        if hasattr(self, "_picker"):
            self._picker.set_path(path)

    def _on_file_change(self, path) -> None:
        self._set_buttons_state("normal" if path else "disabled")

    def _set_buttons_state(self, state: str) -> None:
        if not self._busy:
            self._btn_translate.configure(state=state)

    def _browse_dir(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Cartella di destinazione")
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(text=str(self._out_dir), text_color="white")

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if self._busy:
            return
        pdf = self._picker.get_path()
        if not pdf:
            return
        src = self._src_labels.get(self._src_var.get())
        tgt = self._tgt_labels.get(self._tgt_var.get())
        if not src or not tgt:
            self._status.err("Seleziona lingua di partenza e di arrivo.")
            return

        out_dir = self._out_dir or pdf.parent
        out_path = out_dir / f"{pdf.stem}_tradotto_{tgt}.pdf"
        glossary = self._settings.get(_GLOSSARY_KEY, {})

        # Safety: never let the translated output overwrite the source PDF
        # (can happen re-translating an already-translated file whose name
        # already ends in "_tradotto_<tgt>.pdf" back into the same folder).
        if out_path.resolve() == pdf.resolve():
            self._status.err(
                "Il file di destinazione coincide con il file di origine: "
                "l'operazione è stata annullata per non sovrascrivere il "
                "PDF originale.")
            return

        self._busy = True
        self._cancel_event.clear()
        self._btn_translate.configure(state="disabled")
        self._btn_cancel.configure(state="normal")
        self._progress.set(0)

        include_scanned = self._ocr_var.get()
        if self._review_var.get():
            job = dict(pdf=pdf, out_path=out_path, src=src, tgt=tgt,
                       include_scanned=include_scanned, glossary=glossary,
                       engine=self._mt_engine)
            self._status.busy("Estrazione testo in corso…")
            threading.Thread(target=self._worker_extract, args=(job,), daemon=True).start()
        else:
            self._status.busy("Traduzione in corso…")
            threading.Thread(
                target=self._worker,
                args=(pdf, out_path, src, tgt, include_scanned, glossary, self._mt_engine),
                daemon=True,
            ).start()

    def _worker(self, pdf, out_path, src, tgt, include_scanned, glossary, engine) -> None:
        result = self._engine.translate_pdf(
            pdf, out_path, src, tgt,
            include_scanned=include_scanned,
            glossary=glossary,
            engine=engine,
            progress_cb=lambda f: self.after(0, self._progress.set, f),
            cancel_event=self._cancel_event,
        )
        self.after(0, self._done, result)

    # ── Manual-review flow (extract -> review -> translate -> review -> apply) ─

    def _worker_extract(self, job: dict) -> None:
        try:
            extracted = extract_sections(
                job["pdf"], include_scanned=job["include_scanned"],
                cancel_event=self._cancel_event,
                progress_cb=lambda f: self.after(0, self._progress.set, f))
        except Exception as exc:
            self.after(0, self._review_failed, str(exc))
            return
        self.after(0, self._show_pre_review, job, extracted)

    def _review_failed(self, error: str) -> None:
        self._finish_busy()
        self._status.err(error)

    def _show_pre_review(self, job: dict, extracted) -> None:
        job["extracted"] = extracted
        if self._cancel_event.is_set():
            self._finish_busy()
            self._status.ok("Annullato.")
            return
        if not extracted.sections:
            self._finish_busy()
            self._status.err("Nessun testo trovato nel PDF: nessuna pagina "
                              "conteneva testo da tradurre.")
            return
        self._progress.set(0)
        self._status.ok(f"{len(extracted.sections)} sezioni trovate — "
                         f"controllale prima di tradurre.")
        SectionReviewDialog(
            self, extracted.sections, mode="source",
            title="Revisione testo estratto",
            intro="Controlla le sezioni trovate nel PDF. Rimuovi (✕) quelle "
                  "che non vuoi tradurre o che creano problemi, oppure "
                  "correggi il testo prima di procedere.",
            on_done=lambda confirmed: self._pre_review_done(job, confirmed))

    def _pre_review_done(self, job: dict, confirmed: bool) -> None:
        if not confirmed:
            self._finish_busy()
            self._status.ok("Traduzione annullata.")
            return
        self._status.busy("Traduzione in corso…")
        threading.Thread(target=self._worker_translate, args=(job,), daemon=True).start()

    def _worker_translate(self, job: dict) -> None:
        extracted = job["extracted"]
        translated_ok, translate_errors, first_error = translate_sections(
            extracted.sections, job["src"], job["tgt"], job["glossary"],
            engine=job["engine"], cancel_event=self._cancel_event,
            progress_cb=lambda f: self.after(0, self._progress.set, f))
        job["translated_ok"]    = translated_ok
        job["translate_errors"] = translate_errors
        job["first_error"]      = first_error
        self.after(0, self._show_post_review, job)

    def _show_post_review(self, job: dict) -> None:
        extracted = job["extracted"]
        if self._cancel_event.is_set():
            self._finish_busy()
            self._status.ok("Annullato.")
            return
        if job["translated_ok"] == 0:
            self._finish_busy()
            if job["translate_errors"] > 0:
                self._status.err(
                    f"Nessuna riga è stata tradotta: la coppia di lingue "
                    f"{job['src']}→{job['tgt']} non risulta utilizzabile. "
                    f"Apri 'Gestisci lingue' e scarica/reinstalla la coppia. "
                    f"Dettaglio tecnico: {job['first_error']}")
            else:
                self._status.err("Nessuna sezione da tradurre (tutte rimosse?).")
            return
        self._progress.set(0)
        active = [s for s in extracted.sections if not s.get("removed")]
        SectionReviewDialog(
            self, active, mode="translation",
            title="Revisione traduzione",
            intro="Controlla il risultato. Puoi correggere il testo tradotto "
                  "o rimuovere (✕) una sezione per lasciarla come "
                  "nell'originale.",
            on_done=lambda confirmed: self._post_review_done(job, confirmed))

    def _post_review_done(self, job: dict, confirmed: bool) -> None:
        if not confirmed:
            self._finish_busy()
            self._status.ok("Traduzione annullata.")
            return
        self._status.busy("Scrittura del PDF…")
        threading.Thread(target=self._worker_apply, args=(job,), daemon=True).start()

    def _worker_apply(self, job: dict) -> None:
        extracted = job["extracted"]
        result = apply_translation(
            job["pdf"], job["out_path"], extracted.sections, extracted.page_count,
            cancel_event=self._cancel_event,
            progress_cb=lambda f: self.after(0, self._progress.set, f))
        if result.success and extracted.ocr_needed_missing > 0:
            from common.depmsg import pip_hint
            result.warning = (f"{extracted.ocr_needed_missing} pagina/e "
                               f"scansionata/e ignorata/e: installa il motore "
                               f"OCR per tradurle "
                               f"({pip_hint('rapidocr_onnxruntime')}).")
        self.after(0, self._done, result)

    # ── Shared cancel / done ──────────────────────────────────────────────────

    def _cancel(self) -> None:
        self._cancel_event.set()
        self._status.busy("Annullamento…")

    def _finish_busy(self) -> None:
        self._busy = False
        self._btn_cancel.configure(state="disabled")
        state = "normal" if self._picker.get_path() else "disabled"
        self._btn_translate.configure(state=state)

    def _done(self, result) -> None:
        self._finish_busy()
        if result.cancelled:
            self._status.ok(f"Annullato — {result.page_count} pagine tradotte "
                             f"su {result.output.name}")
        elif result.success:
            msg = f"Tradotto: {result.output.name}"
            if result.warning:
                msg += f"  ⚠ {result.warning}"
            self._status.ok(msg)
        else:
            self._status.err(result.error or "Traduzione interrotta.")
