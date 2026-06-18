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
            text = "".join(span["text"] for span in line["spans"]).strip()
            if not text:
                continue
            span0 = line["spans"][0]
            lines.append({
                "bbox":  line["bbox"],
                "text":  text,
                "size":  span0["size"],
                "color": span0["color"],
                "font":  span0["font"],
            })
    return lines


def _ocr_lines(page, src_lang: str):
    import fitz
    import pytesseract
    from PIL import Image

    zoom = _OCR_DPI / 72
    pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    data = pytesseract.image_to_data(
        img, lang=_TESS_LANG.get(src_lang, "eng"),
        output_type=pytesseract.Output.DICT)

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

        try:
            for i, page in enumerate(doc):
                if cancel_event is not None and cancel_event.is_set():
                    break

                lines = _digital_text_lines(page)
                if not lines and ocr_ready:
                    lines = _ocr_lines(page, src)

                if lines:
                    for li in lines:
                        li["translated"] = translate_text(li["text"], src, tgt, glossary)
                    for li in lines:
                        page.add_redact_annot(fitz.Rect(li["bbox"]), fill=(1, 1, 1))
                    page.apply_redactions()
                    for li in lines:
                        _insert_autoshrink(
                            page, fitz.Rect(li["bbox"]), li["translated"],
                            base_size=li["size"], color=_int_to_rgb(li["color"]),
                            fontname=_pick_font(li["font"]))

                if progress_cb:
                    progress_cb((i + 1) / total)

            doc.save(str(output_path))
            doc.close()
            return PdfResult(output=output_path, success=True,
                              page_count=total, file_size=output_path.stat().st_size)
        except Exception as exc:
            doc.close()
            return PdfResult(output=output_path, success=False, error=str(exc))
