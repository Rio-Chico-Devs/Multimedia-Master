import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog
from typing import Callable

from core.formats import INPUT_EXTS
from ui.file_row import FileRow


class FileListPanel(ctk.CTkFrame):
    """
    Left panel: add-file zone (click + drag & drop), folder import,
    scrollable file list, progress bar and convert button.
    """

    def __init__(
        self,
        parent,
        on_convert: Callable,
        on_select:  Callable | None = None,
        **kw,
    ):
        super().__init__(parent, **kw)
        self._on_convert = on_convert
        self._on_select  = on_select   # called with FileRow when a row is clicked
        self._rows: list[FileRow] = []
        self._selected: FileRow | None = None

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
        row = FileRow(self._list_frame, path,
                      on_remove=self._remove_row,
                      on_select=self._select_row)
        row.pack(fill="x", pady=3, padx=4)
        self._rows.append(row)
        self._refresh_count()

    def enable_drop(self, dnd_available: bool) -> None:
        """Called by MainWindow after TkinterDnD is initialised."""
        if not dnd_available:
            return
        try:
            from tkinterdnd2 import DND_FILES
            self._drop_zone.drop_target_register(DND_FILES)
            self._drop_zone.dnd_bind("<<Drop>>", self._on_drop)
            self._list_frame.drop_target_register(DND_FILES)
            self._list_frame.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def set_progress(self, value: float) -> None:
        self._progress.set(value)

    def set_progress_color(self, color: str) -> None:
        self._progress.configure(progress_color=color)

    def set_status(self, text: str) -> None:
        self._status_lbl.configure(text=text)

    def set_converting(self, active: bool) -> None:
        text = "⏳  Conversione in corso…" if active else "▶  Converti tutto"
        state = "disabled" if active else "normal"
        self._convert_btn.configure(text=text, state=state)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_drop_zone()
        self._build_list()
        self._build_bottom_bar()

    def _build_drop_zone(self) -> None:
        self._drop_zone = ctk.CTkFrame(
            self, height=100, corner_radius=12,
            border_width=2, border_color="#1f6aa5",
        )
        self._drop_zone.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        self._drop_zone.grid_propagate(False)
        self._drop_zone.grid_columnconfigure((0, 1), weight=1)
        self._drop_zone.grid_rowconfigure(0, weight=1)

        inner = ctk.CTkFrame(self._drop_zone, fg_color="transparent")
        inner.grid(row=0, column=0, columnspan=2)

        ctk.CTkLabel(inner, text="Trascina qui le immagini  oppure",
                     font=ctk.CTkFont(size=13, weight="bold")).pack()

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(pady=(6, 0))

        ctk.CTkButton(btn_row, text="Sfoglia file", width=130, height=32,
                      command=self._browse_files).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Aggiungi cartella", width=140, height=32,
                      fg_color="#2a5a8a", hover_color="#1f4a7a",
                      command=self._browse_folder).pack(side="left")

    def _build_list(self) -> None:
        self._list_frame = ctk.CTkScrollableFrame(self, label_text="File in coda")
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        self._list_frame.grid_columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._list_frame,
            text="Nessun file caricato.\nClicca 'Sfoglia file' o trascina le immagini qui.",
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

    def _browse_files(self) -> None:
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

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="Seleziona cartella")
        if not folder:
            return
        added = 0
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file() and path.suffix.lower() in INPUT_EXTS:
                self.add_file(path)
                added += 1
        if added:
            self.set_status(f"{added} immagini aggiunte dalla cartella")

    def _remove_row(self, row: FileRow) -> None:
        if self._selected is row:
            self._selected = None
        row.destroy()
        self._rows.remove(row)
        if not self._rows:
            self._empty_lbl.pack(pady=30)
        self._refresh_count()

    def _select_row(self, row: FileRow) -> None:
        if self._selected and self._selected is not row:
            self._selected.set_selected(False)
        self._selected = row
        row.set_selected(True)
        if self._on_select:
            self._on_select(row)

    def _on_drop(self, event) -> None:
        paths = self.tk.splitlist(event.data)
        for p in paths:
            path = Path(p)
            if path.is_dir():
                for f in sorted(path.rglob("*")):
                    if f.is_file() and f.suffix.lower() in INPUT_EXTS:
                        self.add_file(f)
            else:
                self.add_file(path)

    def _refresh_count(self) -> None:
        n = len(self._rows)
        if n == 0:
            self._status_lbl.configure(text="")
        elif n == 1:
            self._status_lbl.configure(text="1 immagine in coda")
        else:
            self._status_lbl.configure(text=f"{n} immagini in coda")
