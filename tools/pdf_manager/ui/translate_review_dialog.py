"""
Section review dialog — the manual-review step of the PDF translation flow.

Used twice per job (see translate_tab.py):
  1. After extraction, on the *source* text: the user sees every section the
     engine found, can drop ones that are noise/garbled ("✕") or fix the
     source text before it ever reaches the MT engine.
  2. After translation, on the *translated* text: same sections, now editable
     on the translated side, with the original kept alongside as a reference.

Renders ONE PDF page's sections at a time, with Previous/Next navigation,
instead of every section in one long scroll. A 150-page manual can easily
produce a thousand-plus sections; building that many CTkTextbox/CTkFrame/
CTkButton widgets in one go freezes the UI for several seconds and makes the
scrollable frame itself sluggish to the point of feeling broken. Showing only
the current page's handful of sections keeps widget count — and therefore
build time — constant regardless of document size. Edits are committed back
into the section dicts on every navigation, not just on final confirm, so
moving between pages never loses them.
"""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .widgets import Separator


def _autosize(text: str) -> int:
    """Rough line count for an initial textbox height (chars-per-line is a
    guess tuned for the dialog's width; the box stays scrollable if wrong)."""
    chars_per_line = 70
    lines = max(1, -(-len(text) // chars_per_line))  # ceil div
    return min(max(lines, 2), 10)


class _SectionCard(ctk.CTkFrame):
    """One editable section: its text (source or translation), an optional
    read-only reference line, and a remove/restore toggle."""

    def __init__(self, parent, section: dict, *, mode: str,
                 on_toggle: Callable[[], None] | None = None):
        super().__init__(parent, corner_radius=8, fg_color=("#222", "#222"))
        self._section  = section
        self._mode     = mode
        self._field    = "text" if mode == "source" else "translated"
        self._on_toggle = on_toggle

        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        header.grid_columnconfigure(0, weight=1)
        self._tag_lbl = ctk.CTkLabel(header, text="", text_color="#888",
                                      font=ctk.CTkFont(size=10), anchor="w")
        self._tag_lbl.grid(row=0, column=0, sticky="w")
        self._toggle_btn = ctk.CTkButton(header, text="✕", width=26, height=22,
                                          fg_color="#3a1f1f", hover_color="#5c2a2a",
                                          command=self._toggle_removed)
        self._toggle_btn.grid(row=0, column=1, sticky="e")

        row = 1
        if mode == "translation":
            ctk.CTkLabel(self, text=section.get("text", ""),
                         text_color="#888", font=ctk.CTkFont(size=10),
                         anchor="w", justify="left", wraplength=560,
                         ).grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 4))
            row += 1

        text = section.get(self._field, "") or ""
        self._box = ctk.CTkTextbox(self, height=_autosize(text) * 18, wrap="word")
        self._box.grid(row=row, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._box.insert("1.0", text)

        self._update_visual()

    def _toggle_removed(self) -> None:
        self._section["removed"] = not self._section.get("removed", False)
        self._update_visual()
        if self._on_toggle:
            self._on_toggle()

    def _update_visual(self) -> None:
        removed = self._section.get("removed", False)
        if removed:
            self._toggle_btn.configure(text="↺", fg_color="#1f3a1f", hover_color="#2a5c2a")
            self._tag_lbl.configure(text="Sezione rimossa — esclusa, lasciata come nell'originale")
            self._box.configure(state="disabled", text_color="#666")
            self.configure(fg_color=("#1a1a1a", "#1a1a1a"))
        else:
            self._toggle_btn.configure(text="✕", fg_color="#3a1f1f", hover_color="#5c2a2a")
            self._tag_lbl.configure(text="")
            self._box.configure(state="normal", text_color=("white", "white"))
            self.configure(fg_color=("#222", "#222"))

    def commit(self) -> None:
        """Write the (possibly edited) textbox content back into the section
        dict. Skipped for removed sections — their text is never used."""
        if not self._section.get("removed", False):
            self._section[self._field] = self._box.get("1.0", "end-1c")


class SectionReviewDialog(ctk.CTkToplevel):
    """One-PDF-page-at-a-time review of every extracted/translated section.
    Calls on_done(confirmed: bool) once the user continues or cancels; edits
    are written back into the original section dicts in place."""

    def __init__(self, parent, sections: list[dict], *, mode: str,
                 title: str, intro: str, on_done: Callable[[bool], None]):
        super().__init__(parent)
        self._sections = sections
        self._mode     = mode
        self._on_done  = on_done
        self._cards: list[_SectionCard] = []

        # Group by PDF page, preserving the order sections were extracted in
        # (already page-ascending). Pages with no extractable text never
        # produced a section in the first place, so they're simply absent —
        # nothing to review there.
        self._pages: list[tuple[int, list[dict]]] = []
        by_page: dict[int, list[dict]] = {}
        for s in sections:
            by_page.setdefault(s.get("page", 0), []).append(s)
        self._pages = sorted(by_page.items())
        self._page_pos = 0  # index into self._pages, not the PDF page number

        self.title(title)
        self.geometry("680x600")
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Left>", lambda _e: self._go(-1))
        self.bind("<Right>", lambda _e: self._go(1))

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"),
                     ).pack(pady=(14, 2))
        ctk.CTkLabel(self, text=intro, text_color="#888", font=ctk.CTkFont(size=11),
                     justify="center", wraplength=620).pack(pady=(0, 10), padx=16)

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=16, pady=(0, 4))
        self._prev_btn = ctk.CTkButton(nav, text="◀ Pagina precedente", width=160,
                                        height=28, command=lambda: self._go(-1))
        self._prev_btn.pack(side="left")
        self._page_lbl = ctk.CTkLabel(nav, text="", font=ctk.CTkFont(size=12, weight="bold"))
        self._page_lbl.pack(side="left", expand=True)
        self._next_btn = ctk.CTkButton(nav, text="Pagina successiva ▶", width=160,
                                        height=28, command=lambda: self._go(1))
        self._next_btn.pack(side="right")

        self._content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=16)

        Separator(self).pack(fill="x", padx=16, pady=(8, 0))

        self._summary = ctk.CTkLabel(self, text="", text_color="#888",
                                      font=ctk.CTkFont(size=10))
        self._summary.pack(pady=(6, 0))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(bottom, text="Annulla traduzione", height=34, width=140,
                      fg_color="#333", command=self._cancel).pack(side="right")
        ctk.CTkButton(bottom, text="Continua", height=34, width=120,
                      command=self._confirm).pack(side="right", padx=(0, 8))

        self._render_page()

    # ── Page rendering ───────────────────────────────────────────────────────

    def _render_page(self) -> None:
        for w in self._content.winfo_children():
            w.destroy()
        self._cards = []

        if not self._pages:
            ctk.CTkLabel(self._content, text="Nessuna sezione di testo trovata.",
                         text_color="#888").pack(pady=20)
            self._page_lbl.configure(text="—")
            self._prev_btn.configure(state="disabled")
            self._next_btn.configure(state="disabled")
            self._refresh_summary()
            return

        pdf_page, sections = self._pages[self._page_pos]
        self._page_lbl.configure(
            text=f"Pagina {pdf_page + 1} del PDF "
                 f"({self._page_pos + 1}/{len(self._pages)} con testo)")
        self._prev_btn.configure(state="normal" if self._page_pos > 0 else "disabled")
        self._next_btn.configure(
            state="normal" if self._page_pos < len(self._pages) - 1 else "disabled")

        for section in sections:
            card = _SectionCard(self._content, section, mode=self._mode,
                                 on_toggle=self._refresh_summary)
            card.pack(fill="x", pady=3)
            self._cards.append(card)

        self._refresh_summary()

    def _go(self, delta: int) -> None:
        if not self._pages:
            return
        for card in self._cards:
            card.commit()
        new_pos = self._page_pos + delta
        if 0 <= new_pos < len(self._pages):
            self._page_pos = new_pos
            self._render_page()

    def _refresh_summary(self) -> None:
        removed_count = sum(1 for s in self._sections if s.get("removed"))
        self._summary.configure(
            text=f"{len(self._sections)} sezioni totali — {removed_count} rimosse")

    # ── Confirm / cancel ─────────────────────────────────────────────────────

    def _confirm(self) -> None:
        for card in self._cards:
            card.commit()
        self.grab_release()
        self.destroy()
        self._on_done(True)

    def _cancel(self) -> None:
        self.grab_release()
        self.destroy()
        self._on_done(False)
