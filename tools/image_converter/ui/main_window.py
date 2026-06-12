import threading
import customtkinter as ctk
from tkinter import messagebox

from common.version import __version__
from common.ui.geometry import fit_window
from core.converter import ImageConverter
from core.metadata_cleaner import MetadataCleaner
from ui.file_list import FileListPanel
from ui.file_row import FileRow
from ui.sidebar import SettingsSidebar
from ui.preview_panel import PreviewPanel


class MainWindow(ctk.CTk):
    """
    Root window — composes FileListPanel, SettingsSidebar and PreviewPanel.
    Owns the conversion thread and coordinates all UI updates.
    Initialises TkinterDnD drag-and-drop if the library is available.
    """

    def __init__(self):
        super().__init__()
        self.title(f"Multimedia Master  —  Convertitore Immagini  v{__version__}")
        # min height 540: drop zone + bottom bar + preview strip are fixed,
        # below that the file list would collapse to nothing.
        fit_window(self, 980, 760, 720, 540)

        self._converter    = ImageConverter()
        self._cleaner      = MetadataCleaner()
        self._converting   = False
        self._cancel_event = threading.Event()

        self._init_dnd()
        self._build_ui()

    # ── Drag & drop setup (optional dependency) ────────────────────────────────

    def _init_dnd(self) -> None:
        self._dnd_available = False
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES
            TkinterDnD._require(self)
            # Register the entire window so drops work anywhere,
            # regardless of which internal Canvas/Frame is under the cursor.
            self.tk.call("tkdnd::drop_target", "register", self._w, DND_FILES)
            self.bind("<<Drop>>", self._on_window_drop)
            self._dnd_available = True
        except Exception as exc:
            import sys
            print(f"[INFO] Drag&drop non disponibile: {exc}", file=sys.stderr)

    def _on_window_drop(self, event) -> None:
        """Forward window-level drops to the file panel."""
        if hasattr(self, "_file_panel"):
            self._file_panel._on_drop(event)

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._file_panel = FileListPanel(
            self,
            on_convert=self._start_conversion,
            on_clean=self._start_cleaning,
            on_cancel=self._cancel,
            on_select=self._on_row_selected,
        )
        self._file_panel.grid(
            row=0, column=0, sticky="nsew", padx=(12, 6), pady=(12, 6))

        self._sidebar = SettingsSidebar(self)
        self._sidebar.grid(
            row=0, column=1, sticky="nsew", padx=(6, 12), pady=(12, 6))

        # Shorter preview strip on small screens so the file list keeps room.
        preview_h = 210 if self.winfo_screenheight() >= 860 else 160
        self._preview = PreviewPanel(self, height=preview_h)
        self._preview.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))

        # Enable drop targets once widgets exist
        self._file_panel.enable_drop(self._dnd_available)

    # ── File selection → preview ───────────────────────────────────────────────

    def _on_row_selected(self, row: FileRow) -> None:
        if row.result:
            self._preview.show_result(row.result)
        else:
            self._preview.show_source(row.file_path)

    # ── Shared batch helpers ───────────────────────────────────────────────────

    def _begin_batch(self) -> list[FileRow] | None:
        """Common pre-flight for convert/clean. Returns rows or None."""
        if self._converting:
            return None
        rows = self._file_panel.rows
        if not rows:
            messagebox.showwarning(
                "Nessun file",
                "Aggiungi almeno un'immagine prima di procedere.",
            )
            return None
        self._converting = True
        self._cancel_event.clear()
        self._file_panel.set_converting(True)
        self._file_panel.set_progress(0)
        self._file_panel.set_progress_color("#1f6aa5")
        return rows

    def _cancel(self) -> None:
        self._cancel_event.set()
        self._file_panel.set_status("Annullamento dopo il file corrente…")

    # ── Conversion orchestration ───────────────────────────────────────────────

    _ANIMATED_EXTS    = frozenset({".gif", ".webp"})
    _ANIMATED_FMT_OUT = frozenset({"GIF", "WebP"})

    def _start_conversion(self) -> None:
        rows = self._begin_batch()
        if rows is None:
            return
        config = self._sidebar.get_config()   # read tk vars on main thread

        # Warn if any animated source is being converted to a static format.
        if config.format not in self._ANIMATED_FMT_OUT:
            animated = [r.file_path for r in rows
                        if r.file_path.suffix.lower() in self._ANIMATED_EXTS]
            if animated:
                names = "\n".join(f"  · {p.name}" for p in animated[:5])
                if len(animated) > 5:
                    names += f"\n  … e altri {len(animated) - 5}"
                if not messagebox.askyesno(
                    "File animati rilevati",
                    f"{len(animated)} file potrebbero essere animati:\n{names}\n\n"
                    f"Convertendo in {config.format} si salverà solo il "
                    f"primo fotogramma.\n\nContinuare?",
                    icon="warning",
                ):
                    self._converting = False
                    self._file_panel.set_converting(False)
                    return

        threading.Thread(
            target=self._run_conversion,
            args=(rows, config),
            daemon=True,
        ).start()

    def _run_conversion(self, rows, config) -> None:
        import sys
        total     = len(rows)
        ok        = 0
        cancelled = False

        for i, row in enumerate(rows):
            if self._cancel_event.is_set():
                cancelled = True
                break
            # ALL widget updates go through after() — tkinter is not
            # thread-safe and direct calls from here crash on Windows.
            self.after(0, row.set_status, "⏳", "#aaaaaa")
            self.after(0, self._file_panel.set_status,
                       f"({i + 1}/{total})  {row.file_path.name}")

            result = self._converter.convert(row.file_path, config)

            self.after(0, row.apply_result, result)
            if result.success:
                ok += 1
                self.after(0, self._refresh_preview_if_selected, row)
            else:
                print(f"[ERRORE] {row.file_path.name}: {result.error}",
                      file=sys.stderr)
            self.after(0, self._file_panel.set_progress, (i + 1) / total)

        self.after(0, self._on_batch_done, ok, total,
                   "convertite", cancelled)

    # ── Metadata cleaning orchestration ────────────────────────────────────────

    def _start_cleaning(self) -> None:
        rows = self._begin_batch()
        if rows is None:
            return
        out_dir = self._sidebar.get_config().output_dir   # main thread
        threading.Thread(
            target=self._run_cleaning,
            args=(rows, out_dir),
            daemon=True,
        ).start()

    def _run_cleaning(self, rows, out_dir) -> None:
        import sys
        total     = len(rows)
        ok        = 0
        cancelled = False
        removed_counts: dict[str, int] = {}

        for i, row in enumerate(rows):
            if self._cancel_event.is_set():
                cancelled = True
                break
            self.after(0, row.set_status, "⏳", "#aaaaaa")
            self.after(0, self._file_panel.set_status,
                       f"Pulizia ({i + 1}/{total})  {row.file_path.name}")

            src    = row.file_path
            target = (out_dir or src.parent)
            output = self._unique_clean_path(target, src)
            result = self._cleaner.clean(src, output)

            if result.success:
                ok += 1
                for label in result.removed:
                    removed_counts[label] = removed_counts.get(label, 0) + 1
                tag = "🛡 pulita" if result.removed else "🛡 già pulita"
                self.after(0, row.set_status, tag, "#4caf50")
            else:
                print(f"[ERRORE] {src.name}: {result.error}", file=sys.stderr)
                self.after(0, row.set_status, "✗ errore", "#f44336")
            self.after(0, self._file_panel.set_progress, (i + 1) / total)

        summary = ""
        if removed_counts:
            parts = [f"{label} ({n})" for label, n in
                     sorted(removed_counts.items(), key=lambda kv: -kv[1])]
            summary = "  ·  rimossi: " + ", ".join(parts)
        self.after(0, self._on_batch_done, ok, total,
                   "pulite" + summary, cancelled)

    @staticmethod
    def _unique_clean_path(directory, src):
        path = directory / f"{src.stem}_clean{src.suffix}"
        counter = 1
        while path.exists():
            path = directory / f"{src.stem}_clean_{counter}{src.suffix}"
            counter += 1
        return path

    # ── Batch completion ───────────────────────────────────────────────────────

    def _refresh_preview_if_selected(self, row: FileRow) -> None:
        if row.result:
            self._preview.show_result(row.result)

    def _on_batch_done(self, ok: int, total: int,
                       verb: str, cancelled: bool) -> None:
        self._converting = False
        self._file_panel.set_converting(False)

        if cancelled:
            color = "#ff9800"
            msg   = f"⏹ Annullato  ·  {ok} {verb} prima dell'interruzione"
        elif ok == total and total > 0:
            color = "#4caf50"
            msg   = f"✓ {ok}/{total} {verb}"
        elif ok > 0:
            color = "#ff9800"
            msg   = f"✓ {ok}/{total} {verb}  ·  {total - ok} con errori"
        else:
            color = "#f44336"
            msg   = "Nessun file elaborato — controlla gli errori."

        self._file_panel.set_progress_color(color)
        self._file_panel.set_status(msg)
