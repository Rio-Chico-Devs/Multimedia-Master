"""
PDF Translator Engine — translates a PDF in place: same layout, same page,
only the text is replaced.

Pipeline, exposed as three independent stages so a caller can pause between
them for manual review (see ui/translate_review_dialog.py) instead of always
running start-to-finish:

  1. extract_sections() — read text lines with their position/size/font via
     pymupdf's structured text dict. If a page has no extractable text (a
     scanned page), fall back to OCR (RapidOCR, see common/ocr_engine.py) to
     recover line text + position instead. Lines are grouped into paragraphs
     (see _group_into_paragraphs) — translating single wrapped lines in
     isolation starves the MT model of sentence context and reads like
     literal word substitution instead of a real translation.
  2. translate_sections() — translate each paragraph's text as one chunk.
     A caller may edit/remove paragraphs (drop unwanted ones, fix garbled
     OCR text) between stage 1 and this one.
  3. apply_translation() — redact the original line rectangles (pymupdf
     "burns" them out — works for both vector text and the rendered scan
     underneath) and re-insert the translated paragraph text in the union of
     its lines' rectangles, auto-shrinking the font size until it fits.
     Sections marked "removed" are skipped entirely: the original PDF
     content there is left untouched. A caller may edit the translated text
     between stage 2 and this one.

translate_pdf() composes the three stages for the common case of a single,
uninterrupted run with no manual review.

Pages with no text at all (pure images, diagrams) are left untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common.depmsg import pip_hint
from common.ocr_engine import ocr_available, ocr_image
from .translate_engine import clean_extracted_text, translate_text

_MIN_FONT_SIZE = 5.0
_OCR_DPI       = 200


@dataclass
class PdfResult:
    output:     Path | None
    success:    bool
    cancelled:  bool = False
    page_count: int = 0
    file_size:  int = 0
    error:      str = ""
    warning:    str = ""


@dataclass
class ExtractResult:
    sections:            list[dict]
    page_count:          int
    ocr_needed_missing:  int = 0


def _int_to_rgb(color: int) -> tuple[float, float, float]:
    return ((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255


def _pick_font(orig_font_name: str) -> str:
    """Map an embedded font name to one of pymupdf's built-in base-14 fonts."""
    name = (orig_font_name or "").lower()
    bold   = "bold" in name
    italic = "italic" in name or "oblique" in name
    if "times" in name or "georgia" in name or "serif" in name:
        base = {(False, False): "tiro", (True, False): "tibo",
                (False, True): "tiit", (True, True): "tibi"}
    elif "courier" in name or "consolas" in name or "mono" in name:
        base = {(False, False): "cour", (True, False): "cobo",
                (False, True): "coit", (True, True): "cobi"}
    else:
        base = {(False, False): "helv", (True, False): "hebo",
                (False, True): "heit", (True, True): "hebi"}
    return base[(bold, italic)]


def _insert_autoshrink(page, rect, text: str, base_size: float,
                        color: tuple[float, float, float], fontname: str,
                        rotate: int = 0) -> None:
    size = max(base_size, _MIN_FONT_SIZE)
    while size >= _MIN_FONT_SIZE:
        rc = page.insert_textbox(rect, text, fontsize=size, fontname=fontname,
                                  color=color, align=0, rotate=rotate)
        if rc >= 0:
            return
        size -= 0.5
    page.insert_textbox(rect, text, fontsize=_MIN_FONT_SIZE, fontname=fontname,
                         color=color, align=0, rotate=rotate)


def _digital_text_lines(page) -> list[dict]:
    lines = []
    # pymupdf already segments the page into the author's own text blocks
    # (paragraphs/regions). We keep each line's block index so the paragraph
    # grouping below can refuse to merge lines that the document itself put in
    # different blocks — that boundary is a far stronger "this is a separate
    # section" signal than any geometric guess.
    for bidx, block in enumerate(page.get_text("dict")["blocks"]):
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"]]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            # A line can mix styles (e.g. one bold word); use the span that
            # covers most of the line's characters as the representative
            # font/size/color rather than always the first one.
            dominant = max(spans, key=lambda s: len(s["text"]))
            lines.append({
                "bbox":  line["bbox"],
                "text":  text,
                "size":  dominant["size"],
                "color": dominant["color"],
                "font":  dominant["font"],
                "block": bidx,
            })
    return lines


def _ocr_lines(page):
    import fitz
    from PIL import Image

    zoom = _OCR_DPI / 72
    pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    lines = []
    for r in ocr_image(img):
        x0, y0, x1, y1 = r["bbox"]
        height_pt = (y1 - y0) / zoom
        lines.append({
            "bbox":  (x0 / zoom, y0 / zoom, x1 / zoom, y1 / zoom),
            "text":  r["text"],
            "size":  max(_MIN_FONT_SIZE, height_pt * 0.8),
            "color": 0,
            "font":  "",
            # OCR has no block structure to lean on, so the geometric grouping
            # heuristic is left fully in charge (None never blocks a merge).
            "block": None,
        })
    return lines


def _join_lines(texts: list[str]) -> str:
    """Join wrapped lines back into running text. A trailing hyphen marks a
    word split across the line break ("attach-" + "ments" -> "attachments"),
    so we drop it and glue without a space; otherwise lines join with a space.
    Feeding the MT model whole words instead of hyphenated fragments is a big
    part of getting a real translation instead of leftover source text."""
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if not out:
            out = t
        elif out.endswith("-") and not out.endswith(" -"):
            out = out[:-1] + t
        else:
            out = out + " " + t
    return out


def _projection_gaps(intervals: list[tuple[float, float]], min_gap: float):
    """Largest *interior* gap in a 1-D projection. `intervals` are (start, end)
    spans on one axis; merge them and return the midpoint of the widest empty
    band *between* two merged spans that is at least `min_gap` wide, else None.

    A gap on the x-axis is a full-height blank column (a column gutter); a gap
    on the y-axis is a full-width blank row (the band between a heading and the
    body, or two stacked blocks). Exterior margins never count — only gaps
    between two occupied spans — so a wide page margin can't be mistaken for a
    column boundary."""
    if len(intervals) < 2:
        return None
    ivs = sorted(intervals)
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1]:
            if b > merged[-1][1]:
                merged[-1][1] = b
        else:
            merged.append([a, b])
    best_mid = None
    best_w = min_gap
    for (_, end), (start, _) in zip(merged, merged[1:]):
        w = start - end
        if w > best_w:
            best_w = w
            best_mid = (end + start) / 2.0
    return best_mid


def _layout_regions(lines: list[dict], ref_h: float):
    """Recursive XY-cut (Nagy & Seth) layout analysis. Split a set of lines at
    its widest blank gutter — vertical (columns: left before right) or
    horizontal (stacked bands: top before bottom) — and recurse. A full-width
    heading covers the centre, so it blocks any vertical gutter and is peeled
    off as the top band *before* the body columns are split — which is exactly
    the order a person reads. Returns (regions, had_vertical_cut): regions is a
    reading-ordered list of line-lists; had_vertical_cut says whether a column
    split happened anywhere (so the caller knows the page was multi-column)."""
    if len(lines) <= 1:
        return [lines], False
    # A column gutter must be clearly wider than a word space; a row gutter at
    # least a blank line. Normal line spacing within a paragraph is well below
    # these, so paragraph assembly stays the job of _group_into_paragraphs.
    x_cut = _projection_gaps(
        [(li["bbox"][0], li["bbox"][2]) for li in lines], 1.5 * ref_h)
    y_cut = _projection_gaps(
        [(li["bbox"][1], li["bbox"][3]) for li in lines], 1.2 * ref_h)
    # Prefer the vertical (column) split: it is the structural boundary that,
    # left unhandled, interleaves the columns. Only when no column gutter
    # exists do we fall back to a horizontal band split.
    if x_cut is not None:
        def cx(li):
            return (li["bbox"][0] + li["bbox"][2]) / 2.0
        left = [li for li in lines if cx(li) < x_cut]
        right = [li for li in lines if cx(li) >= x_cut]
        lr, _ = _layout_regions(left, ref_h)
        rr, _ = _layout_regions(right, ref_h)
        return lr + rr, True
    if y_cut is not None:
        def cy(li):
            return (li["bbox"][1] + li["bbox"][3]) / 2.0
        top = [li for li in lines if cy(li) < y_cut]
        bottom = [li for li in lines if cy(li) >= y_cut]
        tr, tv = _layout_regions(top, ref_h)
        br, bv = _layout_regions(bottom, ref_h)
        return tr + br, (tv or bv)
    # Leaf: no significant gutter — order what's left top-to-bottom, left-to-right.
    return [sorted(lines, key=lambda li: (li["bbox"][1], li["bbox"][0]))], False


def _order_multicolumn(lines: list[dict]) -> list[dict]:
    """If the page is multi-column, reorder the lines into human reading order
    and tag each with a region id (written to "block") so paragraph grouping
    won't fuse lines across a column boundary. Single-column pages are returned
    unchanged so the existing, well-tuned path stays in charge there.

    This is the fix for two-column manuals (digital PDFs whose own blocks span
    both columns, and OCR lines which carry no block at all): without it lines
    sort by y across the whole page width, interleaving the columns, which both
    scrambles the reading order and stops paragraphs ever reassembling — every
    line ends up its own fragment and the MT model only ever sees half-sentences."""
    if len(lines) < 2:
        return lines
    heights = sorted(max(li["bbox"][3] - li["bbox"][1], 1.0) for li in lines)
    ref_h = heights[len(heights) // 2]
    regions, had_columns = _layout_regions(lines, ref_h)
    if not had_columns:
        return lines
    ordered: list[dict] = []
    for region_id, region in enumerate(regions):
        for li in region:
            tagged = dict(li)
            tagged["block"] = region_id
            ordered.append(tagged)
    return ordered


def _group_into_paragraphs(lines: list[dict], src: str | None = None) -> list[dict]:
    """
    Merge consecutive lines that visually belong to the same paragraph
    (small vertical gap, similar left edge, similar font size) into one
    chunk, so the MT model sees a full sentence/paragraph instead of an
    isolated wrapped fragment. Each resulting paragraph keeps every original
    line's rect for precise redaction, plus their union for re-inserting the
    translated text.

    The font-size check matters: without it a big heading ("PREPARATION")
    glued to the body line under it would both poison the translation and
    break the paragraph chain, leaving the rest of the body as orphaned
    fragments — which is exactly how scanned pages ended up half-translated.

    `src`, when known, runs the same OCR-glued-word cleanup translate_text()
    applies, but here — before the paragraph is ever shown on the manual-
    review screen, not just before translation. Without this, a two-column
    scanned page survives the reading-order fix only to show the user
    "earnedforyou.Webelieve" instead of "earned for you. We believe".
    """
    if not lines:
        return []

    # Read each block's lines top-to-bottom as a contiguous run. Without the
    # block as the primary sort key, two side-by-side blocks (e.g. columns)
    # would interleave by y and the grouping — which only ever merges
    # consecutive lines — could never rebuild either section. OCR lines all
    # carry block=None, so they fall back to pure geometric (y, x) ordering.
    ordered = sorted(
        lines,
        key=lambda li: (li["bbox"][1], li["bbox"][0]) if li.get("block") is None
        else (li["block"], li["bbox"][1], li["bbox"][0]))

    # A page-wide reference height is far more stable than any single line's
    # box (OCR boxes in particular vary a lot), so thresholds below scale to
    # the document's typical line size rather than a possibly-outlier line.
    heights = sorted(max(li["bbox"][3] - li["bbox"][1], 1.0) for li in ordered)
    ref_h = heights[len(heights) // 2]

    groups: list[list[dict]] = []
    for li in ordered:
        x0, y0, x1, y1 = li["bbox"]
        if groups:
            prev = groups[-1][-1]
            px0, py0, px1, py1 = prev["bbox"]
            vgap        = y0 - py1
            x_shift     = abs(x0 - px0)
            prev_size   = max(prev["size"], 0.1)
            size_ratio  = li["size"] / prev_size
            same_size   = 0.75 <= size_ratio <= 1.33
            # Honour the document's own block boundaries: two lines the PDF put
            # in different blocks are different sections, so never fuse them
            # even if they happen to sit close together (e.g. a caption right
            # under a paragraph). OCR lines carry block=None and skip this gate.
            pb, cb      = prev.get("block"), li.get("block")
            same_block  = pb is None or cb is None or pb == cb
            if (same_block and vgap < 0.8 * ref_h
                    and x_shift < 3.0 * ref_h and same_size):
                groups[-1].append(li)
                continue
        groups.append([li])

    paragraphs = []
    for group in groups:
        x0 = min(g["bbox"][0] for g in group)
        y0 = min(g["bbox"][1] for g in group)
        x1 = max(g["bbox"][2] for g in group)
        y1 = max(g["bbox"][3] for g in group)
        dominant = max(group, key=lambda g: len(g["text"]))
        text = _join_lines([g["text"] for g in group])
        if src is not None:
            text = clean_extracted_text(text, src)
        paragraphs.append({
            "line_rects": [g["bbox"] for g in group],
            "bbox":       (x0, y0, x1, y1),
            "text":       text,
            "size":       dominant["size"],
            "color":      dominant["color"],
            "font":       dominant["font"],
            "removed":    False,
        })
    return paragraphs


def extract_sections(
    input_path:       Path,
    include_scanned:  bool = True,
    src:              str | None = None,
    cancel_event=None,
    progress_cb:      Callable[[float], None] | None = None,
) -> ExtractResult:
    """Read every page's paragraphs without modifying the PDF. Each returned
    section is a dict (see _group_into_paragraphs) plus a "page" index and a
    "removed" flag a caller can flip before translate_sections()/
    apply_translation() to drop a section instead of translating/burning it
    in — the original PDF content there is left exactly as-is.

    `src`, when given, runs the OCR-glued-word cleanup (see
    translate_engine.clean_extracted_text) on each paragraph's text as it's
    built, so a manual-review screen shown right after extraction — before any
    translation — already displays cleaned-up text instead of raw OCR glue."""
    import fitz  # pymupdf

    doc = fitz.open(str(input_path))
    try:
        # Build the OCR engine lazily — only the first time a page turns out to
        # have no digital text. ocr_available() loads three ONNX models (a real
        # cold-start cost), so a fully digital PDF (the common case) must never
        # pay for it just because the "include scanned pages" box is ticked.
        total      = doc.page_count or 1
        ocr_ready   = False
        ocr_checked = False
        sections: list[dict] = []
        ocr_needed_missing = 0

        for i, page in enumerate(doc):
            if cancel_event is not None and cancel_event.is_set():
                break

            lines = _digital_text_lines(page)
            if not lines:
                if include_scanned and not ocr_checked:
                    ocr_ready   = ocr_available()
                    ocr_checked = True
                if ocr_ready:
                    try:
                        lines = _ocr_lines(page)
                    except Exception:
                        # OCR failed on this page — leave it untouched
                        # rather than aborting the whole document.
                        lines = []
                elif include_scanned:
                    ocr_needed_missing += 1

            for p in _group_into_paragraphs(_order_multicolumn(lines), src):
                p["page"] = i
                sections.append(p)

            if progress_cb:
                progress_cb((i + 1) / total)

        return ExtractResult(sections=sections, page_count=doc.page_count,
                              ocr_needed_missing=ocr_needed_missing)
    finally:
        doc.close()


def translate_sections(
    sections:    list[dict],
    src:         str,
    tgt:         str,
    glossary:    dict[str, str] | None = None,
    engine:      str = "argos",
    cancel_event=None,
    progress_cb: Callable[[float], None] | None = None,
) -> tuple[int, int, str]:
    """Translate every section's text in place (adds/overwrites the
    "translated" key). Sections with removed=True are skipped — they carry
    no translation and apply_translation() will leave that PDF area as-is.
    Returns (translated_ok, translate_errors, first_error)."""
    translated_ok    = 0
    translate_errors = 0
    first_error      = ""
    total = len(sections) or 1

    for idx, p in enumerate(sections):
        if cancel_event is not None and cancel_event.is_set():
            break
        if not p.get("removed"):
            # A single paragraph that the MT engine chokes on must not throw
            # away every other one already done — fall back to the source.
            try:
                p["translated"] = translate_text(p["text"], src, tgt, glossary,
                                                  engine=engine)
                translated_ok += 1
            except Exception as exc:
                p["translated"] = p["text"]
                translate_errors += 1
                if not first_error:
                    first_error = str(exc)
        if progress_cb:
            progress_cb((idx + 1) / total)

    return translated_ok, translate_errors, first_error


def apply_translation(
    input_path:   Path,
    output_path:  Path,
    sections:     list[dict],
    page_count:   int = 0,
    cancel_event=None,
    progress_cb:  Callable[[float], None] | None = None,
) -> PdfResult:
    """Re-open the original PDF and burn in the (possibly user-edited)
    translated sections, page by page. Sections marked removed=True are
    skipped entirely — neither redacted nor replaced."""
    try:
        import fitz  # pymupdf
    except ImportError:
        return PdfResult(output=output_path, success=False,
                          error=f"pymupdf non disponibile — {pip_hint('pymupdf')}")

    try:
        doc = fitz.open(str(input_path))
    except Exception as exc:
        return PdfResult(output=output_path, success=False, error=str(exc))

    by_page: dict[int, list[dict]] = {}
    for p in sections:
        if not p.get("removed"):
            by_page.setdefault(p["page"], []).append(p)

    total = (page_count or doc.page_count) or 1
    pages_done = 0
    try:
        for i, page in enumerate(doc):
            if cancel_event is not None and cancel_event.is_set():
                break

            paragraphs = by_page.get(i, [])
            if paragraphs:
                # Page rotation handling: get_text()/get_pixmap() report boxes
                # in the *displayed* (rotated) coordinate system, but
                # add_redact_annot()/insert_textbox() operate in the page's
                # *unrotated* base system. derotation_matrix is the identity
                # on an unrotated page, so this is a no-op for the common case.
                derot = page.derotation_matrix
                rot   = page.rotation
                for p in paragraphs:
                    p["rect"] = fitz.Rect(p["bbox"]) * derot

                # apply_redactions() unconditionally drops every link
                # overlapping a redacted rect (pymupdf docs/wiki) — a text
                # line under a hyperlink is the common case (URLs, mailto:,
                # page jumps), so without this the translated PDF would
                # silently lose all its links. Capture and recreate them
                # across the redaction.
                links = page.get_links()
                for p in paragraphs:
                    for rect in p["line_rects"]:
                        page.add_redact_annot(fitz.Rect(rect) * derot, fill=(1, 1, 1))
                page.apply_redactions()
                for link in links:
                    # The xref refers to the link object apply_redactions()
                    # just destroyed — insert_link() must create a new
                    # object, not be pointed at the dead one.
                    link.pop("xref", None)
                    page.insert_link(link)
                for p in paragraphs:
                    _insert_autoshrink(
                        page, p["rect"], p.get("translated", p["text"]),
                        base_size=p["size"], color=_int_to_rgb(p["color"]),
                        fontname=_pick_font(p["font"]), rotate=rot)

            pages_done = i + 1
            if progress_cb:
                progress_cb(pages_done / total)

        cancelled = cancel_event is not None and cancel_event.is_set()
        doc.save(str(output_path))
        doc.close()
        return PdfResult(output=output_path, success=True, cancelled=cancelled,
                          page_count=pages_done, file_size=output_path.stat().st_size)
    except Exception as exc:
        # Best-effort: keep whatever pages were already translated instead
        # of discarding the whole job on one fatal error.
        try:
            doc.save(str(output_path))
        except Exception:
            pass
        doc.close()
        return PdfResult(output=output_path, success=False,
                          page_count=pages_done, error=str(exc))


class PdfTranslatorEngine:
    """Translates a PDF's text in place, preserving the original layout."""

    def translate_pdf(
        self,
        input_path:      Path,
        output_path:     Path,
        src:              str,
        tgt:              str,
        include_scanned:  bool = True,
        glossary:         dict[str, str] | None = None,
        engine:           str = "argos",
        progress_cb:      Callable[[float], None] | None = None,
        cancel_event=None,
    ) -> PdfResult:
        """Run extraction, translation and PDF rewriting back-to-back with no
        pause for manual review — the direct, one-click path."""
        try:
            import fitz  # noqa: F401  (surface the dependency error up front)
        except ImportError:
            return PdfResult(output=output_path, success=False,
                              error=f"pymupdf non disponibile — {pip_hint('pymupdf')}")

        def _scaled(lo: float, hi: float):
            if not progress_cb:
                return None
            return lambda f: progress_cb(lo + f * (hi - lo))

        try:
            extracted = extract_sections(
                input_path, include_scanned=include_scanned, src=src,
                cancel_event=cancel_event, progress_cb=_scaled(0.0, 0.4))
        except Exception as exc:
            return PdfResult(output=output_path, success=False, error=str(exc))

        cancelled = cancel_event is not None and cancel_event.is_set()
        translated_ok = translate_errors = 0
        first_error = ""
        if not cancelled:
            translated_ok, translate_errors, first_error = translate_sections(
                extracted.sections, src, tgt, glossary, engine=engine,
                cancel_event=cancel_event, progress_cb=_scaled(0.4, 0.8))
            cancelled = cancel_event is not None and cancel_event.is_set()

        if cancelled:
            # A section the run never reached has no "translated" value; leave
            # its original content in place rather than redacting and redrawing
            # it with the untranslated source text.
            for s in extracted.sections:
                if "translated" not in s:
                    s["removed"] = True

        if not cancelled and translated_ok == 0:
            # Nothing was translated anywhere in the document — figure out
            # why and report it instead of pretending the job succeeded.
            if extracted.ocr_needed_missing > 0 and translate_errors == 0:
                return PdfResult(
                    output=output_path, success=False, page_count=extracted.page_count,
                    error=(f"Il PDF sembra scansionato (nessun testo "
                           f"digitale) e l'OCR non è disponibile: "
                           f"installa il motore OCR "
                           f"({pip_hint('rapidocr_onnxruntime')}), poi riprova. "
                           f"{extracted.ocr_needed_missing} pagina/e coinvolta/e."))
            if translate_errors > 0:
                # Every line failed to translate → the output would be an
                # unchanged copy of the source (the common case: the chosen
                # language pair was never downloaded, or its model can't be
                # loaded at runtime).
                return PdfResult(
                    output=output_path, success=False, page_count=extracted.page_count,
                    error=(f"Nessuna riga è stata tradotta: la coppia di "
                           f"lingue {src}→{tgt} non risulta utilizzabile. "
                           f"Apri 'Gestisci lingue' e scarica/reinstalla la "
                           f"coppia. Dettaglio tecnico: {first_error}"))
            return PdfResult(
                output=output_path, success=False, page_count=extracted.page_count,
                error="Nessun testo trovato nel PDF: nessuna pagina conteneva "
                      "testo da tradurre.")

        result = apply_translation(
            input_path, output_path, extracted.sections, extracted.page_count,
            # On cancel we still want the work already done to survive — the
            # old per-page pipeline left finished pages translated. Skip the
            # sections that never got a translation (leave the original there)
            # and let the write run to completion rather than aborting it.
            cancel_event=None if cancelled else cancel_event,
            progress_cb=_scaled(0.8, 1.0))
        if cancelled:
            result.cancelled = True
        if result.success and extracted.ocr_needed_missing > 0:
            result.warning = (f"{extracted.ocr_needed_missing} pagina/e scansionata/e "
                               f"ignorata/e: installa il motore OCR per tradurle "
                               f"({pip_hint('rapidocr_onnxruntime')}).")
        return result
