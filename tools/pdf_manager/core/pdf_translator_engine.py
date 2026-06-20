"""
PDF Translator Engine — translates a PDF in place: same layout, same page,
only the text is replaced.

Pipeline per page:
  1. Read text lines with their position/size/font via pymupdf's structured
     text dict. If a page has no extractable text (a scanned page), fall
     back to OCR (RapidOCR, see common/ocr_engine.py) to recover line text
     + position instead.
  2. Group lines into paragraphs (see _group_into_paragraphs) and translate
     each paragraph as one chunk — translating single wrapped lines in
     isolation starves the MT model of sentence context and reads like
     literal word substitution instead of a real translation.
  3. Redact the original line rectangles (pymupdf "burns" them out — works
     for both vector text and the rendered scan underneath).
  4. Re-insert the translated paragraph text in the union of its lines'
     rectangles, auto-shrinking the font size until it fits — translated
     text is rarely the exact same length as the source, and the whole
     point of this tool is that the document keeps looking like the
     original, not like a translation bolted on top of it.

Pages with no text at all (pure images, diagrams) are left untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common.depmsg import pip_hint
from common.ocr_engine import ocr_available, ocr_image
from .translate_engine import translate_text

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
    for block in page.get_text("dict")["blocks"]:
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


def _group_into_paragraphs(lines: list[dict]) -> list[dict]:
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
    """
    if not lines:
        return []

    ordered = sorted(lines, key=lambda li: (li["bbox"][1], li["bbox"][0]))

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
            if (vgap < 0.8 * ref_h and x_shift < 3.0 * ref_h and same_size):
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
        paragraphs.append({
            "line_rects": [g["bbox"] for g in group],
            "bbox":       (x0, y0, x1, y1),
            "text":       _join_lines([g["text"] for g in group]),
            "size":       dominant["size"],
            "color":      dominant["color"],
            "font":       dominant["font"],
        })
    return paragraphs


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
        progress_cb:      Callable[[float], None] | None = None,
        cancel_event=None,
    ) -> PdfResult:
        try:
            import fitz  # pymupdf
        except ImportError:
            return PdfResult(output=output_path, success=False,
                              error=f"pymupdf non disponibile — {pip_hint('pymupdf')}")

        try:
            doc = fitz.open(str(input_path))
        except Exception as exc:
            return PdfResult(output=output_path, success=False, error=str(exc))

        ocr_ready = include_scanned and ocr_available()
        total = doc.page_count or 1
        pages_done = 0

        # Track how many lines actually translated vs. failed. The per-line
        # fallback below keeps one bad line from killing the whole job, but if
        # EVERY line fails (e.g. the language pair isn't really installed, or
        # the MT model can't load) the output is just a copy of the source —
        # we must report that as an error, not a silent "success".
        translated_ok      = 0
        translate_errors   = 0
        first_error        = ""
        # A scanned page with no digital text needs OCR to recover anything —
        # if the user asked for it but RapidOCR isn't installed, that page
        # is silently left untouched. Count it so the result can say so
        # explicitly instead of reporting a fake full-document success.
        ocr_needed_missing = 0

        try:
            for i, page in enumerate(doc):
                if cancel_event is not None and cancel_event.is_set():
                    break

                lines = _digital_text_lines(page)
                if not lines:
                    if ocr_ready:
                        try:
                            lines = _ocr_lines(page)
                        except Exception:
                            # OCR failed on this page — leave it untouched
                            # rather than aborting the whole document.
                            lines = []
                    elif include_scanned:
                        ocr_needed_missing += 1

                if lines:
                    paragraphs = _group_into_paragraphs(lines)
                    for p in paragraphs:
                        # A single paragraph that the MT engine chokes on
                        # must not throw away every other page already
                        # done — fall back to leaving it untranslated.
                        try:
                            p["translated"] = translate_text(p["text"], src, tgt, glossary)
                            translated_ok += 1
                        except Exception as exc:
                            p["translated"] = p["text"]
                            translate_errors += 1
                            if not first_error:
                                first_error = str(exc)
                    # Page rotation handling: get_text()/get_pixmap() report
                    # boxes in the *displayed* (rotated) coordinate system,
                    # but add_redact_annot()/insert_textbox() operate in the
                    # page's *unrotated* base system. On a rotated page (e.g.
                    # this scanned manual is /Rotate 270) the two disagree, so
                    # without converting them the white-out misses the original
                    # text and the translation lands rotated and out of place.
                    # derotation_matrix is the identity on an unrotated page,
                    # so this is a no-op for the common case.
                    derot = page.derotation_matrix
                    rot   = page.rotation
                    for p in paragraphs:
                        p["rect"] = fitz.Rect(p["bbox"]) * derot

                    # apply_redactions() unconditionally drops every link
                    # overlapping a redacted rect (pymupdf docs/wiki) — a
                    # text line under a hyperlink is the common case (URLs,
                    # mailto:, page jumps), so without this the translated
                    # PDF would silently lose all its links. Capture and
                    # recreate them across the redaction.
                    links = page.get_links()
                    for p in paragraphs:
                        # Redact every original line individually (precise,
                        # matches exactly where the source text was) even
                        # though the translation gets re-inserted into their
                        # combined rect below.
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
                            page, p["rect"], p["translated"],
                            base_size=p["size"], color=_int_to_rgb(p["color"]),
                            fontname=_pick_font(p["font"]), rotate=rot)

                pages_done = i + 1
                if progress_cb:
                    progress_cb(pages_done / total)

            cancelled = cancel_event is not None and cancel_event.is_set()

            if not cancelled and translated_ok == 0:
                doc.close()
                # Nothing was translated anywhere in the document — figure out
                # why and report it instead of pretending the job succeeded.
                if ocr_needed_missing > 0 and translate_errors == 0:
                    return PdfResult(
                        output=output_path, success=False, page_count=pages_done,
                        error=(f"Il PDF sembra scansionato (nessun testo "
                               f"digitale) e l'OCR non è disponibile: "
                               f"installa il motore OCR "
                               f"({pip_hint('rapidocr_onnxruntime')}), poi riprova. "
                               f"{ocr_needed_missing} pagina/e coinvolta/e."))
                if translate_errors > 0:
                    # Every line failed to translate → the output is an
                    # unchanged copy of the source (the common case: the
                    # chosen language pair was never downloaded, or its
                    # model can't be loaded at runtime).
                    return PdfResult(
                        output=output_path, success=False, page_count=pages_done,
                        error=(f"Nessuna riga è stata tradotta: la coppia di "
                               f"lingue {src}→{tgt} non risulta utilizzabile. "
                               f"Apri 'Gestisci lingue' e scarica/reinstalla la "
                               f"coppia. Dettaglio tecnico: {first_error}"))
                return PdfResult(
                    output=output_path, success=False, page_count=pages_done,
                    error="Nessun testo trovato nel PDF: nessuna pagina conteneva "
                          "testo da tradurre.")

            doc.save(str(output_path))
            doc.close()
            warning = ""
            if ocr_needed_missing > 0:
                warning = (f"{ocr_needed_missing} pagina/e scansionata/e ignorata/e: "
                           f"installa il motore OCR per tradurle "
                           f"({pip_hint('rapidocr_onnxruntime')}).")
            return PdfResult(output=output_path, success=True, cancelled=cancelled,
                              page_count=pages_done, warning=warning,
                              file_size=output_path.stat().st_size)
        except Exception as exc:
            # Best-effort: keep whatever pages were already translated
            # instead of discarding the whole job on one fatal error.
            try:
                doc.save(str(output_path))
            except Exception:
                pass
            doc.close()
            return PdfResult(output=output_path, success=False,
                              page_count=pages_done, error=str(exc))
