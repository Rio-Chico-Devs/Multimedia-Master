import sys
from pathlib import Path

# Tool-local imports (core/, ui/)
sys.path.insert(0, str(Path(__file__).parent))
# Shared imports (common/)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Crash logging FIRST — on Windows the tool has no console, so without
# this every exception (incl. C-extension crashes) is silently lost.
from common.crashlog import install as _install_crashlog, run_gui as _run_gui
from common.paths import crash_log_path
_install_crashlog(crash_log_path("pdf_manager"))

# Frozen-build hardening: pytesseract spawns tesseract.exe without setting
# stdin, which hangs forever (not crashes) in a windowed build with no console.
from common.proc import harden_subprocess_stdin as _harden_stdin
_harden_stdin()

# Point pytesseract at the bundled Tesseract copy, if the build vendored one
# (see vendor/tesseract/README.md) — makes OCR/scanned-PDF-translation work
# on a customer's PC with nothing extra to install. No-op otherwise.
from common.ocr_bin import configure_tesseract as _configure_tesseract
_configure_tesseract()

import customtkinter as ctk
from ui.pdf_window import PdfWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

if __name__ == "__main__":
    _run_gui(PdfWindow, "Gestione PDF")
