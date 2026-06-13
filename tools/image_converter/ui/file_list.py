import hashlib
import re
import threading
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

from common.settings import Settings
from core.formats import INPUT_EXTS
from ui.file_row import FileRow
from ui.batch_rename import BatchRenameDialog
from ui.widgets import adaptive_wraplength

# Matches filenames this app produces so the watch loop never re-ingests its
# own output.  Anchored at the END of the stem so "my_clean_scan.jpg" passes
# but "photo_clean.jpg" and "photo_converted.jpg" are filtered out.
#   ImageConverter  → "<stem>_converted"  / "<stem>_converted_<n>"
#   MetadataCleaner → "<stem>_clean"      / "<stem>_clean_<n>"
_OWN_OUTPUT_RE = re.compile(r"_(converted|clean)(_\d+)?$")


class FileListPanel(ctk.CTkFrame):
    """
    Left panel: add-file zone (click + drag & drop), folder import,
    scrollable file list, progress bar and convert button.
    """

    def __init__(
        self,
        parent,
        on_convert:       Callable,
        on_clean:         Callable | None = None,
        on_cancel:        Callable | None = None,
        on_select:        Callable | None = None,
        on_auto_convert:  Callable | None = None,
        on_files_change:  Callable | None = None,
        **kw,
    ):
        super().__init__(parent, **kw)
        self._on_convert        = on_convert
        self._on_clean          = on_clean           # metadata-strip batch
        self._on_cancel         = on_cancel          # abort running batch
        self._on_select         = on_select          # called with FileRow on click
        self._on_auto_convert   = on_auto_convert    # triggered by watch folder
        self._on_files_change   = on_files_change    # called when queue changes
        self._rows: list[FileRow] = []
        self._selected: FileRow | None = None
        self._drag_row: FileRow | None = None
        self._settings = Settings("image_converter")

        # Watch-folder state
        self._watch_folder: Path | None    = None
        self._watch_stop   = threading.Event()
        self._watch_seen:  set[Path]       = set()
        self._watch_timer_id: str | None   = None

        self.grid_rowconfigure(2, weight=1)
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
                      on_select=self._select_row,
                      on_drag_start=self._drag_start,
                      on_drag_motion=self._drag_motion,
                      on_drag_end=self._drag_end)
        row.pack(fill="x", pady=3, padx=4)
        self._rows.append(row)
        self._refresh_count()
        self._notify_files_change()

    def enable_drop(self, dnd_available: bool) -> None:
        """Called by MainWindow after TkinterDnD is initialised (no-op: window handles drops)."""
        pass

    def set_progress(self, value: float) -> None:
        self._progress.set(value)

    def set_progress_color(self, color: str) -> None:
        self._progress.configure(progress_color=color)

    def set_status(self, text: str) -> None:
        self._status_lbl.configure(text=text)

    def set_converting(self, active: bool) -> None:
        text = "⏳  Elaborazione in corso…" if active else "▶  Converti tutto"
        state = "disabled" if active else "normal"
        self._convert_btn.configure(text=text, state=state)
        self._clean_btn.configure(state=state)
        self._cancel_btn.configure(state="normal" if active else "disabled")

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_drop_zone()
        self._build_toolbar()
        self._build_list()
        self._build_bottom_bar()

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 2))

        self._rename_btn = ctk.CTkButton(
            bar, text="✎  Rinomina", width=110, height=28,
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            command=self._open_rename)
        self._rename_btn.pack(side="left", padx=(0, 4))

        self._dedup_btn = ctk.CTkButton(
            bar, text="⧉  Rimuovi duplicati", width=150, height=28,
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            command=self._remove_duplicates)
        self._dedup_btn.pack(side="left", padx=4)

        self._clear_btn = ctk.CTkButton(
            bar, text="🗑  Svuota", width=90, height=28,
            fg_color="#2a2a2a", hover_color="#3a3a3a",
            command=self._clear_all)
        self._clear_btn.pack(side="left", padx=4)

        self._watch_btn = ctk.CTkButton(
            bar, text="👁  Sorveglia", width=130, height=28,
            fg_color="#1a3a1a", hover_color="#2a5a2a",
            command=self._toggle_watch)
        self._watch_btn.pack(side="right", padx=(4, 0))

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
        self._list_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=4)
        self._list_frame.grid_columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._list_frame,
            text="Nessun file caricato.\nClicca 'Sfoglia file' o trascina le immagini qui.",
            text_color="gray", justify="center",
        )
        self._empty_lbl.pack(pady=30)

    def _build_bottom_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 10))

        self._progress = ctk.CTkProgressBar(bar, height=8)
        self._progress.pack(fill="x", pady=(0, 8))
        self._progress.set(0)

        btns = ctk.CTkFrame(bar, fg_color="transparent")
        btns.pack(fill="x")
        btns.grid_columnconfigure(0, weight=3)
        btns.grid_columnconfigure(1, weight=2)
        btns.grid_columnconfigure(2, weight=0)

        self._convert_btn = ctk.CTkButton(
            btns, text="▶  Converti tutto", height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_convert,
        )
        self._convert_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._clean_btn = ctk.CTkButton(
            btns, text="🛡  Pulisci metadati", height=44,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1a4a2a", hover_color="#226636",
            command=lambda: self._on_clean and self._on_clean(),
        )
        self._clean_btn.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        self._cancel_btn = ctk.CTkButton(
            btns, text="⏹", width=52, height=44, state="disabled",
            fg_color="#5a1a1a", hover_color="#7a2a2a",
            command=lambda: self._on_cancel and self._on_cancel(),
        )
        self._cancel_btn.grid(row=0, column=2, sticky="e")

        self._status_lbl = ctk.CTkLabel(bar, text="", text_color="gray",
                                        font=ctk.CTkFont(size=11),
                                        wraplength=420, justify="left")
        self._status_lbl.pack(fill="x", pady=(4, 0))
        adaptive_wraplength(self._status_lbl)

        hint = ctk.CTkLabel(
            bar,
            text="🛡 Pulisci metadati: crea una copia *_clean senza EXIF/GPS — "
                 "qualità identica (lossless per JPG e PNG), originale intatto.",
            text_color="#4a7a5a", font=ctk.CTkFont(size=10),
            wraplength=420, justify="left",
        )
        hint.pack(fill="x", pady=(2, 0))
        adaptive_wraplength(hint)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _last_dir(self) -> str | None:
        """Most recently used folder, if it still exists — for dialog initialdir."""
        for d in self._settings.get_recent("recent_dirs"):
            if Path(d).is_dir():
                return d
        return None

    def _browse_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Seleziona immagini",
            initialdir=self._last_dir(),
            filetypes=[
                ("Immagini supportate",
                 "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif"),
                ("Tutti i file", "*.*"),
            ],
        )
        for p in paths:
            self.add_file(Path(p))
        if paths:
            self._settings.add_recent(str(Path(paths[0]).parent), "recent_dirs")

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="Seleziona cartella",
                                         initialdir=self._last_dir())
        if not folder:
            return
        self._settings.add_recent(folder, "recent_dirs")
        self.set_status("Scansione cartella…")
        threading.Thread(
            target=self._scan_folder_bg,
            args=(Path(folder),),
            daemon=True,
        ).start()

    def _scan_folder_bg(self, folder: Path) -> None:
        paths = sorted(
            p for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in INPUT_EXTS
        )
        self.after(0, self._add_paths_sequential, paths, 0)

    def _add_paths_sequential(self, paths: list, idx: int) -> None:
        if idx >= len(paths):
            n = len(paths)
            self.set_status(f"{n} immagini aggiunte" if n else "Nessuna immagine trovata")
            return
        self.add_file(paths[idx])
        # 2 ms gap — lets the event loop repaint between rows
        self.after(2, self._add_paths_sequential, paths, idx + 1)

    def _remove_row(self, row: FileRow) -> None:
        if self._selected is row:
            self._selected = None
        row.destroy()
        self._rows.remove(row)
        if not self._rows:
            self._empty_lbl.pack(pady=30)
        self._refresh_count()
        self._notify_files_change()

    def _select_row(self, row: FileRow) -> None:
        if self._selected and self._selected is not row:
            self._selected.set_selected(False)
        self._selected = row
        row.set_selected(True)
        if self._on_select:
            self._on_select(row)

    # ── Drag to reorder ──────────────────────────────────────────────────────

    def _drag_start(self, row: FileRow, _event) -> None:
        self._drag_row = row
        row.configure(fg_color="#2a4a6c")

    def _drag_motion(self, row: FileRow, event) -> None:
        if self._drag_row is None:
            return
        y = event.y_root
        try:
            cur = self._rows.index(row)
        except ValueError:
            return
        # Move the dragged row onto whichever row the pointer currently overlaps.
        target = cur
        for i, r in enumerate(self._rows):
            if r is row or not r.winfo_exists():
                continue
            top = r.winfo_rooty()
            if top <= y <= top + r.winfo_height():
                target = i
                break
        if target != cur:
            self._rows.insert(target, self._rows.pop(cur))
            self._repack_rows()

    def _drag_end(self, row: FileRow, _event) -> None:
        if self._drag_row is not None:
            # Restore the normal/selected colour now that the drag is over.
            self._drag_row.set_selected(self._drag_row is self._selected)
            self._drag_row = None

    def _repack_rows(self) -> None:
        for r in self._rows:
            if r.winfo_exists():
                r.pack_forget()
        for r in self._rows:
            if r.winfo_exists():
                r.pack(fill="x", pady=3, padx=4)

    # ── Queue actions: rename / dedup / clear ────────────────────────────────

    def _clear_all(self) -> None:
        for row in list(self._rows):
            self._remove_row(row)
        # _remove_row fires _notify_files_change per row; one more here covers
        # the no-rows case where the estimate should be cleared immediately.
        self._notify_files_change()

    def _open_rename(self) -> None:
        if not self._rows:
            messagebox.showinfo("Rinomina", "Aggiungi prima delle immagini.")
            return
        BatchRenameDialog(self, [r.file_path for r in self._rows],
                          on_apply=self._apply_rename)

    def _apply_rename(self, mapping: dict[Path, Path]) -> None:
        """mapping: {old_path: new_path} for files renamed on disk."""
        renamed = 0
        for row in self._rows:
            new = mapping.get(row.file_path)
            if new and new != row.file_path:
                row.file_path = new
                row.refresh_name()
                renamed += 1
        self.set_status(f"✎ {renamed} file rinominati" if renamed
                        else "Nessun file rinominato")

    def _remove_duplicates(self) -> None:
        if not self._rows:
            return
        self._dedup_btn.configure(state="disabled")
        self.set_status("Ricerca duplicati (hash dei contenuti)…")
        items = [(r, r.file_path) for r in self._rows]
        threading.Thread(target=self._dedup_bg, args=(items,),
                         daemon=True).start()

    def _dedup_bg(self, items: list) -> None:
        seen: dict[str, FileRow] = {}
        dupes: list[FileRow] = []
        for row, path in items:
            try:
                h = self._hash_file(path)
            except Exception:
                continue
            if h in seen:
                dupes.append(row)
            else:
                seen[h] = row
        self.after(0, self._dedup_done, dupes)

    @staticmethod
    def _hash_file(path: Path, chunk: int = 1 << 20) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(chunk), b""):
                h.update(block)
        return h.hexdigest()

    def _dedup_done(self, dupes: list) -> None:
        self._dedup_btn.configure(state="normal")
        if not dupes:
            self.set_status("Nessun duplicato trovato")
            return
        for row in dupes:
            if row in self._rows:
                self._remove_row(row)
        self.set_status(f"⧉ {len(dupes)} duplicati rimossi dalla coda")

    # ── Watch folder ──────────────────────────────────────────────────────────

    def _toggle_watch(self) -> None:
        if self._watch_folder is None:
            self._start_watch()
        else:
            self._stop_watch()

    def _start_watch(self) -> None:
        folder = filedialog.askdirectory(
            title="Seleziona cartella da sorvegliare",
            initialdir=self._last_dir(),
        )
        if not folder:
            return
        self._watch_folder = Path(folder)
        # Pre-populate seen set so existing files aren't auto-imported.
        self._watch_seen = {
            p for p in self._watch_folder.rglob("*")
            if p.is_file() and p.suffix.lower() in INPUT_EXTS
        }
        self._watch_stop.clear()
        threading.Thread(target=self._watch_loop, daemon=True).start()
        name = self._watch_folder.name[:16]
        self._watch_btn.configure(
            text=f"⏹  {name}",
            fg_color="#5a1a1a", hover_color="#7a2a2a",
        )
        self.set_status(f"👁 Sorvegliando: {self._watch_folder}")

    def _stop_watch(self) -> None:
        self._watch_stop.set()
        if self._watch_timer_id:
            self.after_cancel(self._watch_timer_id)
            self._watch_timer_id = None
        self._watch_folder = None
        self._watch_btn.configure(
            text="👁  Sorveglia",
            fg_color="#1a3a1a", hover_color="#2a5a2a",
        )
        self.set_status("Sorveglianza cartella interrotta")

    def _watch_loop(self) -> None:
        """Background thread: poll folder every 5 s for new image files."""
        while not self._watch_stop.wait(5.0):
            folder = self._watch_folder
            if folder is None:
                break
            try:
                for p in sorted(folder.rglob("*")):
                    if (p.is_file()
                            and p.suffix.lower() in INPUT_EXTS
                            and not self._is_conversion_output(p)
                            and p not in self._watch_seen):
                        self._watch_seen.add(p)
                        self.after(0, self._on_watch_new_file, p)
            except Exception:
                pass

    @staticmethod
    def _is_conversion_output(path: Path) -> bool:
        """
        True if the file looks like something the converter produced
        (stem ends in '_converted' or '_converted_<n>'). Prevents the watch
        loop from re-ingesting its own output and looping forever when the
        output directory is the watched folder.
        """
        return bool(_OWN_OUTPUT_RE.search(path.stem))

    def _on_watch_new_file(self, path: Path) -> None:
        """Called on the main thread when the watcher discovers a new file."""
        self.add_file(path)
        self.set_status(f"👁 Nuovo file rilevato: {path.name}")
        if self._on_auto_convert:
            # Debounce: wait 3 s after the last new file before starting batch.
            if self._watch_timer_id:
                self.after_cancel(self._watch_timer_id)
            self._watch_timer_id = self.after(3000, self._watch_trigger_convert)

    def _watch_trigger_convert(self) -> None:
        self._watch_timer_id = None
        if self._on_auto_convert:
            self._on_auto_convert()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _notify_files_change(self) -> None:
        if self._on_files_change:
            self._on_files_change()

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
