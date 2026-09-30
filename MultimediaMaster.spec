# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec — onedir builds for Multimedia Master.

ONE spec, two products, selected by the MM_TARGET environment variable:

    MM_TARGET=all  (default)  the full suite — launcher + all three tools
                              -> dist/MultimediaMaster/MultimediaMaster.exe
    MM_TARGET=pdf             the PDF Manager on its own, no launcher
                              -> dist/PdfManager/PdfManager.exe

Build (on Windows, inside the project's venv) — use the batch scripts,
which set MM_TARGET and a per-target workpath for you:

    build.bat        full suite
    build-pdf.bat    PDF Manager only

WHY one parameterised spec instead of two spec files:
    The dependency lists below are the only place that records which
    third-party package each tool needs. Split across two files they would
    silently drift the first time someone adds a library to one and forgets
    the other — and the symptom (a feature that works from source but is
    dead in one of the two exes) is invisible until a customer hits it.
    Here a PDF dependency is added once and lands in both products.

WHY onedir, not onefile:
    Onefile re-extracts the whole bundle to a temp dir on every launch —
    slow startup, and the temp dir disappears on exit (bad for crash logs).
    Onedir starts fast and writes logs next to the real exe. Distribute the
    whole dist/<product>/ folder (the batch scripts zip it for you) or wrap
    it with an installer (Inno Setup) later.

WHY the entire tools/ tree is bundled as plain *data*, not analyzed code:
    image_converter, pdf_manager and audio_manager each have their own
    core/ and ui/ packages using bare names ("core", "ui") rather than
    fully-qualified ones. That's safe at runtime because each tool runs in
    its own subprocess and only ever adds its own tools/<name>/ directory
    to sys.path (see launcher.py / each app.py) — but PyInstaller's static
    analyzer has no way to know that, and would either miss these modules
    or scramble which "core" belongs to which tool if asked to trace them.
    Shipping tools/ as data and loading each app.py with runpy.run_path()
    sidesteps the analyzer entirely and reproduces the exact same import
    behaviour as `python tools/x/app.py` in dev mode. Both entry points do
    this — launcher.py for the suite, pdf_launcher.py for the standalone —
    so the two products run the tool code along one identical path.
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)

# ── Build target ───────────────────────────────────────────────────────────────

TARGET = os.environ.get("MM_TARGET", "all").strip().lower()
if TARGET not in ("all", "pdf"):
    raise SystemExit(
        f"MM_TARGET must be 'all' or 'pdf', got {TARGET!r}. "
        "Use build.bat (full suite) or build-pdf.bat (PDF Manager only).")

# (entry script, exe/folder name, product name shown in the build output)
_ENTRY, _NAME, _LABEL = {
    "all": ("launcher.py",     "MultimediaMaster", "Multimedia Master (full suite)"),
    "pdf": ("pdf_launcher.py", "PdfManager",       "PDF Manager (standalone)"),
}[TARGET]

print(f"[spec] MM_TARGET={TARGET} -> building {_LABEL}")

# The PDF Manager needs only its own tree plus the shared common/ package
# (crash log, OCR, settings, window icon) — it imports nothing from
# image_converter or audio_manager, so leaving those out of the standalone
# build drops their code and, more importantly, lets the dependency lists
# below drop the audio libraries entirely.
if TARGET == "pdf":
    datas = [
        (str(ROOT / "tools" / "pdf_manager"), "tools/pdf_manager"),
        (str(ROOT / "tools" / "common"), "tools/common"),
    ]
else:
    datas = [
        (str(ROOT / "tools"), "tools"),
    ]
datas.append((str(ROOT / "assets"), "assets"))
binaries = []
hiddenimports = []

# Third-party packages used by code inside tools/ that PyInstaller's
# analyzer never sees (see module docstring above) — collected explicitly
# so their compiled extensions, data files and hidden submodules are not
# silently dropped from the bundle.
#
# Grouped by which tool needs them, so the pdf target can leave out what it
# provably never imports. When adding a dependency, put it in the group that
# owns it: anything in _SHARED or _PDF ships in BOTH products, anything in
# _AUDIO ships only in the full suite.

# Needed by common/ (OCR, window icon, dialogs) and by every tool.
_THIRD_PARTY_SHARED = [
    "customtkinter",
    "PIL",
    "tkinterdnd2",
    "numpy",
    # common/ocr_engine.py -> rapidocr, plus its runtime dependencies
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "shapely",
    "pyclipper",
]

# Needed by tools/pdf_manager/.
_THIRD_PARTY_PDF = [
    "pypdf",
    "reportlab",
    "fitz",          # pymupdf's import name
    "pdfplumber",
    "argostranslate",
    "ctranslate2",   # argostranslate's inference backend
    "sentencepiece",
    "wordninja",
    "spellchecker",
]

# Needed by tools/audio_manager/ only. imageio_ffmpeg alone carries a full
# ffmpeg binary, so dropping this group is most of what makes the standalone
# PDF Manager smaller than the suite.
_THIRD_PARTY_AUDIO = [
    "pydub",
    "imageio_ffmpeg",
    "soundfile",
    "noisereduce",
    "scipy",
    "mutagen",
    "sounddevice",
]

# tools/image_converter/ needs nothing beyond _THIRD_PARTY_SHARED.
_THIRD_PARTY = _THIRD_PARTY_SHARED + _THIRD_PARTY_PDF
if TARGET == "all":
    _THIRD_PARTY += _THIRD_PARTY_AUDIO

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
    [_ENTRY],
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
    name=_NAME,
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
    name=_NAME,
)
