"""
OCR engine — RapidOCR (ONNX), chosen instead of Tesseract specifically
because it needs no separate native installer: `pip install
rapidocr-onnxruntime` ships its own detection/recognition models *inside*
the wheel, so PyInstaller can bundle everything into the .exe and a
customer's PC needs nothing extra.

Language caveat: the model bundled in the wheel by default recognises
Chinese + English well, but not accented Latin text (Italian, French,
German, Spanish...). For that, vendor the "latin" PP-OCRv3 recognition
model once on the build machine (see vendor/rapidocr/README.md) — this
module then loads it from the local path instead of the stock model.

This module never reaches out to the network: model paths are always
either the wheel's own bundled files or an explicit local file already on
disk, never an auto-download.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_engine: Any = None
_engine_failed = False


def _vendor_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        d = Path(base) / "vendor" / "rapidocr"
    else:
        d = Path(__file__).resolve().parent.parent.parent / "vendor" / "rapidocr"
    return d if d.is_dir() else None


def _build_engine():
    from rapidocr_onnxruntime import RapidOCR

    kwargs: dict[str, str] = {}
    vendor = _vendor_dir()
    if vendor is not None:
        paths = {
            "det_model_path": vendor / "det.onnx",
            "rec_model_path": vendor / "rec.onnx",
            "rec_keys_path":  vendor / "keys.txt",
            "cls_model_path": vendor / "cls.onnx",
        }
        for key, path in paths.items():
            if path.is_file():
                kwargs[key] = str(path)
    return RapidOCR(**kwargs)


def _get_engine():
    global _engine, _engine_failed
    if _engine is None and not _engine_failed:
        try:
            _engine = _build_engine()
        except Exception:
            _engine_failed = True
    return _engine


def ocr_available() -> bool:
    return _get_engine() is not None


def ocr_image(img) -> list[dict]:
    """
    Run OCR on a PIL Image. Returns a list of
    {"bbox": (x0, y0, x1, y1), "text": str, "score": float}
    in image pixel coordinates (origin top-left), one per detected text line.
    """
    engine = _get_engine()
    if engine is None:
        return []

    import numpy as np

    result, _elapse = engine(np.array(img))
    if not result:
        return []

    lines = []
    for box, text, score in result:
        text = (text or "").strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        lines.append({
            "bbox":  (min(xs), min(ys), max(xs), max(ys)),
            "text":  text,
            "score": float(score),
        })
    return lines
