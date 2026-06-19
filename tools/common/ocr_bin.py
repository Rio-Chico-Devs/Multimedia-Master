"""
Bundled-Tesseract auto-configuration.

Makes the PyInstaller build fully self-contained for OCR: if the developer
vendored a Tesseract OCR copy before building (see
vendor/tesseract/README.md), point pytesseract at that bundled binary instead
of requiring the end user to install Tesseract separately.

No-op in dev mode (`python app.py`, not frozen) or if no vendored copy was
bundled — pytesseract then falls back to searching PATH, exactly as it does
today.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_tesseract() -> None:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return  # dev mode — nothing to do, rely on the system PATH

    vendor = Path(base) / "vendor" / "tesseract"
    exe_name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    exe_path = vendor / exe_name
    if not exe_path.is_file():
        return  # build wasn't given a vendored copy — fall back to PATH

    try:
        import pytesseract
    except ImportError:
        return

    pytesseract.pytesseract.tesseract_cmd = str(exe_path)
    tessdata = vendor / "tessdata"
    if tessdata.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
