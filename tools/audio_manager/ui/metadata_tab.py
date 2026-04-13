"""
Metadata Tab — batch tag editor + file health analyser.

Features:
  • Load multiple audio files
  • Click file → load its tags into the editor
  • Save tags to the selected file  |  Apply current fields to ALL files
  • Strip all metadata from selected file(s)
  • Health & safety analysis: magic bytes, ffmpeg decode, tag content check
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk

from common.ui.widgets import SectionLabel, Separator, StatusBar
from core.audio_engine import AudioEngine
from core.dependencies import DepStatus
from core.formats import AUDIO_EXTS


_TAG_FIELDS = [
    ("title",       "Titolo"),
    ("artist",      "Artista"),
    ("album",       "Album"),
    ("date",        "Anno"),
    ("tracknumber", "Traccia n°"),
    ("genre",       "Genere"),
    ("comment",     "Commento"),
]

_BTN_DARK = {"fg_color": "#2a2a2a", "hover_color": "#3a3a3a"}


class MetadataTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine    = engine
        self._deps      = deps
        self._art_path: Path | None = None
        self._art_photo: ImageTk.PhotoImage | None = None
        self._entries:  dict[str, ctk.CTkEntry] = {}
        self._files:    list[Path] = []          # all loaded files
        self._sel_idx:  int | None = None        # currently selected row index
        self._rows:     list[ctk.CTkFrame] = []  # row frames
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        if not self._deps.mutagen:
            ctk.CTkLabel(
                self,
                text="⚠  Questa funzione richiede mutagen.\n\n"
                     "Installa con:  pip install mutagen\n\n"
                     "Poi riavvia Multimedia Master.",
                font=ctk.CTkFont(size=12),
                text_color="#f44336",
                justify="left",
            ).grid(row=0, column=0, padx=40, pady=40, sticky="nw")
            return

        # ── Top toolbar ───────────────────────────────────────────────────
        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        ctk.CTkButton(tb, text="＋ Aggiungi file", width=120, height=28,
                      command=self._add_files).pack(side="left", padx=(0, 4))
        ctk.CTkButton(tb, text="Rimuovi", width=80, height=28,
                      **_BTN_DARK, command=self._remove_sel).pack(side="left", padx=2)
        ctk.CTkButton(tb, text="Pulisci lista", width=90, height=28,
                      **_BTN_DARK, command=self._clear_list).pack(side="left", padx=2)

        # ── Body: left list + right editor ────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 0))
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        # Left — file list
        left = ctk.CTkFrame(body, fg_color=("#111", "#111"), corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self._list_sf = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._list_sf.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._empty_lbl = ctk.CTkLabel(
            self._list_sf,
            text="Nessun file  ·  clicca ＋ Aggiungi",
            text_color="#555", font=ctk.CTkFont(size=11))
        self._empty_lbl.pack(expand=True, pady=20)

        # Right — editor (scrollable)
        right = ctk.CTkScrollableFrame(
            body, fg_color=("#111", "#111"), corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        # Tag fields + album art side by side
        editor = ctk.CTkFrame(right, fg_color="transparent")
        editor.pack(fill="x", padx=12, pady=(12, 0))
        editor.grid_columnconfigure(0, weight=1)
        editor.grid_columnconfigure(1, weight=0)

        # Fields
        fields = ctk.CTkFrame(editor, fg_color="transparent")
        fields.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        fields.grid_columnconfigure(1, weight=1)

        SectionLabel(fields, "Tag").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        for i, (key, label) in enumerate(_TAG_FIELDS):
            ctk.CTkLabel(fields, text=label + ":", width=80,
                         anchor="w", font=ctk.CTkFont(size=11)).grid(
                row=i + 1, column=0, sticky="w", pady=3)
            entry = ctk.CTkEntry(fields, placeholder_text=label)
            entry.grid(row=i + 1, column=1, sticky="ew", padx=(4, 0), pady=3)
            self._entries[key] = entry

        # Album art
        art = ctk.CTkFrame(editor, fg_color="transparent")
        art.grid(row=0, column=1, sticky="n")

        SectionLabel(art, "Copertina").pack(fill="x", pady=(0, 6))
        self._art_lbl = ctk.CTkLabel(
            art, text="",
            width=128, height=128,
            fg_color="#1a1a1a", corner_radius=6)
        self._art_lbl.pack()
        self._art_name = ctk.CTkLabel(
            art, text="Nessuna immagine",
            text_color="gray", font=ctk.CTkFont(size=10))
        self._art_name.pack(pady=(4, 6))
        ctk.CTkButton(art, text="Scegli", height=26,
                      command=self._pick_art).pack(fill="x")
        ctk.CTkButton(art, text="Rimuovi", height=26,
                      **_BTN_DARK, command=self._clear_art).pack(
            fill="x", pady=(4, 0))

        # Analysis results area (hidden until Analizza is clicked)
        Separator(right).pack(fill="x", padx=12, pady=(14, 6))
        self._analysis_lbl = SectionLabel(right, "Analisi file")
        self._analysis_lbl.pack(fill="x", padx=12)
        self._analysis_box = ctk.CTkTextbox(
            right, height=140, font=ctk.CTkFont(family="Courier", size=10),
            state="disabled", fg_color="#0d0d0d")
        self._analysis_box.pack(fill="x", padx=12, pady=(4, 12))

        # ── Bottom bar ────────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)

        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")

        self._btn_analyze = ctk.CTkButton(
            bot, text="🔍 Analizza", width=110, height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            state="disabled", **_BTN_DARK,
            command=self._analyze)
        self._btn_analyze.grid(row=0, column=1, padx=(8, 0))

        self._btn_strip = ctk.CTkButton(
            bot, text="🗑 Pulisci tag", width=110, height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            state="disabled", fg_color="#7a1c1c", hover_color="#9a2c2c",
            command=self._strip)
        self._btn_strip.grid(row=0, column=2, padx=(6, 0))

        self._btn_apply_all = ctk.CTkButton(
            bot, text="↕ Applica a tutti", width=130, height=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            state="disabled", **_BTN_DARK,
            command=self._apply_all)
        self._btn_apply_all.grid(row=0, column=3, padx=(6, 0))

        self._btn_save = ctk.CTkButton(
            bot, text="💾 Salva tag", width=110, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._save)
        self._btn_save.grid(row=0, column=4, padx=(6, 0))

    # ── File list management ───────────────────────────────────────────────

    def _add_files(self) -> None:
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Seleziona file audio",
            filetypes=[
                ("Audio", " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))),
                ("Tutti i file", "*.*"),
            ])
        existing = set(self._files)
        for p in paths:
            path = Path(p)
            if path not in existing:
                self._files.append(path)
                self._add_row(path)
                existing.add(path)
        self._refresh_empty()

    def _add_row(self, path: Path) -> None:
        idx = len(self._rows)
        row = ctk.CTkFrame(self._list_sf, fg_color="#222", corner_radius=6)
        row.pack(fill="x", pady=2)

        lbl = ctk.CTkLabel(row, text=path.name, anchor="w",
                           font=ctk.CTkFont(size=11))
        lbl.pack(side="left", padx=8, pady=6, fill="x", expand=True)

        row.bind("<Button-1>", lambda _, i=idx: self._select(i))
        lbl.bind("<Button-1>", lambda _, i=idx: self._select(i))

        self._rows.append(row)

    def _select(self, idx: int) -> None:
        if idx >= len(self._files):
            return
        # Deselect previous
        if self._sel_idx is not None and self._sel_idx < len(self._rows):
            self._rows[self._sel_idx].configure(fg_color="#222")
        self._sel_idx = idx
        self._rows[idx].configure(fg_color="#1a3a5c")
        self._load_tags(self._files[idx])
        self._set_buttons(True)

    def _remove_sel(self) -> None:
        if self._sel_idx is None:
            return
        idx = self._sel_idx
        self._rows[idx].destroy()
        self._rows.pop(idx)
        self._files.pop(idx)
        self._sel_idx = None
        self._set_buttons(False)
        self._clear_fields()
        self._refresh_empty()

    def _clear_list(self) -> None:
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self._files.clear()
        self._sel_idx = None
        self._set_buttons(False)
        self._clear_fields()
        self._refresh_empty()

    def _refresh_empty(self) -> None:
        if self._files:
            self._empty_lbl.pack_forget()
        else:
            self._empty_lbl.pack(expand=True, pady=20)

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self._btn_save, self._btn_strip,
                    self._btn_analyze, self._btn_apply_all):
            btn.configure(state=state)
        if enabled and len(self._files) < 2:
            self._btn_apply_all.configure(state="disabled")

    # ── Tag editor ────────────────────────────────────────────────────────

    def _load_tags(self, path: Path) -> None:
        tags = self._engine.read_tags(path)
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            if key in tags:
                entry.insert(0, tags[key])
        self._clear_art()
        self._status.info(f"Tag caricati: {path.name}")

    def _clear_fields(self) -> None:
        for e in self._entries.values():
            e.delete(0, "end")
        self._clear_art()

    def _pick_art(self) -> None:
        from tkinter import filedialog
        p = filedialog.askopenfilename(
            title="Scegli copertina",
            filetypes=[("Immagini", "*.jpg *.jpeg *.png"), ("Tutti", "*.*")])
        if p:
            self._art_path = Path(p)
            try:
                img = Image.open(p).convert("RGB")
                img.thumbnail((128, 128))
                self._art_photo = ImageTk.PhotoImage(img)
                self._art_lbl.configure(image=self._art_photo, text="")
            except Exception:
                pass
            self._art_name.configure(text=self._art_path.name,
                                     text_color="white")

    def _clear_art(self) -> None:
        self._art_path  = None
        self._art_photo = None
        if hasattr(self, "_art_lbl"):
            self._art_lbl.configure(image=None, text="")
            self._art_name.configure(text="Nessuna immagine", text_color="gray")

    # ── Save / Apply all / Strip ──────────────────────────────────────────

    def _save(self) -> None:
        if self._sel_idx is None:
            return
        path = self._files[self._sel_idx]
        tags = {k: e.get().strip() for k, e in self._entries.items()}
        self._btn_save.configure(state="disabled")
        self._status.busy("Salvataggio tag…")
        threading.Thread(
            target=self._worker_save,
            args=([path], tags, self._art_path),
            daemon=True,
        ).start()

    def _apply_all(self) -> None:
        if not self._files:
            return
        tags = {k: e.get().strip() for k, e in self._entries.items()}
        self._btn_apply_all.configure(state="disabled")
        self._status.busy(f"Applicazione tag a {len(self._files)} file…")
        threading.Thread(
            target=self._worker_save,
            args=(list(self._files), tags, self._art_path),
            daemon=True,
        ).start()

    def _worker_save(self, paths: list[Path], tags: dict, art: Path | None) -> None:
        ok = 0
        errors = []
        for path in paths:
            r = self._engine.write_tags(path, tags, art)
            if r.success:
                ok += 1
            else:
                errors.append(f"{path.name}: {r.error}")
        if errors:
            self.after(0, self._status.err,
                       f"{ok}/{len(paths)} salvati — {errors[0]}")
        else:
            self.after(0, self._status.ok,
                       f"Tag salvati su {ok} file")
        self.after(0, self._set_buttons, True)

    def _strip(self) -> None:
        if self._sel_idx is None:
            return
        path = self._files[self._sel_idx]
        self._btn_strip.configure(state="disabled")
        self._status.busy(f"Rimozione tag da {path.name}…")
        threading.Thread(
            target=self._worker_strip, args=(path,), daemon=True
        ).start()

    def _worker_strip(self, path: Path) -> None:
        r = self._engine.strip_tags(path)
        if r.success:
            self.after(0, self._status.ok, f"Tag rimossi: {path.name}")
            self.after(0, self._clear_fields)
        else:
            self.after(0, self._status.err, r.error)
        self.after(0, self._set_buttons, True)

    # ── Analyze ───────────────────────────────────────────────────────────

    def _analyze(self) -> None:
        if self._sel_idx is None:
            return
        path = self._files[self._sel_idx]
        self._btn_analyze.configure(state="disabled")
        self._status.busy(f"Analisi in corso: {path.name}…")
        self._set_analysis_text("Analisi in corso…")
        threading.Thread(
            target=self._worker_analyze, args=(path,), daemon=True
        ).start()

    def _worker_analyze(self, path: Path) -> None:
        report = self._engine.analyze_file(path)
        lines  = []

        if report["safe"]:
            lines.append("✅  FILE SICURO E INTEGRO")
        else:
            lines.append(f"⚠   PROBLEMI RILEVATI ({len(report['issues'])})")

        lines.append("")
        if report["issues"]:
            lines.append("— Problemi —")
            for issue in report["issues"]:
                lines.append(f"  ✗  {issue}")
            lines.append("")

        lines.append("— Dettagli —")
        for detail in report["details"]:
            lines.append(f"  ✓  {detail}")

        text = "\n".join(lines)
        self.after(0, self._set_analysis_text, text)
        if report["safe"]:
            self.after(0, self._status.ok, f"Analisi completata: {path.name} — nessun problema")
        else:
            self.after(0, self._status.err,
                       f"Analisi: {len(report['issues'])} problema/i rilevato/i")
        self.after(0, self._set_buttons, True)

    def _set_analysis_text(self, text: str) -> None:
        self._analysis_box.configure(state="normal")
        self._analysis_box.delete("1.0", "end")
        self._analysis_box.insert("end", text)
        self._analysis_box.configure(state="disabled")
