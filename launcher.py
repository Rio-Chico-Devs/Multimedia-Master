import sys
import subprocess
from pathlib import Path

import customtkinter as ctk

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "tools"))
from common.version import __version__
from common.ui.geometry import fit_window
from common.paths import crash_log_path

_TOOLS = ("image_converter", "pdf_manager", "audio_manager")

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
        # Fixed-size card. Nothing in this app ever measures or recomputes the
        # layout: the window's native geometry manager stretches/shrinks the
        # card via the grid cell (sticky + weight) and that is guaranteed
        # stable. There is deliberately NO <Configure> handler that reacts to
        # size by changing geometry — that pattern caused an endless
        # resize loop and must never be reintroduced.
        super().__init__(parent, width=180, height=200, **kw)
        self.pack_propagate(False)   # card keeps its size, ignores content
        self.configure(cursor="hand2")
        self._default_color = self.cget("fg_color")

        ctk.CTkLabel(self, text=icon,
                     font=ctk.CTkFont(size=38)).pack(pady=(22, 4))
        ctk.CTkLabel(self, text=title,
                     font=ctk.CTkFont(size=15, weight="bold")).pack()

        feat_text = "  ·  ".join(features)
        # Fixed wraplength — never adjusted at runtime, so it can never trigger
        # a resize feedback loop. 150 px fits comfortably inside the card at
        # every supported window size.
        ctk.CTkLabel(self, text=feat_text,
                     text_color="#666",
                     font=ctk.CTkFont(size=10),
                     wraplength=150, justify="center").pack(
            fill="x", padx=12, pady=(6, 22))

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
        # uniform="c" forces the three columns to stay equal width regardless
        # of content, so the layout can never become lopsided.
        cards.grid_columnconfigure((0, 1, 2), weight=1, uniform="c")
        cards.grid_rowconfigure(0, weight=1)

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

        ctk.CTkLabel(self,
                     text=f"v{__version__}  ·  open source  ·  nessuna connessione richiesta",
                     text_color="#333",
                     font=ctk.CTkFont(size=10)).pack(side="bottom", pady=10)

    # ── Launch ─────────────────────────────────────────────────────────────────

    def _launch(self, tool_name: str) -> None:
        # Frozen build: sys.executable IS the bundled exe, so re-invoke it
        # with --tool — the bootloader re-runs this same script (see the
        # entry point below), which dispatches to the requested tool.
        # Dev mode: invoke the system Python on this exact file instead.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--tool", tool_name]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve()), "--tool", tool_name]
        try:
            proc = subprocess.Popen(
                cmd,
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
            log = crash_log_path(tool_name)
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
#
# This file is the single PyInstaller entry point for the whole app. The
# launcher window spawns each tool as a SEPARATE PROCESS by re-invoking this
# same exe with --tool <name> (see _launch above) — runpy then executes that
# tool's app.py exactly as if it had been run directly, preserving the
# process isolation the app relies on (one tool crashing never takes down
# the launcher or any other tool).

if __name__ == "__main__":
    import argparse
    _parser = argparse.ArgumentParser()
    _parser.add_argument("--tool", choices=_TOOLS)
    _args = _parser.parse_args()

    if _args.tool:
        import runpy
        runpy.run_path(
            str(ROOT / "tools" / _args.tool / "app.py"), run_name="__main__")
    else:
        Launcher().mainloop()
