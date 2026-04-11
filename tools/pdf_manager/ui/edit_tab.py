"""
Edit Tab — visual PDF editor.

Layout:
  ┌──────────────────────────────────────────────────────┐
  │  [Apri PDF]  pag ◀ 1/5 ▶  Zoom [▾]  [✂][✥][↕]  [↩] │  ← toolbar
  ├──────────────────────────────────────────────────────┤
  │                                                      │
  │               EditorCanvas  (scrollable)             │
  │                                                      │
  ├──────────────────────────────────────────────────────┤
  │  status bar                          [Salva PDF]     │  ← bottom bar
  └──────────────────────────────────────────────────────┘

Modes:
  ✂  Snip   — rubber-band selection → draggable snippet
  ✥  Sposta — drag existing snippets
  ↕  Spazio — insert / remove horizontal white space

All heavy work (rendering, export) runs in background threads.
"""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from .editor_canvas import EditorCanvas
from .widgets       import SectionLabel, StatusBar
from core.pdf_editor_engine import PdfEditorEngine


# ── Mode button colours ───────────────────────────────────────────────────────

_BTN_ACTIVE   = "#1f6aa5"
_BTN_INACTIVE = "#2a2a2a"
_BTN_HOVER    = "#1a5580"


class EditTab(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)

        self._engine    = PdfEditorEngine()
        self._page_num  = 0
        self._pdf_path: Path | None = None

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_toolbar()
        self._build_canvas()
        self._build_bottom()

        self._set_mode("snip")          # default mode
        self._set_controls_state(False) # disabled until PDF opened

        # Keyboard shortcuts (bind_all so they work regardless of focus)
        self.bind_all("<Control-z>", lambda _: self._undo(), add="+")
        self.bind_all("<Control-Z>", lambda _: self._undo(), add="+")
        self.bind_all("<Control-s>", lambda _: self._save_pdf(), add="+")
        self.bind_all("<Control-S>", lambda _: self._save_pdf(), add="+")
        self.bind_all("<Prior>",     lambda _: self._prev_page(), add="+")  # PgUp
        self.bind_all("<Next>",      lambda _: self._next_page(), add="+")  # PgDn

    # ── Toolbar ────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=("#1a1a1a", "#1a1a1a"),
                           corner_radius=8)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        # Open button
        ctk.CTkButton(bar, text="📂  Apri PDF", width=110, height=30,
                      command=self._open_pdf).pack(side="left", padx=(8, 12))

        # Separator
        ctk.CTkFrame(bar, width=1, height=24, fg_color="#333").pack(
            side="left", padx=4)

        # Page navigation
        self._btn_prev = ctk.CTkButton(bar, text="◀", width=30, height=30,
                                        command=self._prev_page)
        self._btn_prev.pack(side="left", padx=(8, 2))

        self._page_lbl = ctk.CTkLabel(bar, text="—", width=60,
                                       font=ctk.CTkFont(size=12))
        self._page_lbl.pack(side="left", padx=2)

        self._btn_next = ctk.CTkButton(bar, text="▶", width=30, height=30,
                                        command=self._next_page)
        self._btn_next.pack(side="left", padx=(2, 8))

        # Separator
        ctk.CTkFrame(bar, width=1, height=24, fg_color="#333").pack(
            side="left", padx=4)

        # Zoom
        ctk.CTkLabel(bar, text="Zoom:", font=ctk.CTkFont(size=11)).pack(
            side="left", padx=(8, 2))
        self._zoom_var = ctk.StringVar(value="100%")
        self._zoom_menu = ctk.CTkOptionMenu(
            bar, variable=self._zoom_var, width=80, height=28,
            values=["50%", "75%", "100%", "125%", "150%", "200%"],
            command=self._on_zoom_change)
        self._zoom_menu.pack(side="left", padx=(0, 8))

        # Separator
        ctk.CTkFrame(bar, width=1, height=24, fg_color="#333").pack(
            side="left", padx=4)

        # Mode buttons
        ctk.CTkLabel(bar, text="Strumento:",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(8, 4))

        self._btn_snip  = self._mode_btn(bar, "✂  Ritaglia",  "snip")
        self._btn_drag  = self._mode_btn(bar, "✥  Sposta",    "drag")
        self._btn_space = self._mode_btn(bar, "↕  Spazio",    "space")

        self._btn_snip.pack(side="left", padx=2)
        self._btn_drag.pack(side="left", padx=2)
        self._btn_space.pack(side="left", padx=2)

        # Separator
        ctk.CTkFrame(bar, width=1, height=24, fg_color="#333").pack(
            side="left", padx=8)

        # Undo
        self._btn_undo = ctk.CTkButton(bar, text="↩  Annulla", width=90,
                                        height=30, fg_color="#2a2a2a",
                                        hover_color="#3a3a3a",
                                        command=self._undo)
        self._btn_undo.pack(side="left", padx=2)

        # Legend (right side)
        legend = (
            "✂ Seleziona un'area  ·  "
            "✥ Trascina i blocchi  ·  "
            "↕ Trascina su/giù per aggiungere/rimuovere spazio"
        )
        ctk.CTkLabel(bar, text=legend, text_color="#555",
                     font=ctk.CTkFont(size=10)).pack(
            side="right", padx=12)

    def _mode_btn(self, parent, label: str, mode: str) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=label, width=90, height=30,
            fg_color=_BTN_INACTIVE, hover_color=_BTN_HOVER,
            command=lambda m=mode: self._set_mode(m))

    # ── Canvas area ────────────────────────────────────────────────────────

    def _build_canvas(self):
        # Wrap EditorCanvas in a CTkFrame for consistent styling
        wrapper = ctk.CTkFrame(self, corner_radius=8,
                               fg_color=("#111", "#111"))
        wrapper.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        wrapper.grid_rowconfigure(0, weight=1)
        wrapper.grid_columnconfigure(0, weight=1)

        self._editor = EditorCanvas(wrapper, on_change=self._on_canvas_change)
        self._editor.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

    # ── Bottom bar ─────────────────────────────────────────────────────────

    def _build_bottom(self):
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew")
        bot.grid_columnconfigure(0, weight=1)

        self._status = StatusBar(bot)
        self._status.grid(row=0, column=0, sticky="ew")

        self._btn_save = ctk.CTkButton(
            bot, text="💾  Salva PDF modificato",
            width=180, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._save_pdf)
        self._btn_save.grid(row=0, column=1, padx=(8, 0))

    # ── Open PDF ───────────────────────────────────────────────────────────

    def _open_pdf(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Apri PDF da modificare",
            filetypes=[("PDF", "*.pdf"), ("Tutti i file", "*.*")],
        )
        if not path:
            return
        self._pdf_path = Path(path)
        self._status.busy("Apertura e rendering in corso…")
        self.update_idletasks()

        threading.Thread(target=self._worker_open, daemon=True).start()

    def _worker_open(self):
        try:
            n = self._engine.open(self._pdf_path)
            self._page_num = 0
            self.after(0, self._load_current_page)
            self.after(0, self._set_controls_state, True)
            self.after(0, self._status.ok,
                       f"Aperto: {self._pdf_path.name}  ({n} pagine)")
        except ImportError:
            self.after(0, self._status.err,
                       "pymupdf non installato. Esegui: pip install pymupdf")
        except Exception as exc:
            self.after(0, self._status.err, str(exc))

    # ── Page navigation ────────────────────────────────────────────────────

    def _load_current_page(self):
        state = self._engine.get_state(self._page_num)
        zoom  = self._parse_zoom()
        self._editor.load_state(state, zoom=zoom)
        total = self._engine.page_count
        self._page_lbl.configure(
            text=f"{self._page_num + 1} / {total}")

    def _prev_page(self):
        if self._page_num > 0:
            self._page_num -= 1
            self._load_current_page()

    def _next_page(self):
        if self._page_num < self._engine.page_count - 1:
            self._page_num += 1
            self._load_current_page()

    # ── Zoom ───────────────────────────────────────────────────────────────

    def _parse_zoom(self) -> float:
        try:
            return int(self._zoom_var.get().rstrip("%")) / 100
        except ValueError:
            return 1.0

    def _on_zoom_change(self, _=None):
        self._editor.set_zoom(self._parse_zoom())

    # ── Mode ───────────────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self._editor.set_mode(mode)
        for btn, m in [(self._btn_snip,  "snip"),
                       (self._btn_drag,  "drag"),
                       (self._btn_space, "space")]:
            btn.configure(
                fg_color=_BTN_ACTIVE if m == mode else _BTN_INACTIVE)
        hints = {
            "snip":  "✂  Disegna un rettangolo per ritagliare un blocco",
            "drag":  "✥  Clicca e trascina un blocco per spostarlo",
            "space": "↕  Clicca e trascina verso il basso per aggiungere spazio, verso l'alto per rimuoverlo",
        }
        self._status.info(hints.get(mode, ""))

    # ── Undo ───────────────────────────────────────────────────────────────

    def _undo(self):
        self._editor.undo()
        self._status.info("Operazione annullata.")

    # ── Save ───────────────────────────────────────────────────────────────

    def _save_pdf(self):
        if not self._pdf_path:
            return
        from tkinter import filedialog
        default = self._pdf_path.stem + "_modificato.pdf"
        out_path = filedialog.asksaveasfilename(
            title="Salva PDF modificato",
            defaultextension=".pdf",
            initialfile=default,
            filetypes=[("PDF", "*.pdf")],
        )
        if not out_path:
            return
        output = Path(out_path)
        self._status.busy("Salvataggio in corso…")
        self._btn_save.configure(state="disabled")
        self.update_idletasks()

        threading.Thread(
            target=self._worker_save, args=(output,), daemon=True).start()

    def _worker_save(self, output: Path):
        try:
            def progress(p):
                self.after(0, self._status.busy,
                           f"Salvataggio… {int(p*100)}%")
            self._engine.export(output, progress_cb=progress)
            self.after(0, self._status.ok,
                       f"Salvato: {output.name}")
        except Exception as exc:
            self.after(0, self._status.err, str(exc))
        finally:
            self.after(0, self._btn_save.configure, {"state": "normal"})

    # ── Helpers ────────────────────────────────────────────────────────────

    def _set_controls_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for w in (self._btn_prev, self._btn_next, self._btn_snip,
                  self._btn_drag, self._btn_space, self._btn_undo,
                  self._btn_save, self._zoom_menu):
            w.configure(state=state)

    def _on_canvas_change(self):
        """Called by EditorCanvas after any edit."""
        pass   # could update a dirty-flag indicator here
