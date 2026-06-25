"""
Section review dialog — the manual-review step of the PDF translation flow.

Used twice per job (see translate_tab.py):
  1. After extraction, on the *source* text: the user sees every section the
     engine found, can drop ones that are noise/garbled ("✕") or fix the
     source text before it ever reaches the MT engine.
  2. After translation, on the *translated* text: same sections, now editable
     on the translated side, with the original kept alongside as a reference.

Two deliberate performance choices, because real manuals run to hundreds of
pages and thousands of sections:

  * ONE PDF page's sections at a time, with Previous/Next navigation, instead
    of every section in one endless scroll.
  * The section cards are built from plain Tkinter widgets (tk.Frame / tk.Text
    / tk.Label), NOT CustomTkinter ones. A CTkTextbox alone wraps a
    canvas-bordered CTkFrame + a tkinter.Text + CTkScrollbars and redraws
    rounded corners on a canvas; building ~10 such widgets per section made a
    dense page take seconds to appear. Plain Tk widgets are an order of
    magnitude cheaper to instantiate, and the cards are pooled and *reused*
    across page navigation rather than destroyed and rebuilt — so paging
    through a long document stays instant regardless of its size.

Edits are committed back into the section dicts on every navigation, not just
on final confirm, so moving between pages never loses them.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from .widgets import Separator

# Plain-Tk cards can't borrow CustomTkinter's theme engine, so the few colours
# they need are spelled out here to match the rest of the dark UI.
_CARD_BG          = "#222222"
_CARD_BG_REMOVED  = "#1a1a1a"
_TEXT_BG          = "#2b2b2b"
_TEXT_BG_REMOVED  = "#1c1c1c"
_TEXT_FG          = "#ffffff"
_TEXT_FG_REMOVED  = "#666666"
_MUTED_FG         = "#888888"
_BORDER           = "#3a3a3a"


def _autosize(text: str) -> int:
    """Rough line count for a textbox's height, in text lines (tk.Text measures
    height in lines). chars-per-line is a guess tuned for the dialog width; the
    box stays scrollable if the guess is off."""
    chars_per_line = 70
    lines = max(1, -(-len(text) // chars_per_line))  # ceil div
    return min(max(lines, 2), 10)


class _SectionCard(tk.Frame):
    """One editable section, built from cheap native Tk widgets and *reused*
    across pages: construct once, then call bind_section() to point it at a
    different section dict. Holds the section's text (source or translation), an
    optional read-only reference line, and a remove/restore toggle."""

    def __init__(self, parent, *, mode: str,
                 on_toggle: Callable[[], None] | None = None):
        super().__init__(parent, bg=_CARD_BG, bd=0, highlightthickness=0)
        self._mode      = mode
        self._field     = "text" if mode == "source" else "translated"
        self._on_toggle = on_toggle
        self._section: dict | None = None

        self.grid_columnconfigure(0, weight=1)

        self._tag_lbl = tk.Label(self, text="", fg=_MUTED_FG, bg=_CARD_BG,
                                 font=("TkDefaultFont", 9), anchor="w")
        self._tag_lbl.grid(row=0, column=0, sticky="w", padx=10, pady=(6, 0))

        # A clickable label is far cheaper than a CTkButton (no canvas) and is
        # all a one-glyph ✕/↺ toggle needs.
        self._toggle = tk.Label(self, text="✕", fg="#e57373", bg=_CARD_BG,
                                font=("TkDefaultFont", 12, "bold"),
                                cursor="hand2", padx=8)
        self._toggle.grid(row=0, column=1, sticky="e", padx=(0, 8), pady=(6, 0))
        self._toggle.bind("<Button-1>", lambda _e: self._toggle_removed())

        row = 1
        self._ref_lbl: tk.Label | None = None
        if mode == "translation":
            self._ref_lbl = tk.Label(self, text="", fg=_MUTED_FG, bg=_CARD_BG,
                                     font=("TkDefaultFont", 9), anchor="w",
                                     justify="left", wraplength=600)
            self._ref_lbl.grid(row=row, column=0, columnspan=2, sticky="ew",
                               padx=12, pady=(2, 2))
            row += 1

        self._box = tk.Text(self, height=3, wrap="word", bd=0,
                            relief="flat", highlightthickness=1,
                            highlightbackground=_BORDER, highlightcolor=_BORDER,
                            bg=_TEXT_BG, fg=_TEXT_FG, insertbackground=_TEXT_FG,
                            padx=6, pady=4, font=("TkDefaultFont", 11), undo=True)
        self._box.grid(row=row, column=0, columnspan=2, sticky="ew",
                       padx=10, pady=(0, 8))

    # ── reuse ────────────────────────────────────────────────────────────────

    def bind_section(self, section: dict) -> None:
        """Point this (possibly previously-used) card at a new section."""
        self._section = section
        if self._ref_lbl is not None:
            self._ref_lbl.configure(text=section.get("text", ""))
        text = section.get(self._field, "") or ""
        self._box.configure(state="normal", height=_autosize(text))
        self._box.delete("1.0", "end")
        self._box.insert("1.0", text)
        self._update_visual()

    # ── toggle / visuals ──────────────────────────────────────────────────────

    def _toggle_removed(self) -> None:
        if self._section is None:
            return
        self._section["removed"] = not self._section.get("removed", False)
        self._update_visual()
        if self._on_toggle:
            self._on_toggle()

    def _update_visual(self) -> None:
        removed = bool(self._section and self._section.get("removed", False))
        if removed:
            self._toggle.configure(text="↺", fg="#81c784")
            self._tag_lbl.configure(
                text="Sezione rimossa — esclusa, lasciata come nell'originale")
            self._box.configure(state="disabled", bg=_TEXT_BG_REMOVED,
                                fg=_TEXT_FG_REMOVED)
            self._set_bg(_CARD_BG_REMOVED)
        else:
            self._toggle.configure(text="✕", fg="#e57373")
            self._tag_lbl.configure(text="")
            self._box.configure(state="normal", bg=_TEXT_BG, fg=_TEXT_FG)
            self._set_bg(_CARD_BG)

    def _set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self._tag_lbl.configure(bg=color)
        self._toggle.configure(bg=color)
        if self._ref_lbl is not None:
            self._ref_lbl.configure(bg=color)

    # ── commit ─────────────────────────────────────────────────────────────────

    def commit(self) -> None:
        """Write the (possibly edited) textbox content back into the bound
        section dict. Skipped for removed sections — their text is never used."""
        if self._section is not None and not self._section.get("removed", False):
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
        self._pool: list[_SectionCard] = []   # reused across pages
        self._visible = 0                      # cards currently bound/shown

        # Group by PDF page, preserving the order sections were extracted in
        # (already page-ascending). Pages with no extractable text never
        # produced a section in the first place, so they're simply absent —
        # nothing to review there.
        by_page: dict[int, list[dict]] = {}
        for s in sections:
            by_page.setdefault(s.get("page", 0), []).append(s)
        self._pages: list[tuple[int, list[dict]]] = sorted(by_page.items())
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

        self._empty_lbl = ctk.CTkLabel(self._content,
                                       text="Nessuna sezione di testo trovata.",
                                       text_color="#888")

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
        if not self._pages:
            self._empty_lbl.pack(pady=20)
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

        # Grow the pool only as far as the densest page seen so far; cards are
        # bound to new sections and re-shown rather than recreated.
        while len(self._pool) < len(sections):
            card = _SectionCard(self._content, mode=self._mode,
                                on_toggle=self._refresh_summary)
            self._pool.append(card)

        for i, card in enumerate(self._pool):
            if i < len(sections):
                card.bind_section(sections[i])
                card.pack(fill="x", pady=3)
            else:
                card.pack_forget()
        self._visible = len(sections)

        # Back to the top of the new page rather than wherever the last one
        # was scrolled to. Uses CTkScrollableFrame's inner canvas; guarded
        # in case the private attribute ever changes.
        try:
            self._content._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

        self._refresh_summary()

    def _commit_visible(self) -> None:
        for card in self._pool[:self._visible]:
            card.commit()

    def _go(self, delta: int) -> None:
        if not self._pages:
            return
        self._commit_visible()
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
        self._commit_visible()
        self.grab_release()
        self.destroy()
        self._on_done(True)

    def _cancel(self) -> None:
        self.grab_release()
        self.destroy()
        self._on_done(False)
