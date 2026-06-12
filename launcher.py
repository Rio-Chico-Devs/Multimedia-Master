import sys
import subprocess
from pathlib import Path

import customtkinter as ctk

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "tools"))
from common.version import __version__
from common.ui.geometry import fit_window
from common.ui.widgets import adaptive_wraplength

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
        super().__init__(parent, **kw)
        self.configure(cursor="hand2")
        self._default_color = self.cget("fg_color")

        ctk.CTkLabel(self, text=icon,
                     font=ctk.CTkFont(size=38)).pack(pady=(22, 4))
        ctk.CTkLabel(self, text=title,
                     font=ctk.CTkFont(size=15, weight="bold")).pack()

        feat_text = "  ·  ".join(features)
        feat_lbl = ctk.CTkLabel(self, text=feat_text,
                                text_color="#666",
                                font=ctk.CTkFont(size=10),
                                wraplength=170, justify="center")
        feat_lbl.pack(fill="x", padx=12, pady=(6, 22))
        adaptive_wraplength(feat_lbl, margin=24)

        self._bind_all(on_click)

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
        cards.grid_columnconfigure((0, 1, 2), weight=1)
        cards.grid_rowconfigure(0, weight=1)

        _ToolCard(
            cards,
            icon="🖼",
            title="Convertitore Immagini",
            features=["JPG · PNG · WebP · AVIF", "Comprimi · Ridimensiona",
                      "Profili · Anteprima"],
            on_click=self._launch_image_converter,
        ).grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        _ToolCard(
            cards,
            icon="📄",
            title="Gestione PDF",
            features=["Converti · OCR · Unisci", "Dividi · Proteggi",
                      "Analizza · Sintesi"],
            on_click=self._launch_pdf_manager,
        ).grid(row=0, column=1, sticky="nsew", padx=8)

        _ToolCard(
            cards,
            icon="🎵",
            title="Audio Manager",
            features=["Converti · Estrai da video", "Riduzione rumore · EQ",
                      "Separa tracce · Metadati"],
            on_click=self._launch_audio_manager,
        ).grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        ctk.CTkLabel(self,
                     text=f"v{__version__}  ·  open source  ·  nessuna connessione richiesta",
                     text_color="#333",
                     font=ctk.CTkFont(size=10)).pack(side="bottom", pady=10)

    # ── Launch ─────────────────────────────────────────────────────────────────

    def _launch(self, tool_name: str) -> None:
        script = ROOT / "tools" / tool_name / "app.py"
        tool_dir = script.parent
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(tool_dir),
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
