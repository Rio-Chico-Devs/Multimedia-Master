"""
Protect Tab — encrypt and decrypt PDFs.
  • Encrypt: user password, owner password, print/copy permissions (AES-256)
  • Decrypt: remove password with known password
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from .file_widgets import SingleFilePicker
from .widgets      import SectionLabel, Separator, StatusBar
from core.pdf_engine import PdfEngine


class ProtectTab(ctk.CTkFrame):
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
        self._picker = SingleFilePicker(self, label="File PDF",
                                        on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Panels side by side
        panels = ctk.CTkFrame(self, fg_color="transparent")
        panels.grid(row=1, column=0, sticky="nsew")
        panels.grid_columnconfigure((0, 1), weight=1)
        panels.grid_rowconfigure(0, weight=1)

        # ── Encrypt panel ─────────────────────────────────────────────────
        enc = ctk.CTkFrame(panels, corner_radius=10,
                           fg_color=("#1a1a1a", "#1a1a1a"))
        enc.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        SectionLabel(enc, "🔒 Proteggi con password").pack(
            fill="x", padx=12, pady=(12, 4))
        Separator(enc).pack()

        SectionLabel(enc, "Password utente").pack(
            fill="x", padx=12, pady=(8, 2))
        self._user_pw = ctk.CTkEntry(enc, placeholder_text="Password per aprire il PDF",
                                      show="•")
        self._user_pw.pack(fill="x", padx=12, pady=(0, 4))

        SectionLabel(enc, "Password proprietario").pack(
            fill="x", padx=12, pady=(4, 2))
        self._owner_pw = ctk.CTkEntry(enc,
                                       placeholder_text="(opzionale, come utente se vuota)",
                                       show="•")
        self._owner_pw.pack(fill="x", padx=12, pady=(0, 4))

        # Show/hide toggle
        self._show_pw = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(enc, text="Mostra password",
                        variable=self._show_pw,
                        command=self._toggle_show).pack(
            anchor="w", padx=14, pady=(0, 6))

        Separator(enc).pack()
        SectionLabel(enc, "Permessi").pack(fill="x", padx=12, pady=(8, 2))
        self._allow_print = ctk.BooleanVar(value=True)
        self._allow_copy  = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(enc, text="Consenti stampa",
                        variable=self._allow_print).pack(
            anchor="w", padx=14, pady=2)
        ctk.CTkCheckBox(enc, text="Consenti copia testo",
                        variable=self._allow_copy).pack(
            anchor="w", padx=14, pady=2)

        Separator(enc).pack(pady=(6, 0))

        # Output name
        SectionLabel(enc, "Nome file output").pack(
            fill="x", padx=12, pady=(8, 2))
        self._enc_name = ctk.CTkEntry(enc, placeholder_text="protetto.pdf")
        self._enc_name.insert(0, "protetto.pdf")
        self._enc_name.pack(fill="x", padx=12, pady=(0, 4))

        self._btn_enc = ctk.CTkButton(
            enc, text="Proteggi PDF", height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._run_encrypt)
        self._btn_enc.pack(fill="x", padx=12, pady=(8, 12))

        # ── Decrypt panel ─────────────────────────────────────────────────
        dec = ctk.CTkFrame(panels, corner_radius=10,
                           fg_color=("#1a1a1a", "#1a1a1a"))
        dec.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        SectionLabel(dec, "🔓 Rimuovi protezione").pack(
            fill="x", padx=12, pady=(12, 4))
        Separator(dec).pack()

        SectionLabel(dec, "Password attuale").pack(
            fill="x", padx=12, pady=(8, 2))
        self._unlock_pw = ctk.CTkEntry(dec,
                                        placeholder_text="Password del PDF",
                                        show="•")
        self._unlock_pw.pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkLabel(dec,
                     text="La password viene usata solo\nlocalmente, non viene trasmessa.",
                     text_color="gray",
                     font=ctk.CTkFont(size=10),
                     justify="left").pack(fill="x", padx=12, pady=(0, 8))

        Separator(dec).pack()

        # Output name
        SectionLabel(dec, "Nome file output").pack(
            fill="x", padx=12, pady=(8, 2))
        self._dec_name = ctk.CTkEntry(dec, placeholder_text="sbloccato.pdf")
        self._dec_name.insert(0, "sbloccato.pdf")
        self._dec_name.pack(fill="x", padx=12, pady=(0, 4))

        self._btn_dec = ctk.CTkButton(
            dec, text="Rimuovi password", height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._run_decrypt)
        self._btn_dec.pack(fill="x", padx=12, pady=(8, 12))

        # Output directory (shared, at bottom)
        Separator(self).grid(row=2, column=0, sticky="ew", padx=4, pady=(4, 0))
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=3, column=0, sticky="ew", padx=4, pady=4)
        bot.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bot, text="Destinazione:", width=90,
                     font=ctk.CTkFont(size=11), anchor="w").grid(row=0, column=0)
        self._dir_lbl = ctk.CTkLabel(bot, text="(stessa cartella del file)",
                                      text_color="gray", anchor="w",
                                      font=ctk.CTkFont(size=10))
        self._dir_lbl.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkButton(bot, text="Sfoglia", width=72, height=26,
                      command=self._browse_dir).grid(row=0, column=2,
                                                     padx=(6, 0))

        # Status bar
        self._status = StatusBar(self)
        self._status.grid(row=4, column=0, sticky="ew", padx=4, pady=(4, 0))

        self._set_buttons_state("disabled")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _on_file_change(self, path):
        self._set_buttons_state("normal" if path else "disabled")

    def _set_buttons_state(self, state: str):
        self._btn_enc.configure(state=state)
        self._btn_dec.configure(state=state)

    def _toggle_show(self):
        show = "" if self._show_pw.get() else "•"
        self._user_pw.configure(show=show)
        self._owner_pw.configure(show=show)

    def _browse_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Cartella di destinazione")
        if d:
            self._out_dir = Path(d)
            self._dir_lbl.configure(text=str(self._out_dir), text_color="white")

    def _resolve_output(self, name: str) -> Path:
        pdf = self._picker.get_path()
        out_dir = self._out_dir or (pdf.parent if pdf else Path.home())
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        return out_dir / name

    # ── Run: encrypt ──────────────────────────────────────────────────────

    def _run_encrypt(self):
        pdf = self._picker.get_path()
        if not pdf:
            return
        user_pw  = self._user_pw.get()
        owner_pw = self._owner_pw.get() or user_pw
        if not user_pw:
            self._status.err("Inserisci almeno la password utente.")
            return

        output = self._resolve_output(self._enc_name.get().strip() or "protetto.pdf")
        self._status.busy("Protezione in corso…")
        self.update_idletasks()

        threading.Thread(
            target=self._worker_encrypt,
            args=(pdf, user_pw, owner_pw, output),
            daemon=True,
        ).start()

    def _worker_encrypt(self, pdf, user_pw, owner_pw, output):
        try:
            result = self._engine.protect(
                pdf=pdf,
                user_pw=user_pw,
                owner_pw=owner_pw,
                output=output,
                allow_print=self._allow_print.get(),
                allow_copy=self._allow_copy.get(),
            )
            if result.success:
                self.after(0, self._status.ok, f"Salvato: {output.name}")
            else:
                self.after(0, self._status.err, result.error)
        except Exception as exc:
            self.after(0, self._status.err, str(exc))

    # ── Run: decrypt ──────────────────────────────────────────────────────

    def _run_decrypt(self):
        pdf = self._picker.get_path()
        if not pdf:
            return
        password = self._unlock_pw.get()
        output   = self._resolve_output(
            self._dec_name.get().strip() or "sbloccato.pdf")
        self._status.busy("Rimozione protezione…")
        self.update_idletasks()

        threading.Thread(
            target=self._worker_decrypt,
            args=(pdf, password, output),
            daemon=True,
        ).start()

    def _worker_decrypt(self, pdf, password, output):
        try:
            result = self._engine.unlock(pdf, password, output)
            if result.success:
                self.after(0, self._status.ok, f"Salvato: {output.name}")
            else:
                self.after(0, self._status.err, result.error)
        except Exception as exc:
            self.after(0, self._status.err, str(exc))
