"""
PDF Editor Engine — raster-based visual editing, zero UI dependencies.

Workflow:
  1. PdfEditorEngine.open(path)  → renders each page via pymupdf at 150 DPI
  2. engine.get_state(page_num)  → returns a PageState (lazy, on first access)
  3. PageState.snip(x0,y0,x1,y1) → cuts region, fills with white, returns Snippet
  4. PageState.insert_space(y, amount) → pushes content above/below
  5. Snippet.x / Snippet.y        → move freely (editor canvas updates these)
  6. engine.export(output)        → composites all edits → new PDF

All coordinates are in page-pixel space (at DPI=150).
The canvas layer is responsible for zoom conversion.
"""

from __future__ import annotations

import copy
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw


# ── Primitives ─────────────────────────────────────────────────────────────────

@dataclass
class Snippet:
    """A movable image block extracted from a page."""
    image: Image.Image
    x:     int   # current position in page pixels
    y:     int

    @property
    def w(self) -> int: return self.image.width
    @property
    def h(self) -> int: return self.image.height

    def hit(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def clone(self) -> "Snippet":
        return Snippet(image=self.image.copy(), x=self.x, y=self.y)


# ── Page state ─────────────────────────────────────────────────────────────────

class PageState:
    """
    Editing state for one PDF page.

    Internal representation:
      _bg       — the "background" PIL image that accumulates all erases and
                  space insertions.  Snippets are NOT baked into _bg; they
                  are overlaid at render time so they remain freely movable.
      snippets  — list of Snippet objects (drawn on top of _bg at compose time)
      _undo     — stack of (bg_copy, snippets_copy) for up to MAX_UNDO steps
    """

    MAX_UNDO = 30

    def __init__(self, base: Image.Image):
        self._bg      = base.convert("RGB")
        self.snippets: list[Snippet] = []
        self._undo:    list[tuple[bytes, list[Snippet]]] = []

    # ── Compose ───────────────────────────────────────────────────────────

    def compose(self) -> Image.Image:
        """Return the flattened page image (background + all snippets)."""
        result = self._bg.copy()
        for snip in self.snippets:
            # Clip to page bounds
            px, py = max(0, snip.x), max(0, snip.y)
            crop   = snip.image
            if px != snip.x or py != snip.y:
                dx = px - snip.x
                dy = py - snip.y
                crop = crop.crop((dx, dy, crop.width, crop.height))
            result.paste(crop, (px, py))
        return result

    def background(self) -> Image.Image:
        """Background without snippets (used for canvas base layer)."""
        return self._bg.copy()

    # ── Edit operations ───────────────────────────────────────────────────

    def snip(self, x0: int, y0: int, x1: int, y1: int) -> Snippet | None:
        """
        Crop [x0,y0 → x1,y1] from the current composed view,
        erase that area (fill white) on _bg, return a new Snippet.
        """
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None

        self._push_undo()

        # Crop from fully composed image so we capture existing snippets too
        region = self.compose().crop((x0, y0, x1, y1))
        snip   = Snippet(image=region.copy(), x=x0, y=y0)
        self.snippets.append(snip)

        # Erase source area on background
        d = ImageDraw.Draw(self._bg)
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(255, 255, 255))

        return snip

    def copy(self, x0: int, y0: int, x1: int, y1: int) -> Snippet | None:
        """
        Duplicate [x0,y0 → x1,y1] without erasing the source.
        Returns a new Snippet placed on top of the original area.
        """
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None

        self._push_undo()

        region = self.compose().crop((x0, y0, x1, y1))
        snip   = Snippet(image=region.copy(), x=x0, y=y0)
        self.snippets.append(snip)
        # Source area is NOT erased — original stays visible underneath
        return snip

    def insert_space(self, y: int, amount: int) -> None:
        """
        Insert (amount > 0) or remove (amount < 0) horizontal whitespace
        at page-pixel row y.  Adjusts snippet positions accordingly.
        """
        if amount == 0:
            return
        self._push_undo()
        self._bg = _shift_image(self._bg, y, amount)
        # Shift snippets that are entirely below the insertion point
        for snip in self.snippets:
            if snip.y >= y:
                snip.y = max(0, snip.y + amount)

    def undo(self) -> bool:
        if not self._undo:
            return False
        bg_bytes, snips = self._undo.pop()
        self._bg        = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
        self.snippets   = snips
        return True

    # ── Internal ──────────────────────────────────────────────────────────

    def _push_undo(self):
        if len(self._undo) >= self.MAX_UNDO:
            self._undo.pop(0)
        snips_copy = [s.clone() for s in self.snippets]
        # Compress to PNG bytes: ~5–15× smaller than raw pixels in RAM
        # (a 150 DPI A4 page: ~5.6 MB raw → ~300–600 KB compressed)
        buf = io.BytesIO()
        self._bg.save(buf, format="PNG", optimize=True, compress_level=6)
        self._undo.append((buf.getvalue(), snips_copy))

    @property
    def size(self) -> tuple[int, int]:
        return self._bg.size   # (width, height) in page pixels


# ── Space helper ───────────────────────────────────────────────────────────────

def _shift_image(img: Image.Image, y: int, amount: int) -> Image.Image:
    """Insert or remove `amount` pixels of white space at row y."""
    w, h = img.size
    y     = max(0, min(y, h))

    if amount >= 0:
        new_h = h + amount
        out   = Image.new("RGB", (w, new_h), (255, 255, 255))
        out.paste(img.crop((0,  0, w,  y)), (0, 0))
        out.paste(img.crop((0,  y, w,  h)), (0, y + amount))
    else:
        remove = min(-amount, h - y)
        new_h  = max(h - remove, 1)
        out    = Image.new("RGB", (w, new_h), (255, 255, 255))
        out.paste(img.crop((0, 0, w, y)), (0, 0))
        if y + remove < h:
            out.paste(img.crop((0, y + remove, w, h)), (0, y))
    return out


# ── Engine ─────────────────────────────────────────────────────────────────────

class PdfEditorEngine:
    """
    Opens a PDF, manages per-page editing states, and exports the result.

    Required dependency: pymupdf  (pip install pymupdf)
    """

    DPI = 150   # render resolution — good quality/speed balance

    def __init__(self):
        self._doc    = None
        self._states: list[PageState | None] = []
        self._path:   Path | None = None

    # ── Open / close ──────────────────────────────────────────────────────

    def open(self, path: Path) -> int:
        """Open a PDF file. Returns the page count."""
        import fitz  # pymupdf
        if self._doc:
            self._doc.close()
        self._path   = path
        self._doc    = fitz.open(str(path))
        self._states = [None] * len(self._doc)
        return len(self._doc)

    def close(self):
        if self._doc:
            self._doc.close()
            self._doc = None

    # ── Page access ───────────────────────────────────────────────────────

    def get_state(self, page_num: int) -> PageState:
        """Return (lazy-created) editing state for a page."""
        if self._states[page_num] is None:
            self._states[page_num] = PageState(self._render_page(page_num))
        return self._states[page_num]

    def _render_page(self, page_num: int) -> Image.Image:
        import fitz
        mat = fitz.Matrix(self.DPI / 72, self.DPI / 72)
        pix = self._doc[page_num].get_pixmap(matrix=mat, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    # ── Export ────────────────────────────────────────────────────────────

    def export(self, output: Path,
               progress_cb: Callable[[float], None] | None = None) -> None:
        """
        Compose all edits and write a new PDF.
        Uses reportlab to assemble pages from composed PIL images.
        """
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.utils import ImageReader

        n = len(self._doc) if self._doc else 0
        c = rl_canvas.Canvas(str(output))

        for i in range(n):
            state = self._states[i]
            img   = state.compose() if state else self._render_page(i)
            w, h  = img.size

            c.setPageSize((w, h))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            buf.seek(0)
            c.drawImage(ImageReader(buf), 0, 0, w, h)
            c.showPage()

            if progress_cb:
                progress_cb((i + 1) / n)

        c.save()

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def page_count(self) -> int:
        return len(self._doc) if self._doc else 0
