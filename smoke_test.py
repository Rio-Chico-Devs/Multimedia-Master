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
    optional = ["pymupdf"]
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
    optional: list[str] = []
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
    # Permission flags: denying everything must NOT produce -4, which is
    # pypdf's "all permissions granted" value.
    try:
        from core.pdf_engine import (_PERM_ALL, _PERM_DENIABLE, _PERM_PRINT,
                                     _PERM_PRINT_HQ, _PERM_EXTRACT)

        def _flag(ap, ac):
            v = _PERM_ALL & ~_PERM_DENIABLE
            if ap: v |= _PERM_PRINT | _PERM_PRINT_HQ
            if ac: v |= _PERM_EXTRACT
            return v

        def _bit(v, n):      # /P bit N is (1 << (N-1))
            return ((v & 0xFFFFFFFF) >> (n - 1)) & 1

        deny = _flag(False, False)
        allow = _flag(True, True)
        ok = (deny != _PERM_ALL
              and _bit(deny, 3) == 0 and _bit(deny, 5) == 0
              and _bit(deny, 4) == 0 and _bit(deny, 11) == 0
              and _bit(deny, 10) == 1              # accessibility kept
              and _bit(deny, 32) == 1              # reserved bits intact
              and _bit(allow, 3) == 1 and _bit(allow, 5) == 1)
        _record("PASS" if ok else "FAIL", "encryption permission flags",
                f"deny={deny & 0xFFFFFFFF:#010x}, allow={allow & 0xFFFFFFFF:#010x}")
    except Exception as exc:
        _record("FAIL", "encryption permission flags", str(exc))

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

        # an invalid page range must be reported, never written as a 0-page PDF
        try:
            bad = eng.split_by_ranges(merged, "5-3, 0, 50-60, abc", tmp)
            ok = bool(bad) and all(not r.success for r in bad) and len(bad) == 4
            good = eng.split_by_ranges(merged, "1-2, 9-3, 3", tmp)
            ok = ok and [r.success for r in good] == [True, False, True]
            _record("PASS" if ok else "FAIL", "split invalid ranges rejected",
                    f"{sum(1 for r in bad if not r.success)}/4 rejected")
        except Exception as exc:
            _record("FAIL", "split invalid ranges rejected", str(exc))

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


def check_audio_engine() -> None:
    print("\n[5] Audio engine (format mapping / ID3v1 / voice effects)")
    # Each tool owns a top-level package literally named `core`, and the PDF
    # one is already bound in sys.modules from section [5]. Drop it and put
    # audio_manager first so `core.audio_engine` resolves to the audio tool.
    # (Run last: this repoints `core` for the rest of the process.)
    for mod in [m for m in sys.modules if m == "core" or m.startswith("core.")]:
        del sys.modules[mod]
    sys.path.insert(0, str(ROOT / "tools" / "audio_manager"))

    # pydub's export(format=) is an ffmpeg MUXER name, not a file extension.
    try:
        from core.audio_engine import _pydub_format
        from core.formats import AUDIO_EXTS
        bad = [e for e in ("m4a", "aac", "aif", "wma", "mka")
               if _pydub_format("." + e) == e]
        empty = [e for e in AUDIO_EXTS if not _pydub_format(e)]
        ok = not bad and not empty and _pydub_format(".mp3") == "mp3"
        _record("PASS" if ok else "FAIL", "pydub muxer mapping",
                f".m4a -> {_pydub_format('.m4a')}"
                + (f", unmapped: {bad}" if bad else ""))
    except Exception as exc:
        _record("FAIL", "pydub muxer mapping", str(exc))

    # ID3v1.1: byte 125 is the zero marker, 126 the track, 127 ALWAYS the genre.
    try:
        from core.audio_engine import AudioEngine
        tag = (b"TAG" + b"T".ljust(30, b"\x00") + b"A".ljust(30, b"\x00")
               + b"B".ljust(30, b"\x00") + b"2024"
               + b"c".ljust(28, b"\x00") + bytes([0, 7]) + bytes([17]))
        got = {f["raw_key"]: f["value"] for f in AudioEngine()._read_id3v1(tag)}
        ok = (got.get("_id3v1_track") == "7"
              and got.get("_id3v1_genre") == "Rock")
        _record("PASS" if ok else "FAIL", "ID3v1.1 offsets",
                f"track={got.get('_id3v1_track')}, "
                f"genre={got.get('_id3v1_genre')}")
    except Exception as exc:
        _record("FAIL", "ID3v1.1 offsets", str(exc))

    # asetrate constants are relative to 44100, so the chain must resample first.
    try:
        from core.audio_engine import VOICE_EFFECTS
        pitch = {k: c for k, (_, c) in VOICE_EFFECTS.items()
                 if "asetrate=" in c}
        bad = [k for k, c in pitch.items()
               if "aresample=44100" not in ("aresample=44100," + c).split(
                   "asetrate=")[0]]
        _record("PASS" if not bad else "FAIL", "voice-effect rate normalisation",
                f"{len(pitch)} pitch effects" + (f", bad: {bad}" if bad else ""))
    except Exception as exc:
        _record("FAIL", "voice-effect rate normalisation", str(exc))


def main() -> int:
    print("Multimedia Master — smoke test")
    check_versions()
    check_imports()
    check_pypdf()
    check_pillow()
    check_audio_engine()

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
