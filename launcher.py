import sys
import subprocess
from pathlib import Path

import customtkinter as ctk

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "tools"))
from common.version import __version__
from common.ui.geometry import fit_window

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ── Card cliccabile ────────────────────────────────────────────────────────────

class _ToolCard(ctk.CTkFrame):
    """Clickable card that launches a tool."""

    def __init__(self, parent, icon: str, title: str, features: list[str],
                 on_click, **kw):
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", "#1f3a5c")
        # Don't let the card shrink/grow to fit its label content: the width
        # is driven top-down by the grid cell. Without this, the feature
        # label's requested width (≈ its wraplength) would feed back into the
        # card → column → window minimum, causing an endless resize loop.
        super().__init__(parent, width=180, height=200, **kw)
        # Children are packed, so pack_propagate(False) is what stops the
        # card from shrinking/growing to its content. The grid cell (with
        # sticky="nsew" + column weight) stretches the card to fill space.
        self.pack_propagate(False)
        self.configure(cursor="hand2")
        self._default_color = self.cget("fg_color")

        ctk.CTkLabel(self, text=icon,
                     font=ctk.CTkFont(size=38)).pack(pady=(22, 4))
        ctk.CTkLabel(self, text=title,
                     font=ctk.CTkFont(size=15, weight="bold")).pack()

        feat_text = "  ·  ".join(features)
        # wraplength is updated top-down by Launcher via set_wraplength();
        # see the cards-container <Configure> binding. No self-binding here,
        # so the label can never drive its own (or the card's) width.
        self.feat_lbl = ctk.CTkLabel(self, text=feat_text,
                                     text_color="#666",
                                     font=ctk.CTkFont(size=10),
                                     wraplength=150, justify="center")
        self.feat_lbl.pack(fill="x", padx=12, pady=(6, 22))

        self._bind_all(on_click)

    def set_wraplength(self, logical_px: int) -> None:
        self.feat_lbl.configure(wraplength=max(90, logical_px))

    def _bind_all(self, cmd):
        for w in [self, *self.winfo_children()]:
            w.bind("<Button-1>", lambda _: cmd())
            w.bind("<Enter>",    lambda _: self.configure(fg_color="#152d4a"))
            w.bind("<Leave>",    lambda _: self.configure(fg_color=self._default_color))


# ── Launcher window ────────────────────────────────────────────────────────────

class Launcher(ctk.CTk):
    """
    Lightweight root window — launches each tool as an independent process.
    No shared state, no shared memory. Pure isolation.
    """

    def __init__(self):
        super().__init__()
        self.title("Multimedia Master")
        fit_window(self, 900, 380, 640, 320)
        self._processes: list[subprocess.Popen] = []
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Multimedia Master",
                     font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(28, 2))
        ctk.CTkLabel(self, text="Il tuo studio multimediale  ·  100% offline",
                     text_color="#555",
                     font=ctk.CTkFont(size=12)).pack(pady=(0, 22))

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="both", expand=True, padx=40)
        # uniform="c" forces the three columns to stay equal width regardless
        # of content, so the layout can never become lopsided.
        cards.grid_columnconfigure((0, 1, 2), weight=1, uniform="c")
        cards.grid_rowconfigure(0, weight=1)
        self._cards_frame = cards

        self._cards = [
            _ToolCard(
                cards,
                icon="🖼",
                title="Convertitore Immagini",
                features=["JPG · PNG · WebP · AVIF", "Comprimi · Ridimensiona",
                          "Profili · Anteprima"],
                on_click=self._launch_image_converter,
            ),
            _ToolCard(
                cards,
                icon="📄",
                title="Gestione PDF",
                features=["Converti · OCR · Unisci", "Dividi · Proteggi",
                          "Analizza · Sintesi"],
                on_click=self._launch_pdf_manager,
            ),
            _ToolCard(
                cards,
                icon="🎵",
                title="Audio Manager",
                features=["Converti · Estrai da video", "Riduzione rumore · EQ",
                          "Separa tracce · Metadati"],
                on_click=self._launch_audio_manager,
            ),
        ]
        for col, (card, pad) in enumerate(
                zip(self._cards, ((0, 8), 8, (8, 0)))):
            card.grid(row=0, column=col, sticky="nsew", padx=pad)

        # Reflow the feature text top-down from the container width. The
        # container is pack(fill=both, expand) so its width tracks the window,
        # NOT the labels — reading it here is fully decoupled from wraplength,
        # which is what kills the old infinite-resize feedback loop.
        cards.bind("<Configure>", self._reflow_cards)

        ctk.CTkLabel(self,
                     text=f"v{__version__}  ·  open source  ·  nessuna connessione richiesta",
                     text_color="#333",
                     font=ctk.CTkFont(size=10)).pack(side="bottom", pady=10)

    # ── Responsive reflow ────────────────────────────────────────────────────────

    def _reflow_cards(self, event=None) -> None:
        """Set each card's feature-text wraplength from the container width."""
        total = self._cards_frame.winfo_width()
        if total < 10:          # not laid out yet
            return
        # Per-card slice minus inter-card gaps and the label's internal padding.
        per_card = total / 3 - 36
        # winfo_width is physical px; CTk re-applies the DPI factor when we set
        # wraplength, so convert to logical units first to avoid double scaling.
        try:
            rev = self._cards[0].feat_lbl._reverse_widget_scaling
            per_card = rev(per_card)
        except Exception:
            pass
        wl = max(90, int(per_card))
        for card in self._cards:
            card.set_wraplength(wl)

    # ── Launch ─────────────────────────────────────────────────────────────────

    def _launch(self, tool_name: str) -> None:
        script = ROOT / "tools" / tool_name / "app.py"
        tool_dir = script.parent
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(tool_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            from tkinter import messagebox
            messagebox.showerror(
                "Avvio fallito",
                f"Impossibile avviare {tool_name}:\n{exc}")
            return
        self._processes.append(proc)
        # If the tool dies within 2 s it crashed at import time —
        # tell the user instead of failing silently.
        self.after(2000, self._check_alive, proc, tool_name)

    def _check_alive(self, proc: subprocess.Popen, tool_name: str) -> None:
        rc = proc.poll()
        if rc is not None and rc != 0:
            from tkinter import messagebox
            log = ROOT / "tools" / tool_name / "crash.log"
            messagebox.showerror(
                "Strumento terminato",
                f"{tool_name} si è chiuso subito (codice {rc}).\n\n"
                f"Controlla il log:\n{log}")

    def _launch_image_converter(self) -> None:
        self._launch("image_converter")

    def _launch_pdf_manager(self) -> None:
        self._launch("pdf_manager")

    def _launch_audio_manager(self) -> None:
        self._launch("audio_manager")

    # ── Close ──────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        # Clean up finished processes, leave running ones alive
        self._processes = [p for p in self._processes if p.poll() is None]
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    Launcher().mainloop()
