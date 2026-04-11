"""
EditorCanvas — interactive tkinter Canvas for visual PDF editing.

Three interaction modes (set via .set_mode()):

  "snip"  — Click + drag to draw a rubber-band selection.
             On release: the selected region is lifted off the page as a
             movable Snippet (original area filled white).

  "drag"  — Click on any Snippet and drag it to a new position.

  "space" — Click and drag vertically anywhere on the page.
             Dragging DOWN inserts white space at that Y position
             (content below moves down).
             Dragging UP removes space (content below moves up).

The canvas displays:
  • The page background (base + erases + space shifts) as a PhotoImage.
  • Each Snippet as a separate PhotoImage overlay (so moving them is fast).
  • Mode-specific overlays: rubber-band rect, space guide line + arrow.

Coordinate systems:
  • "canvas coords"  — screen pixels inside the tk.Canvas widget (affected
                       by scroll offset).
  • "page coords"    — pixels in the rendered page image (DPI 150).
  Conversion: page_x = canvas_x / zoom,  canvas_x = page_x * zoom
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from core.pdf_editor_engine import PageState, Snippet


# ── Colours ────────────────────────────────────────────────────────────────────

_CLR_RB     = "#0078d4"   # rubber-band / snippet border
_CLR_SPACE  = "#e74c3c"   # space-insert guide
_CLR_BG     = "#404040"   # canvas background (outside page)
_CLR_SHADOW = "#00000055" # snippet drop-shadow (unused for simplicity)


class EditorCanvas(tk.Frame):
    """
    Scrollable editing surface.

    Usage:
        canvas = EditorCanvas(parent, on_change=callback)
        canvas.load_state(page_state, zoom=1.0)
        canvas.set_mode("snip")   # or "drag" / "space"
    """

    def __init__(self, parent,
                 on_change: Callable | None = None,
                 **kw):
        kw.setdefault("bg", _CLR_BG)
        super().__init__(parent, **kw)
        self._on_change = on_change or (lambda: None)

        self._mode:  str         = "snip"
        self._zoom:  float       = 1.0
        self._state: PageState | None = None

        # Canvas items: page background
        self._page_item:  int | None    = None
        self._page_photo: ImageTk.PhotoImage | None = None

        # Snippet canvas items: list of [item_id, border_id, PhotoImage, Snippet]
        self._snip_items: list[list] = []

        # Interaction state
        self._press_cx    = 0   # canvas coords at mouse press
        self._press_cy    = 0
        self._rb_item:    int | None = None   # rubber-band rect
        self._drag_info:  tuple | None = None
        self._space_items: list[int] = []

        # Pending snip: set after rubber-band, cleared after choice
        self._pending_sel: tuple[int,int,int,int] | None = None  # page coords
        self._choice_win:  int | None = None   # canvas window item id

        self._build()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._cv = tk.Canvas(self, bg=_CLR_BG, highlightthickness=0,
                              cursor="crosshair")
        vsb = tk.Scrollbar(self, orient="vertical",   command=self._cv.yview)
        hsb = tk.Scrollbar(self, orient="horizontal", command=self._cv.xview)
        self._cv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._cv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._cv.bind("<ButtonPress-1>",   self._on_press)
        self._cv.bind("<B1-Motion>",       self._on_drag_)
        self._cv.bind("<ButtonRelease-1>", self._on_release)
        self._cv.bind("<MouseWheel>",
                      lambda e: self._cv.yview_scroll(
                          -1 if e.delta > 0 else 1, "units"))
        # Middle-click scroll (Linux)
        self._cv.bind("<Button-4>", lambda _: self._cv.yview_scroll(-1, "units"))
        self._cv.bind("<Button-5>", lambda _: self._cv.yview_scroll( 1, "units"))

    # ── Public API ─────────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """Switch between 'snip', 'drag', 'space'."""
        self._mode = mode
        cursors = {"snip": "crosshair", "drag": "fleur",
                   "space": "sb_v_double_arrow"}
        self._cv.configure(cursor=cursors.get(mode, "crosshair"))

    def load_state(self, state: PageState, zoom: float | None = None) -> None:
        """Display a new PageState (call after open or page change)."""
        self._state = state
        if zoom is not None:
            self._zoom = zoom
        self._full_render()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        if self._state:
            self._full_render()

    def refresh(self) -> None:
        """Re-render everything (call after external state change)."""
        if self._state:
            self._full_render()

    def undo(self) -> None:
        if self._state and self._state.undo():
            self._full_render()
            self._on_change()

    # ── Rendering ──────────────────────────────────────────────────────────

    def _full_render(self) -> None:
        """Render page background + all snippet overlays."""
        self._render_bg()
        self._render_snippets()

    def _render_bg(self) -> None:
        if not self._state:
            return
        bg   = self._state.background()
        w    = int(bg.width  * self._zoom)
        h    = int(bg.height * self._zoom)
        img  = bg.resize((w, h), Image.LANCZOS)
        self._page_photo = ImageTk.PhotoImage(img)

        if self._page_item is None:
            self._page_item = self._cv.create_image(
                0, 0, anchor="nw", image=self._page_photo, tags="page")
        else:
            self._cv.itemconfigure(self._page_item, image=self._page_photo)

        self._cv.configure(scrollregion=(0, 0, w, h))
        self._cv.tag_lower("page")

    def _render_snippets(self) -> None:
        for row in self._snip_items:
            self._cv.delete(row[0])   # image item
            self._cv.delete(row[1])   # border rect
        self._snip_items.clear()

        if not self._state:
            return

        for snip in self._state.snippets:
            self._add_snip_item(snip)

    def _add_snip_item(self, snip: Snippet) -> None:
        sw = max(1, int(snip.w * self._zoom))
        sh = max(1, int(snip.h * self._zoom))
        photo = ImageTk.PhotoImage(snip.image.resize((sw, sh), Image.LANCZOS))
        cx    = int(snip.x * self._zoom)
        cy    = int(snip.y * self._zoom)

        img_id = self._cv.create_image(cx, cy, anchor="nw",
                                        image=photo, tags="snippet")
        brd_id = self._cv.create_rectangle(
            cx, cy, cx + sw, cy + sh,
            outline=_CLR_RB, width=1, dash=(4, 2), tags="snip_border")
        self._snip_items.append([img_id, brd_id, photo, snip])

    def _update_snip_item(self, row: list, snip: Snippet) -> None:
        cx = int(snip.x * self._zoom)
        cy = int(snip.y * self._zoom)
        sw = max(1, int(snip.w * self._zoom))
        sh = max(1, int(snip.h * self._zoom))
        self._cv.coords(row[0], cx, cy)
        self._cv.coords(row[1], cx, cy, cx + sw, cy + sh)

    # ── Coordinate helpers ─────────────────────────────────────────────────

    def _c2p(self, cx: float, cy: float) -> tuple[int, int]:
        """Canvas → page pixel (accounting for scroll)."""
        return (int(self._cv.canvasx(cx) / self._zoom),
                int(self._cv.canvasy(cy) / self._zoom))

    def _cx(self, x: float) -> float:
        return self._cv.canvasx(x)

    def _cy(self, y: float) -> float:
        return self._cv.canvasy(y)

    # ── Snippet hit-test ───────────────────────────────────────────────────

    def _snip_at(self, px: int, py: int):
        """Return (row, Snippet) for the topmost snippet at page coords."""
        for row in reversed(self._snip_items):
            if row[3].hit(px, py):
                return row, row[3]
        return None, None

    # ── Mouse: PRESS ───────────────────────────────────────────────────────

    def _on_press(self, event):
        # Cancel any pending choice panel before starting a new action
        self._cancel_choice()

        self._press_cx = event.x
        self._press_cy = event.y
        px, py = self._c2p(event.x, event.y)

        if self._mode == "snip":
            acx, acy = self._cx(event.x), self._cy(event.y)
            self._rb_item = self._cv.create_rectangle(
                acx, acy, acx, acy,
                outline=_CLR_RB, width=2, dash=(4, 4), tags="rb")

        elif self._mode == "drag":
            row, snip = self._snip_at(px, py)
            if snip:
                off_px = px - snip.x
                off_py = py - snip.y
                self._drag_info = (row[0], row[1], row, snip, off_px, off_py)
                self._cv.tag_raise(row[0])
                self._cv.tag_raise(row[1])

        elif self._mode == "space":
            acy  = self._cy(event.y)
            pw   = (self._state.size[0] * self._zoom) if self._state else 800
            line = self._cv.create_line(
                0, acy, pw, acy,
                fill=_CLR_SPACE, width=2, dash=(6, 3), tags="space_guide")
            self._space_items = [line]

    # ── Mouse: DRAG ────────────────────────────────────────────────────────

    def _on_drag_(self, event):
        acx = self._cx(event.x)
        acy = self._cy(event.y)
        p_cx = self._cx(self._press_cx)
        p_cy = self._cy(self._press_cy)

        if self._mode == "snip" and self._rb_item:
            self._cv.coords(self._rb_item, p_cx, p_cy, acx, acy)

        elif self._mode == "drag" and self._drag_info:
            _, _, row, snip, off_px, off_py = self._drag_info
            px, py = self._c2p(event.x, event.y)
            snip.x = max(0, px - off_px)
            snip.y = max(0, py - off_py)
            self._update_snip_item(row, snip)

        elif self._mode == "space" and self._space_items:
            # Clean previous guide overlay
            for item in self._space_items[1:]:
                self._cv.delete(item)
            self._space_items = self._space_items[:1]

            pw     = (self._state.size[0] * self._zoom) if self._state else 800
            amount = int((event.y - self._press_cy) / self._zoom)
            mid_x  = pw / 2

            # Arrow from press line to current y
            arrow = self._cv.create_line(
                mid_x, p_cy, mid_x, acy,
                fill=_CLR_SPACE, width=2,
                arrow=tk.LAST, arrowshape=(10, 12, 4),
                tags="space_guide")
            sign   = "+" if amount >= 0 else ""
            label  = self._cv.create_text(
                mid_x + 16, (p_cy + acy) / 2,
                text=f"{sign}{amount} px",
                fill=_CLR_SPACE, anchor="w",
                font=("Arial", 11, "bold"), tags="space_guide")
            self._space_items += [arrow, label]

    # ── Mouse: RELEASE ─────────────────────────────────────────────────────

    def _on_release(self, event):
        px, py   = self._c2p(event.x, event.y)
        ppx, ppy = self._c2p(self._press_cx, self._press_cy)

        # ── Snip ──────────────────────────────────────────────────────────
        if self._mode == "snip" and self._rb_item:
            x0, x1 = sorted((ppx, px))
            y0, y1 = sorted((ppy, py))
            if x1 - x0 < 4 or y1 - y0 < 4:
                # Too small — cancel
                self._cv.delete(self._rb_item)
                self._rb_item = None
            else:
                # Keep the rubber-band visible and show choice panel
                self._pending_sel = (x0, y0, x1, y1)
                self._show_choice_panel(event.x, event.y)

        # ── Drag ──────────────────────────────────────────────────────────
        elif self._mode == "drag" and self._drag_info:
            self._drag_info = None
            self._on_change()

        # ── Space ─────────────────────────────────────────────────────────
        elif self._mode == "space" and self._space_items:
            for item in self._space_items:
                self._cv.delete(item)
            self._space_items = []
            amount = int((event.y - self._press_cy) / self._zoom)
            if self._state and abs(amount) > 2:
                self._state.insert_space(ppy, amount)
                self._full_render()
                self._on_change()

    # ── Choice panel (Ritaglia / Copia) ────────────────────────────────────

    def _show_choice_panel(self, mouse_x: int, mouse_y: int) -> None:
        """Show a floating panel near the selection asking Ritaglia or Copia."""
        if not self._pending_sel:
            return

        frame = tk.Frame(self._cv, bg="#1e1e1e", relief="solid", bd=1)

        # ── Ritaglia button ───────────────────────────────────────────────
        tk.Button(
            frame,
            text="✂  Ritaglia",
            command=self._do_cut,
            bg="#1f5a8a", fg="white", activebackground="#174a72",
            activeforeground="white", relief="flat",
            font=("Arial", 11, "bold"), padx=14, pady=7,
            cursor="hand2", bd=0,
        ).pack(side="left", padx=(6, 2), pady=6)

        # ── Separator ─────────────────────────────────────────────────────
        tk.Frame(frame, width=1, bg="#444").pack(
            side="left", fill="y", pady=6)

        # ── Copia button ──────────────────────────────────────────────────
        tk.Button(
            frame,
            text="⎘  Copia",
            command=self._do_copy,
            bg="#1f6a3a", fg="white", activebackground="#175530",
            activeforeground="white", relief="flat",
            font=("Arial", 11, "bold"), padx=14, pady=7,
            cursor="hand2", bd=0,
        ).pack(side="left", padx=(2, 2), pady=6)

        # ── Separator ─────────────────────────────────────────────────────
        tk.Frame(frame, width=1, bg="#444").pack(
            side="left", fill="y", pady=6)

        # ── Cancel button ─────────────────────────────────────────────────
        tk.Button(
            frame,
            text="✕",
            command=self._cancel_choice,
            bg="#3a1f1f", fg="white", activebackground="#2a1515",
            activeforeground="white", relief="flat",
            font=("Arial", 11), padx=10, pady=7,
            cursor="hand2", bd=0,
        ).pack(side="left", padx=(2, 6), pady=6)

        # Place panel just below the bottom-right corner of the selection
        x0, y0, x1, y1 = self._pending_sel
        panel_cx = int(x0 * self._zoom)          # left-align with selection
        panel_cy = int(y1 * self._zoom) + 6      # just below selection

        self._choice_win = self._cv.create_window(
            panel_cx, panel_cy, anchor="nw",
            window=frame, tags="choice_panel")

    def _do_cut(self) -> None:
        """User chose Ritaglia — erase source."""
        sel = self._pending_sel
        self._dismiss_choice()
        if sel and self._state:
            snip = self._state.snip(*sel)
            if snip:
                self._render_bg()
                self._add_snip_item(snip)
                self._on_change()

    def _do_copy(self) -> None:
        """User chose Copia — keep source intact."""
        sel = self._pending_sel
        self._dismiss_choice()
        if sel and self._state:
            snip = self._state.copy(*sel)
            if snip:
                self._add_snip_item(snip)
                self._on_change()

    def _dismiss_choice(self) -> None:
        """Remove choice panel and rubber-band (after a decision was made)."""
        if self._choice_win is not None:
            self._cv.delete(self._choice_win)
            self._choice_win = None
        if self._rb_item is not None:
            self._cv.delete(self._rb_item)
            self._rb_item = None
        self._pending_sel = None

    def _cancel_choice(self) -> None:
        """Remove choice panel and rubber-band without performing any action."""
        self._dismiss_choice()
