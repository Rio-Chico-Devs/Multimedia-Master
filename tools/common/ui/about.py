"""Shared "About" dialog — version, copyright and a quick entry point for it."""
from __future__ import annotations

import customtkinter as ctk

from common.version import __version__, __build_year__, APP_NAME


def show_about(parent, tool_label: str | None = None) -> None:
    win = ctk.CTkToplevel(parent)
    win.title("Informazioni")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    title = APP_NAME + (f" — {tool_label}" if tool_label else "")
    ctk.CTkLabel(win, text=title, font=ctk.CTkFont(size=16, weight="bold")
                 ).pack(pady=(24, 4), padx=36)
    ctk.CTkLabel(win, text=f"Versione {__version__}",
                 font=ctk.CTkFont(size=12)).pack(pady=(0, 12))
    ctk.CTkLabel(
        win,
        text=f"© {__build_year__} — tutti i diritti riservati.\n"
             "100% offline · nessuna connessione richiesta.",
        font=ctk.CTkFont(size=11), text_color="#888", justify="center",
    ).pack(pady=(0, 20), padx=36)
    ctk.CTkButton(win, text="Chiudi", width=100,
                  command=win.destroy).pack(pady=(0, 18))

    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    win.geometry(f"+{max(px, 0)}+{max(py, 0)}")


def add_about_button(win, tool_label: str | None = None) -> None:
    """Small unobtrusive "ⓘ" button, overlaid in the top-right corner."""
    btn = ctk.CTkButton(
        win, text="ⓘ", width=26, height=22, corner_radius=6,
        fg_color="transparent", hover_color="#1f3a5c",
        font=ctk.CTkFont(size=13),
        command=lambda: show_about(win, tool_label),
    )
    btn.place(relx=1.0, x=-10, y=8, anchor="ne")
