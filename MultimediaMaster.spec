# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec — single-exe build for Multimedia Master.

Build (on Windows, inside the project's venv):
    pip install pyinstaller
    pyinstaller MultimediaMaster.spec

Output: dist/MultimediaMaster/MultimediaMaster.exe  (onedir build)

WHY onedir, not onefile:
    Onefile re-extracts the whole bundle to a temp dir on every launch —
    slow startup, and the temp dir disappears on exit (bad for crash logs).
    Onedir starts fast and writes logs next to the real exe. Distribute the
    whole dist/MultimediaMaster/ folder (zip it) or wrap it with an
    installer (Inno Setup) later.

WHY the entire tools/ tree is bundled as plain *data*, not analyzed code:
    image_converter, pdf_manager and audio_manager each have their own
    core/ and ui/ packages using bare names ("core", "ui") rather than
    fully-qualified ones. That's safe at runtime because each tool runs in
    its own subprocess and only ever adds its own tools/<name>/ directory
    to sys.path (see launcher.py / each app.py) — but PyInstaller's static
    analyzer has no way to know that, and would either miss these modules
    or scramble which "core" belongs to which tool if asked to trace them.
    Shipping tools/ as data and loading each app.py with runpy.run_path()
    (see launcher.py's entry point) sidesteps the analyzer entirely and
    reproduces the exact same import behaviour as `python tools/x/app.py`
    in dev mode.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "tools"), "tools"),
    (str(ROOT / "assets"), "assets"),
]
binaries = []
hiddenimports = []

# Third-party packages used by code inside tools/ that PyInstaller's
# analyzer never sees (see module docstring above) — collected explicitly
# so their compiled extensions, data files and hidden submodules are not
# silently dropped from the bundle.
_THIRD_PARTY = [
    "customtkinter",
    "PIL",
    "tkinterdnd2",
    "pypdf",
    "reportlab",
    "fitz",          # pymupdf's import name
    "pdfplumber",
    "pydub",
    "imageio_ffmpeg",
    "soundfile",
    "noisereduce",
    "numpy",
    "scipy",
    "mutagen",
    "sounddevice",
    "argostranslate",
    "ctranslate2",
    "sentencepiece",
    "wordninja",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "shapely",
    "pyclipper",
]
for _pkg in _THIRD_PARTY:
    try:
        _d, _b, _h = collect_all(_pkg)
    except Exception:
        # Optional dependency not installed in this build environment —
        # skip it; the corresponding feature will fail gracefully at
        # runtime exactly like it does today when the package is missing.
        continue
    datas += _d
    binaries += _b
    hiddenimports += _h

# Bundle a vendored RapidOCR "latin" model (Italian/French/German/Spanish
# recognition) if the developer placed one at vendor/rapidocr/ before
# building (see vendor/rapidocr/README.md). Optional: rapidocr_onnxruntime's
# own stock Chinese+English model is already collected above regardless, so
# the build still succeeds and OCR still works for English without this —
# this only improves accented-Latin-script recognition.
_VENDOR_RAPIDOCR = ROOT / "vendor" / "rapidocr"
if _VENDOR_RAPIDOCR.is_dir():
    datas.append((str(_VENDOR_RAPIDOCR), "vendor/rapidocr"))

a = Analysis(
    ["launcher.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MultimediaMaster",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # GUI app — no console window
    icon=str(ROOT / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MultimediaMaster",
)
