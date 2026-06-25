"""
Convert Tab — images → PDF
  • Select multiple images (browse / folder / drag-and-drop)
  • Optional: one PDF per image vs. single merged PDF
  • Optional: OCR (RapidOCR, fully bundled — no separate install)
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
        self._engine       = PdfEngine()
        self._out_dir: Path | None = None
        self._cancel_event = threading.Event()
        self._busy         = False
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
                        text="Attiva OCR  (testo ricercabile sopra la scansione)",
                        variable=self._ocr_var).pack(
            anchor="w", padx=16, pady=2)

        Separator(right).pack(pady=(8, 0))

        # Output name (single mode)
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

        # Actions — Converti + ⏹ cancel on the same row
        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(12, 4))
        btn_row.grid_columnconfigure(0, weight=1)

        self._convert_btn = ctk.CTkButton(
            btn_row, text="Converti", height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._run)
        self._convert_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._cancel_btn = ctk.CTkButton(
            btn_row, text="⏹", width=44, height=38,
            fg_color="#5a1a1a", hover_color="#7a2a2a",
            state="disabled",
            command=self._cancel)
        self._cancel_btn.grid(row=0, column=1, sticky="e")

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

    # ── Cancel ────────────────────────────────────────────────────────────

    def _cancel(self):
        self._cancel_event.set()
        self._status.busy("Annullamento dopo il file corrente…")

    # ── Run ───────────────────────────────────────────────────────────────

    def _run(self):
        if self._busy:
            return
        images = self._file_list.get_paths()
        if not images:
            self._status.err("Nessuna immagine selezionata.")
            return

        out_dir = self._out_dir or images[0].parent
        name    = self._name_entry.get().strip() or "output.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        output  = out_dir / name

        one_per = self._mode.get() == "per_file"
        ocr     = self._ocr_var.get()

        # Overwrite check applies only to single-file mode.
        if not one_per and output.exists():
            from tkinter import messagebox
            if not messagebox.askyesno(
                "Sovrascrivere?",
                f"Il file esiste già:\n{output.name}\n\nSovrascrivere?",
                icon="warning",
            ):
                return

        self._busy = True
        self._cancel_event.clear()
        self._convert_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._status.busy("Conversione in corso…")
        self.update_idletasks()

        threading.Thread(
            target=self._worker,
            args=(images, output, ocr, one_per),
            daemon=True,
        ).start()

    def _worker(self, images, output, ocr, one_per):
        try:
            if one_per:
                # Process each image individually so cancel takes effect between files.
                ok = fail = 0
                total = len(images)
                for i, img in enumerate(images):
                    if self._cancel_event.is_set():
                        self.after(0, self._done,
                                   f"⏹ Annullato  ·  {ok}/{total} creati", "cancel")
                        return
                    self.after(0, self._status.busy, f"({i+1}/{total})  {img.name}")

                    per_file_output = output.parent / f"{img.stem}.pdf"
                    # Safety: never let a per-image output overwrite the
                    # source image itself (possible if an input file is
                    # already named "<stem>.pdf").
                    if per_file_output.resolve() == img.resolve():
                        fail += 1
                        continue
                    try:
                        results = self._engine.images_to_pdf(
                            images=[img],
                            output=per_file_output,
                            ocr=ocr,
                            one_per_file=False,
                        )
                        if results and results[0].success:
                            ok += 1
                        else:
                            fail += 1
                    except Exception:
                        fail += 1
                msg = f"{ok} PDF creati"
                if fail:
                    msg += f"  ·  {fail} errori"
                self.after(0, self._done, msg, "ok" if not fail else "err")
            else:
                # Safety: never let the single merged output overwrite one
                # of the source images.
                out_resolved = output.resolve()
                if any(out_resolved == img.resolve() for img in images):
                    self.after(0, self._done,
                               "Il nome/cartella di destinazione coincide con "
                               "una delle immagini di origine: l'operazione "
                               "è stata annullata per non sovrascriverla.",
                               "err")
                    return
                results = self._engine.images_to_pdf(
                    images=images,
                    output=output,
                    ocr=ocr,
                    one_per_file=False,
                )
                ok   = [r for r in results if r.success]
                fail = [r for r in results if not r.success]
                msg  = f"{len(ok)} file creati"
                if fail:
                    msg += f"  |  {len(fail)} errori: {fail[0].error}"
                self.after(0, self._done, msg, "ok" if not fail else "err")
        except Exception as exc:
            self.after(0, self._done, str(exc), "err")

    def _done(self, msg: str, status: str) -> None:
        self._busy = False
        self._convert_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        if status == "ok":
            self._status.ok(msg)
        elif status == "cancel":
            self._status.info(msg)
        else:
            self._status.err(msg)
