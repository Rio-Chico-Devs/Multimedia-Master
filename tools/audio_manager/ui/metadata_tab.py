"""
Metadata Tab — read and write ID3 / Vorbis / MP4 / FLAC tags + album art.

Supported formats: MP3, M4A, FLAC, OGG (via mutagen).
Album art is displayed as a 128×128 thumbnail.
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
from .widgets import MediaFilePicker


_TAG_FIELDS = [
    ("title",       "Titolo"),
    ("artist",      "Artista"),
    ("album",       "Album"),
    ("date",        "Anno"),
    ("tracknumber", "Traccia n°"),
    ("genre",       "Genere"),
    ("comment",     "Commento"),
]


class MetadataTab(ctk.CTkFrame):

    def __init__(self, parent, engine: AudioEngine, deps: DepStatus, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._engine   = engine
        self._deps     = deps
        self._art_path: Path | None = None
        self._entries:  dict[str, ctk.CTkEntry] = {}
        self._art_photo: ImageTk.PhotoImage | None = None
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

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

        # File picker
        self._picker = MediaFilePicker(
            self, label="File audio",
            exts={".mp3", ".m4a", ".flac", ".ogg", ".mp4"},
            on_change=self._on_file_change)
        self._picker.grid(row=0, column=0, sticky="ew",
                          padx=12, pady=(12, 0))

        body = ctk.CTkFrame(self, fg_color=("#111", "#111"), corner_radius=10)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        # ── Tag fields (left) ─────────────────────────────────────────────
        fields = ctk.CTkFrame(body, fg_color="transparent")
        fields.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        fields.grid_columnconfigure(1, weight=1)

        SectionLabel(fields, "Tag").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        for i, (key, label) in enumerate(_TAG_FIELDS):
            ctk.CTkLabel(fields, text=label + ":", width=80,
                          anchor="w", font=ctk.CTkFont(size=11)).grid(
                row=i + 1, column=0, sticky="w", pady=3)
            entry = ctk.CTkEntry(fields, placeholder_text=label)
            entry.grid(row=i + 1, column=1, sticky="ew", padx=(4, 0), pady=3)
            self._entries[key] = entry

        # ── Album art (right) ─────────────────────────────────────────────
        art_frame = ctk.CTkFrame(body, fg_color="transparent")
        art_frame.grid(row=0, column=1, sticky="nsew",
                       padx=(0, 12), pady=12)

        SectionLabel(art_frame, "Copertina album").pack(fill="x",
                                                         pady=(0, 8))

        # Art display (128×128 placeholder)
        self._art_lbl = ctk.CTkLabel(
            art_frame, text="",
            width=128, height=128,
            fg_color="#1a1a1a", corner_radius=6)
        self._art_lbl.pack()

        self._art_name = ctk.CTkLabel(
            art_frame, text="Nessuna immagine",
            text_color="gray", font=ctk.CTkFont(size=10))
        self._art_name.pack(pady=(4, 6))

        ctk.CTkButton(art_frame, text="Scegli immagine", height=28,
                      command=self._pick_art).pack(fill="x")
        ctk.CTkButton(art_frame, text="Rimuovi", height=28,
                      fg_color="#2a2a2a", hover_color="#3a3a3a",
                      command=self._clear_art).pack(fill="x", pady=(4, 0))

        # Bottom bar
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        bot.grid_columnconfigure(0, weight=1)
        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")
        self._btn_save = ctk.CTkButton(
            bot, text="💾  Salva tag",
            width=130, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._save)
        self._btn_save.grid(row=0, column=1, padx=(8, 0))

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_file_change(self, path: Path | None) -> None:
        if not path:
            for e in self._entries.values():
                e.delete(0, "end")
            self._clear_art()
            if hasattr(self, "_btn_save"):
                self._btn_save.configure(state="disabled")
            return

        tags = self._engine.read_tags(path)
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            if key in tags:
                entry.insert(0, tags[key])

        self._btn_save.configure(state="normal")
        self._status.info(f"Tag caricati da: {path.name}")

    def _pick_art(self) -> None:
        from tkinter import filedialog
        p = filedialog.askopenfilename(
            title="Scegli copertina",
            filetypes=[("Immagini", "*.jpg *.jpeg *.png"), ("Tutti", "*.*")])
        if p:
            self._art_path = Path(p)
            self._show_art_preview(self._art_path)
            self._art_name.configure(text=self._art_path.name,
                                      text_color="white")

    def _clear_art(self) -> None:
        self._art_path = None
        self._art_photo = None
        if hasattr(self, "_art_lbl"):
            self._art_lbl.configure(image=None, text="")
            self._art_name.configure(text="Nessuna immagine",
                                      text_color="gray")

    def _show_art_preview(self, path: Path) -> None:
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail((128, 128))
            self._art_photo = ImageTk.PhotoImage(img)
            self._art_lbl.configure(image=self._art_photo, text="")
        except Exception:
            pass

    # ── Save ───────────────────────────────────────────────────────────────

    def _save(self) -> None:
        src = self._picker.get_path()
        if not src:
            return

        tags = {key: entry.get().strip()
                for key, entry in self._entries.items()}

        self._btn_save.configure(state="disabled")
        self._status.busy("Salvataggio tag…")
        threading.Thread(
            target=self._worker, args=(src, tags), daemon=True
        ).start()

    def _worker(self, src: Path, tags: dict) -> None:
        result = self._engine.write_tags(src, tags, self._art_path)
        if result.success:
            self.after(0, self._status.ok, f"Tag salvati: {src.name}")
        else:
            self.after(0, self._status.err, result.error)
        self.after(0, self._btn_save.configure, {"state": "normal"})
