#!/usr/bin/env python3
"""
Smoke test — verifies the parts most likely to break after a dependency
bump, without needing the GUI. Run it inside the venv:

    python smoke_test.py

It checks, in order:
  1. Versions of the security-bumped packages (Pillow, pypdf) + key optionals.
  2. That every core + optional dependency actually imports.
  3. The real pypdf code paths (merge / split / encrypt / decrypt) — this is
     the riskiest area because pypdf jumped a major version (5.x -> 6.x).
  4. A Pillow 12 image round-trip (open / convert / save).
  5. The offline-translation source cleanup we added (de-hyphenation +
     wordninja word de-gluing).

Exit code is 0 only if nothing FAILED (SKIP is allowed, e.g. an optional
package not installed). Anything FAILED -> exit 1, so this can gate a build.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Mirror how tools/pdf_manager/app.py sets up imports: the tool dir first
# (so `import core.*` resolves), then tools/ (so `import common.*` resolves).
sys.path.insert(0, str(ROOT / "tools" / "pdf_manager"))
sys.path.insert(0, str(ROOT / "tools"))

_results: list[tuple[str, str, str]] = []  # (status, name, detail)


def _record(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}[status]
    line = f"  {icon} {status:4} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)


def check_versions() -> None:
    print("\n[1] Package versions")
    import importlib.metadata as md
    wanted = {
        "pillow": "12.2.0",   # security floor
        "pypdf":  "6.13.3",   # security floor
    }
    optional = ["argostranslate", "stanza", "ctranslate2", "wordninja",
                "pymupdf", "rapidocr-onnxruntime"]
    for pkg, floor in wanted.items():
        try:
            v = md.version(pkg)
            ok = tuple(map(int, v.split(".")[:3])) >= tuple(map(int, floor.split(".")))
            _record("PASS" if ok else "FAIL", f"{pkg} {v}",
                     "" if ok else f"expected >= {floor}")
        except Exception as exc:
            _record("FAIL", pkg, f"not found: {exc}")
    for pkg in optional:
        try:
            _record("PASS", f"{pkg} {md.version(pkg)}")
        except Exception:
            _record("SKIP", pkg, "not installed (optional)")


def check_imports() -> None:
    print("\n[2] Imports")
    core = ["PIL", "pypdf", "reportlab", "fitz", "pdfplumber",
            "customtkinter", "numpy", "scipy", "soundfile", "mutagen", "pydub"]
    optional = ["rapidocr_onnxruntime", "argostranslate.translate", "wordninja"]
    for mod in core:
        try:
            __import__(mod)
            _record("PASS", f"import {mod}")
        except Exception as exc:
            _record("FAIL", f"import {mod}", str(exc))
    for mod in optional:
        try:
            __import__(mod)
            _record("PASS", f"import {mod}")
        except Exception:
            _record("SKIP", f"import {mod}", "optional not installed")


def _make_pdf(path: Path, pages: int = 2) -> None:
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    for i in range(pages):
        c.drawString(72, 720, f"Smoke test page {i + 1}")
        c.showPage()
    c.save()


def check_pypdf() -> None:
    print("\n[3] pypdf code paths (merge / split / encrypt / decrypt)")
    try:
        from core.pdf_engine import PdfEngine
        from pypdf import PdfReader
    except Exception as exc:
        _record("FAIL", "load PdfEngine", str(exc))
        return

    eng = PdfEngine()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "src.pdf"
        _make_pdf(src, pages=2)

        # merge two 2-page PDFs -> 4 pages
        merged = tmp / "merged.pdf"
        r = eng.merge([src, src], merged)
        try:
            n = len(PdfReader(str(merged)).pages)
            _record("PASS" if r.success and n == 4 else "FAIL",
                    "merge", f"{n} pages" if r.success else r.error)
        except Exception as exc:
            _record("FAIL", "merge", str(exc))

        # split a range out
        try:
            rs = eng.split_by_ranges(merged, "1-2", tmp)
            ok = rs and rs[0].success and Path(rs[0].output).exists()
            _record("PASS" if ok else "FAIL", "split_by_ranges",
                    "" if ok else (rs[0].error if rs else "no result"))
        except Exception as exc:
            _record("FAIL", "split_by_ranges", str(exc))

        # encrypt with AES-256, confirm it's really encrypted
        prot = tmp / "protected.pdf"
        try:
            r = eng.protect(src, "secret", "secret", prot)
            enc = PdfReader(str(prot)).is_encrypted if r.success else False
            _record("PASS" if r.success and enc else "FAIL", "protect (AES-256)",
                    "encrypted" if enc else (r.error or "not encrypted"))
        except Exception as exc:
            _record("FAIL", "protect (AES-256)", str(exc))

        # decrypt it back with the right password
        unlocked = tmp / "unlocked.pdf"
        try:
            r = eng.unlock(prot, "secret", unlocked)
            still = PdfReader(str(unlocked)).is_encrypted if r.success else True
            _record("PASS" if r.success and not still else "FAIL", "unlock",
                    "decrypted" if not still else (r.error or "still encrypted"))
        except Exception as exc:
            _record("FAIL", "unlock", str(exc))


def check_pillow() -> None:
    print("\n[4] Pillow image round-trip")
    try:
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "x.png"
            jpg = Path(td) / "x.jpg"
            Image.new("RGBA", (32, 16), (200, 100, 50, 255)).save(png)
            Image.open(png).convert("RGB").save(jpg, "JPEG", quality=85)
            ok = jpg.exists() and Image.open(jpg).size == (32, 16)
            _record("PASS" if ok else "FAIL", "PNG->JPEG convert")
    except Exception as exc:
        _record("FAIL", "PNG->JPEG convert", str(exc))


def check_translation_cleanup() -> None:
    print("\n[5] Translation source cleanup")
    try:
        from core.pdf_translator_engine import _join_lines
        out = _join_lines(["attach-", "ments are designed"])
        _record("PASS" if out == "attachments are designed" else "FAIL",
                "de-hyphenation", out)
    except Exception as exc:
        _record("FAIL", "de-hyphenation", str(exc))

    try:
        from core.translate_engine import _split_glued_word, _get_wordninja
        if _get_wordninja() is None:
            _record("SKIP", "word de-gluing", "wordninja not installed")
        else:
            out = _split_glued_word("POWERUNITS")
            _record("PASS" if out == "POWER UNITS" else "FAIL",
                    "word de-gluing", f"POWERUNITS -> {out}")
    except Exception as exc:
        _record("FAIL", "word de-gluing", str(exc))


def main() -> int:
    print("Multimedia Master — smoke test")
    check_versions()
    check_imports()
    check_pypdf()
    check_pillow()
    check_translation_cleanup()

    n_fail = sum(1 for s, _, _ in _results if s == "FAIL")
    n_skip = sum(1 for s, _, _ in _results if s == "SKIP")
    n_pass = sum(1 for s, _, _ in _results if s == "PASS")
    print(f"\nSummary: {n_pass} passed, {n_fail} failed, {n_skip} skipped")
    if n_fail:
        print("RESULT: FAIL — see the ✗ lines above.")
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
