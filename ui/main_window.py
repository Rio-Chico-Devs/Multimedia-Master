import threading
import customtkinter as ctk
from tkinter import messagebox

from core.converter import ImageConverter
from ui.file_list import FileListPanel
from ui.sidebar import SettingsSidebar


class MainWindow(ctk.CTk):
    """
    Root window — composes FileListPanel and SettingsSidebar,
    owns the conversion thread and coordinates UI updates.
    """

    def __init__(self):
        super().__init__()
        self.title("Multimedia Master  —  Convertitore Immagini")
        self.geometry("960x680")
        self.minsize(720, 520)

        self._converter  = ImageConverter()
        self._converting = False

        self._build_ui()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._file_panel = FileListPanel(self, on_convert=self._start_conversion)
        self._file_panel.grid(
            row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)

        self._sidebar = SettingsSidebar(self)
        self._sidebar.grid(
            row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)

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
        self._file_panel.set_progress_color("#1f6aa5")  # reset to default blue

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
            else:
                print(f"[ERRORE] {row.file_path.name}: {result.error}")

            self.after(0, self._file_panel.set_progress, (i + 1) / total)

        self.after(0, self._on_conversion_done, ok, total)

    def _on_conversion_done(self, ok: int, total: int) -> None:
        self._converting = False
        self._file_panel.set_converting(False)

        if ok == total and total > 0:
            color = "#4caf50"   # green
            msg   = f"✓ {ok}/{total} convertite con successo"
        elif ok > 0:
            color = "#ff9800"   # orange
            msg   = f"✓ {ok}/{total} convertite · {total - ok} con errori"
        else:
            color = "#f44336"   # red
            msg   = "Nessun file convertito — controlla gli errori."

        self._file_panel.set_progress_color(color)
        self._file_panel.set_status(msg)
