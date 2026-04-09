import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog
from typing import Callable

from core.formats import INPUT_EXTS
from ui.file_row import FileRow


class FileListPanel(ctk.CTkFrame):
    """
    Left panel: add-file zone, scrollable file list,
    progress bar and convert button.
    """

    def __init__(self, parent, on_convert: Callable, **kw):
        super().__init__(parent, **kw)
        self._on_convert = on_convert
        self._rows: list[FileRow] = []

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def rows(self) -> list[FileRow]:
        return list(self._rows)

    def add_file(self, path: Path) -> None:
        if path.suffix.lower() not in INPUT_EXTS:
            return
        if any(r.file_path == path for r in self._rows):
            return
        if self._empty_lbl.winfo_ismapped():
            self._empty_lbl.pack_forget()
        row = FileRow(self._list_frame, path, self._remove_row)
        row.pack(fill="x", pady=3, padx=4)
        self._rows.append(row)
        self._refresh_count()

    def set_progress(self, value: float) -> None:
        self._progress.set(value)

    def set_progress_color(self, color: str) -> None:
        self._progress.configure(progress_color=color)

    def set_status(self, text: str) -> None:
        self._status_lbl.configure(text=text)

    def set_converting(self, active: bool) -> None:
        if active:
            self._convert_btn.configure(state="disabled",
                                        text="⏳  Conversione in corso…")
        else:
            self._convert_btn.configure(state="normal",
                                        text="▶  Converti tutto")

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_drop_zone()
        self._build_list()
        self._build_bottom_bar()

    def _build_drop_zone(self) -> None:
        zone = ctk.CTkFrame(self, height=100, corner_radius=12,
                            border_width=2, border_color="#1f6aa5")
        zone.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        zone.grid_propagate(False)
        zone.grid_columnconfigure(0, weight=1)
        zone.grid_rowconfigure(0, weight=1)

        inner = ctk.CTkFrame(zone, fg_color="transparent")
        inner.grid(row=0, column=0)
        ctk.CTkLabel(inner, text="Aggiungi immagini da convertire",
                     font=ctk.CTkFont(size=14, weight="bold")).pack()
        ctk.CTkButton(inner, text="  Sfoglia file  ", width=140, height=34,
                      command=self._browse).pack(pady=(6, 0))

    def _build_list(self) -> None:
        self._list_frame = ctk.CTkScrollableFrame(self, label_text="File in coda")
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        self._list_frame.grid_columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._list_frame,
            text="Nessun file caricato.\nClicca 'Sfoglia file' per iniziare.",
            text_color="gray", justify="center",
        )
        self._empty_lbl.pack(pady=30)

    def _build_bottom_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 10))

        self._progress = ctk.CTkProgressBar(bar, height=8)
        self._progress.pack(fill="x", pady=(0, 8))
        self._progress.set(0)

        self._convert_btn = ctk.CTkButton(
            bar, text="▶  Converti tutto", height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_convert,
        )
        self._convert_btn.pack(fill="x")

        self._status_lbl = ctk.CTkLabel(bar, text="", text_color="gray",
                                        font=ctk.CTkFont(size=11))
        self._status_lbl.pack(pady=(4, 0))

    # ── Internal ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Seleziona immagini",
            filetypes=[
                ("Immagini supportate",
                 "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif"),
                ("Tutti i file", "*.*"),
            ],
        )
        for p in paths:
            self.add_file(Path(p))

    def _remove_row(self, row: FileRow) -> None:
        row.destroy()
        self._rows.remove(row)
        if not self._rows:
            self._empty_lbl.pack(pady=30)
        self._refresh_count()

    def _refresh_count(self) -> None:
        n = len(self._rows)
        if n == 0:
            self._status_lbl.configure(text="")
        elif n == 1:
            self._status_lbl.configure(text="1 immagine in coda")
        else:
            self._status_lbl.configure(text=f"{n} immagini in coda")
