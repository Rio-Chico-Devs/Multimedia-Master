"""
PDF Translator Engine — translates a PDF in place: same layout, same page,
only the text is replaced.

Pipeline per page:
  1. Read text lines with their position/size/font via pymupdf's structured
     text dict. If a page has no extractable text (a scanned page), fall
     back to OCR (pytesseract) to recover line text + position instead.
  2. Translate every line (offline, see translate_engine.py).
  3. Redact the original line rectangles (pymupdf "burns" them out — works
     for both vector text and the rendered scan underneath).
  4. Re-insert the translated text in the same rectangle, auto-shrinking the
     font size until it fits — translated text is rarely the exact same
     length as the source, and the whole point of this tool is that the
     document keeps looking like the original, not like a translation
     bolted on top of it.

Pages with no text at all (pure images, diagrams) are left untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common.depmsg import pip_hint
from .translate_engine import translate_text

# argostranslate language codes (ISO 639-1) -> Tesseract language codes.
_TESS_LANG = {
    "en": "eng", "it": "ita", "fr": "fra", "de": "deu", "es": "spa",
    "pt": "por", "nl": "nld", "ru": "rus", "zh": "chi_sim", "ja": "jpn",
    "ar": "ara", "pl": "pol", "tr": "tur", "ko": "kor", "sv": "swe",
}

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


def _ocr_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


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
                        color: tuple[float, float, float], fontname: str) -> None:
    size = max(base_size, _MIN_FONT_SIZE)
    while size >= _MIN_FONT_SIZE:
        rc = page.insert_textbox(rect, text, fontsize=size, fontname=fontname,
                                  color=color, align=0)
        if rc >= 0:
            return
        size -= 0.5
    page.insert_textbox(rect, text, fontsize=_MIN_FONT_SIZE, fontname=fontname,
                         color=color, align=0)


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


def _ocr_lines(page, src_lang: str):
    import fitz
    import pytesseract
    from PIL import Image

    zoom = _OCR_DPI / 72
    pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    # timeout: Tesseract può bloccarsi su immagini patologiche — stesso
    # limite usato da core/pdf_engine.py per la conversione con OCR.
    data = pytesseract.image_to_data(
        img, lang=_TESS_LANG.get(src_lang, "eng"),
        output_type=pytesseract.Output.DICT, timeout=120)

    groups: dict[tuple, dict] = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y, w, h = (data["left"][i], data["top"][i],
                      data["width"][i], data["height"][i])
        g = groups.setdefault(key, {"words": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h})
        g["words"].append(word)
        g["x0"] = min(g["x0"], x);     g["y0"] = min(g["y0"], y)
        g["x1"] = max(g["x1"], x + w); g["y1"] = max(g["y1"], y + h)

    lines = []
    for g in groups.values():
        height_pt = (g["y1"] - g["y0"]) / zoom
        lines.append({
            "bbox":  (g["x0"] / zoom, g["y0"] / zoom, g["x1"] / zoom, g["y1"] / zoom),
            "text":  " ".join(g["words"]),
            "size":  max(_MIN_FONT_SIZE, height_pt * 0.8),
            "color": 0,
            "font":  "",
        })
    return lines


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

        ocr_ready = include_scanned and _ocr_available()
        total = doc.page_count or 1
        pages_done = 0

        try:
            for i, page in enumerate(doc):
                if cancel_event is not None and cancel_event.is_set():
                    break

                lines = _digital_text_lines(page)
                if not lines and ocr_ready:
                    try:
                        lines = _ocr_lines(page, src)
                    except RuntimeError:
                        # OCR timed out on this page — leave it untouched
                        # rather than aborting the whole document.
                        lines = []

                if lines:
                    for li in lines:
                        # A single line that the MT engine chokes on must
                        # not throw away every other page already done —
                        # fall back to leaving that one line untranslated.
                        try:
                            li["translated"] = translate_text(li["text"], src, tgt, glossary)
                        except Exception:
                            li["translated"] = li["text"]
                    # apply_redactions() unconditionally drops every link
                    # overlapping a redacted rect (pymupdf docs/wiki) — a
                    # text line under a hyperlink is the common case (URLs,
                    # mailto:, page jumps), so without this the translated
                    # PDF would silently lose all its links. Capture and
                    # recreate them across the redaction.
                    links = page.get_links()
                    for li in lines:
                        page.add_redact_annot(fitz.Rect(li["bbox"]), fill=(1, 1, 1))
                    page.apply_redactions()
                    for link in links:
                        # The xref refers to the link object apply_redactions()
                        # just destroyed — insert_link() must create a new
                        # object, not be pointed at the dead one.
                        link.pop("xref", None)
                        page.insert_link(link)
                    for li in lines:
                        _insert_autoshrink(
                            page, fitz.Rect(li["bbox"]), li["translated"],
                            base_size=li["size"], color=_int_to_rgb(li["color"]),
                            fontname=_pick_font(li["font"]))

                pages_done = i + 1
                if progress_cb:
                    progress_cb(pages_done / total)

            cancelled = cancel_event is not None and cancel_event.is_set()
            doc.save(str(output_path))
            doc.close()
            return PdfResult(output=output_path, success=True, cancelled=cancelled,
                              page_count=pages_done, file_size=output_path.stat().st_size)
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
