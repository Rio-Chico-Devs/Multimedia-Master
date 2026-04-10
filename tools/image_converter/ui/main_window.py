import threading
import customtkinter as ctk
from tkinter import messagebox

from core.converter import ImageConverter
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
        self.title("Multimedia Master  —  Convertitore Immagini")
        self.geometry("980x760")
        self.minsize(740, 560)

        self._converter  = ImageConverter()
        self._converting = False

        self._init_dnd()
        self._build_ui()

    # ── Drag & drop setup (optional dependency) ────────────────────────────────

    def _init_dnd(self) -> None:
        self._dnd_available = False
        try:
            from tkinterdnd2 import TkinterDnD
            TkinterDnD._require(self)
            self._dnd_available = True
        except Exception:
            pass   # app works fine without drag & drop

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._file_panel = FileListPanel(
            self,
            on_convert=self._start_conversion,
            on_select=self._on_row_selected,
        )
        self._file_panel.grid(
            row=0, column=0, sticky="nsew", padx=(12, 6), pady=(12, 6))

        self._sidebar = SettingsSidebar(self)
        self._sidebar.grid(
            row=0, column=1, sticky="nsew", padx=(6, 12), pady=(12, 6))

        self._preview = PreviewPanel(self)
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

    # ── Conversion orchestration ───────────────────────────────────────────────

    def _start_conversion(self) -> None:
        if self._converting:
            return
        rows = self._file_panel.rows
        if not rows:
            messagebox.showwarning(
                "Nessun file",
                "Aggiungi almeno un'immagine prima di convertire.",
            )
            return

        config = self._sidebar.get_config()
        self._converting = True
        self._file_panel.set_converting(True)
        self._file_panel.set_progress(0)
        self._file_panel.set_progress_color("#1f6aa5")

        threading.Thread(
            target=self._run_conversion,
            args=(rows, config),
            daemon=True,
        ).start()

    def _run_conversion(self, rows, config) -> None:
        total = len(rows)
        ok    = 0

        for i, row in enumerate(rows):
            row.set_status("⏳", "#aaaaaa")
            result = self._converter.convert(row.file_path, config)
            row.apply_result(result)

            if result.success:
                ok += 1
                # If this row is currently selected, refresh the preview
                self.after(0, self._refresh_preview_if_selected, row)
            else:
                print(f"[ERRORE] {row.file_path.name}: {result.error}")

            self.after(0, self._file_panel.set_progress, (i + 1) / total)

        self.after(0, self._on_conversion_done, ok, total)

    def _refresh_preview_if_selected(self, row: FileRow) -> None:
        if row.result:
            self._preview.show_result(row.result)

    def _on_conversion_done(self, ok: int, total: int) -> None:
        self._converting = False
        self._file_panel.set_converting(False)

        if ok == total and total > 0:
            color = "#4caf50"
            msg   = f"✓ {ok}/{total} convertite con successo"
        elif ok > 0:
            color = "#ff9800"
            msg   = f"✓ {ok}/{total} convertite  ·  {total - ok} con errori"
        else:
            color = "#f44336"
            msg   = "Nessun file convertito — controlla gli errori."

        self._file_panel.set_progress_color(color)
        self._file_panel.set_status(msg)
