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

# Per-target identity.
#   _ENTRY    PyInstaller entry script (compiled into the archive, never
#             shipped as readable source next to the exe)
#   _NAME     exe and dist/ folder name
#   _PRODUCT  display name — title bars, About box, desktop notifications
#   _SLUG     filesystem-safe id: ~/.<slug>/settings.json and license salt.
#             The suite's slug MUST stay "multimedia_master" or existing
#             installs lose their saved settings and their issued keys.
#   _ALONE    True when the build holds a single tool and is sold on its own.
#             Shipped code describes itself this way rather than referring to
#             a multi-tool build, so a standalone install never hints that
#             other products exist.
_ENTRY, _NAME, _PRODUCT, _SLUG, _ALONE = {
    "all": ("launcher.py",     "MultimediaMaster",
            "Multimedia Master", "multimedia_master", False),
    "pdf": ("pdf_launcher.py", "PdfManager",
            "PDF Manager",       "pdf_manager",       True),
}[TARGET]

# Packaging mode, independent of which product is being built.
#
# onedir (default): a folder of files. Starts instantly and the whole folder
#   must be distributed together.
# onefile (MM_ONEFILE=1): a single self-extracting .exe that can be dropped
#   anywhere and double-clicked. It unpacks its entire payload to a temporary
#   directory on EVERY launch, so startup costs seconds, not milliseconds,
#   and antivirus heuristics flag self-extracting executables more often.
#   Chosen when handing a customer one file matters more than launch speed.
ONEFILE = os.environ.get("MM_ONEFILE", "").strip().lower() in ("1", "true", "yes", "on")

print(f"[spec] MM_TARGET={TARGET} -> building {_PRODUCT} ({_NAME}), "
      f"{'onefile' if ONEFILE else 'onedir'}")

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
# Only the icon itself — assets/generate_icon.py is a developer tool for
# regenerating it and has no business sitting in a customer's install folder.
datas.append((str(ROOT / "assets" / "icon.ico"), "assets"))

# Product identity, written into the bundle rather than hardcoded in
# tools/common/version.py, which both products ship verbatim. See that
# module's docstring for why: the standalone PDF Manager must not carry the
# suite's name anywhere a customer could find it.
# `workpath` is injected by PyInstaller and is per-target (build.bat passes
# --workpath), which keeps one product's stamp out of the other's build.
# Defaulted defensively so the spec still works if invoked by hand.
_STAMP_DIR = Path(globals().get("workpath") or (ROOT / "build")) / "_stamp"
_STAMP_DIR.mkdir(parents=True, exist_ok=True)
_STAMP = _STAMP_DIR / "_stamp.py"
_STAMP.write_text(
    '"""Product identity — GENERATED AT BUILD TIME by the build spec.\n'
    'Do not edit and do not commit: it is rewritten on every build."""\n'
    f"PRODUCT_NAME = {_PRODUCT!r}\n"
    f"PRODUCT_SLUG = {_SLUG!r}\n"
    f"IS_STANDALONE = {_ALONE!r}\n"
    f"IS_ONEFILE = {ONEFILE!r}\n",
    encoding="utf-8",
)
datas.append((str(_STAMP), "tools/common"))

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

# Needed by common/ (window icon, dialogs) and by every tool.
_THIRD_PARTY_SHARED = [
    "customtkinter",
    "PIL",
    "tkinterdnd2",
]

# Needed by tools/pdf_manager/.
_THIRD_PARTY_PDF = [
    "pypdf",
    "reportlab",
    "fitz",          # pymupdf's import name
    "pdfplumber",
]

# Needed by tools/audio_manager/ only. imageio_ffmpeg alone carries a full
# ffmpeg binary, so dropping this group is most of what makes the standalone
# PDF Manager smaller than the suite.
_THIRD_PARTY_AUDIO = [
    "numpy",         # only the audio tool computes on arrays
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

_EXE_COMMON = dict(
    name=_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # GUI app — no console window
    icon=str(ROOT / "assets" / "icon.ico"),
)

if ONEFILE:
    # Everything goes inside the executable; there is no COLLECT step and no
    # output folder — dist/<name>.exe IS the product.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        **_EXE_COMMON,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **_EXE_COMMON,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=_NAME,
    )
