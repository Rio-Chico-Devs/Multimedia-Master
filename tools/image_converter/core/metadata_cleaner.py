"""
Metadata Cleaner — privacy-grade metadata removal, zero UI dependencies.

JPEG and PNG are cleaned LOSSLESSLY at byte level — pixel data is never
re-encoded, so there is zero quality loss:

  JPEG:  drops APP1 (EXIF + XMP), APP13 (IPTC/Photoshop), every other APPn
         and COM comment segments.  Keeps APP0 (JFIF), APP14 (Adobe colour
         transform — required for correct colours) and, optionally, the
         APP2 ICC colour profile.
         If the EXIF orientation tag is set (≠ 1) the rotation is baked
         into the pixels first via re-encode with quality='keep'
         (original quantisation tables → visually identical).

  PNG:   drops ancillary metadata chunks (tEXt, zTXt, iTXt, eXIf, tIME)
         keeping everything required to render the image identically.

  Other formats (WebP / TIFF / GIF / BMP) are re-encoded without metadata.

scan() reports which sensitive fields are present BEFORE cleaning, so the
UI can show the user exactly what is being removed (GPS, camera, dates…).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps


# EXIF tag ids (IFD0 / Exif IFD) → human-readable category
_GPS_IFD       = 0x8825
_EXIF_IFD      = 0x8769
_TAG_MAKE      = 0x010F
_TAG_MODEL     = 0x0110
_TAG_SOFTWARE  = 0x0131
_TAG_DATETIME  = 0x0132
_TAG_ARTIST    = 0x013B
_TAG_COPYRIGHT = 0x8298
_TAG_DT_ORIG   = 0x9003
_TAG_SERIAL    = 0xA431
_TAG_LENS_SER  = 0xA435
_TAG_ORIENT    = 0x0112

# PNG ancillary chunks that carry metadata (never needed for rendering)
_PNG_META_CHUNKS = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}


@dataclass
class CleanResult:
    source:         Path
    output:         Path | None
    success:        bool
    lossless:       bool       = False
    removed:        list[str]  = field(default_factory=list)
    original_size:  int        = 0
    cleaned_size:   int        = 0
    error:          str        = ""


class MetadataCleaner:
    """Stateless engine: scan & strip image metadata."""

    # ── Scan ──────────────────────────────────────────────────────────────

    def scan(self, path: Path) -> list[str]:
        """Return human-readable labels of sensitive metadata found."""
        found: list[str] = []
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                if exif:
                    try:
                        if exif.get_ifd(_GPS_IFD):
                            found.append("Posizione GPS")
                    except Exception:
                        pass
                    if exif.get(_TAG_MAKE) or exif.get(_TAG_MODEL):
                        found.append("Fotocamera")
                    try:
                        exif_ifd = exif.get_ifd(_EXIF_IFD)
                    except Exception:
                        exif_ifd = {}
                    if exif.get(_TAG_DATETIME) or exif_ifd.get(_TAG_DT_ORIG):
                        found.append("Data scatto")
                    if exif.get(_TAG_SOFTWARE):
                        found.append("Software")
                    if exif.get(_TAG_ARTIST) or exif.get(_TAG_COPYRIGHT):
                        found.append("Autore")
                    if exif_ifd.get(_TAG_SERIAL) or exif_ifd.get(_TAG_LENS_SER):
                        found.append("N° seriale dispositivo")
                    if exif and not found:
                        found.append("EXIF generico")
                if img.info.get("xmp") or img.info.get("XML:com.adobe.xmp"):
                    found.append("XMP")
                if img.info.get("photoshop"):
                    found.append("IPTC/Photoshop")
                if img.info.get("comment"):
                    found.append("Commento")
                # PNG textual chunks
                if getattr(img, "text", None):
                    found.append("Testo PNG")
        except Exception:
            pass
        return found

    # ── Clean ─────────────────────────────────────────────────────────────

    def clean(self, src: Path, output: Path,
              keep_icc: bool = True) -> CleanResult:
        """Write a metadata-free copy of `src` to `output`."""
        removed = self.scan(src)
        try:
            orig_size = src.stat().st_size
            ext = src.suffix.lower()

            if ext in (".jpg", ".jpeg"):
                lossless = self._clean_jpeg(src, output, keep_icc)
            elif ext == ".png":
                lossless = self._clean_png(src, output, keep_icc)
            else:
                lossless = self._clean_reencode(src, output, keep_icc)

            if not output.exists() or output.stat().st_size == 0:
                return CleanResult(source=src, output=output, success=False,
                                   error="output vuoto")
            return CleanResult(
                source=src, output=output, success=True,
                lossless=lossless, removed=removed,
                original_size=orig_size,
                cleaned_size=output.stat().st_size,
            )
        except Exception as exc:
            return CleanResult(source=src, output=output,
                               success=False, error=str(exc))

    # ── JPEG: byte-level segment strip ────────────────────────────────────

    def _clean_jpeg(self, src: Path, output: Path, keep_icc: bool) -> bool:
        """Returns True if the clean was lossless (no re-encode)."""
        # Orientation ≠ 1 → must bake rotation into pixels (re-encode once
        # with the original quantisation tables: visually identical).
        with Image.open(src) as img:
            orientation = img.getexif().get(_TAG_ORIENT, 1)
            if orientation != 1:
                icc = img.info.get("icc_profile") if keep_icc else None
                # Reuse the ORIGINAL quantisation tables + subsampling so the
                # one unavoidable re-encode is visually identical.  (Can't use
                # quality='keep': after exif_transpose the image is no longer
                # a JpegImageFile and PIL would raise.)
                kw: dict = {"optimize": True}
                try:
                    from PIL import JpegImagePlugin
                    kw["qtables"] = img.quantization
                    sampling = JpegImagePlugin.get_sampling(img)
                    if sampling >= 0:
                        kw["subsampling"] = sampling
                except Exception:
                    kw = {"quality": 95, "optimize": True}
                img = ImageOps.exif_transpose(img)
                if icc:
                    kw["icc_profile"] = icc
                img.save(output, format="JPEG", **kw)
                return False

        data = src.read_bytes()
        output.write_bytes(self._strip_jpeg_segments(data, keep_icc))
        return True

    @staticmethod
    def _strip_jpeg_segments(data: bytes, keep_icc: bool) -> bytes:
        if data[:2] != b"\xff\xd8":
            raise ValueError("Non è un file JPEG valido")
        out = bytearray(b"\xff\xd8")
        i = 2
        n = len(data)
        while i < n - 1:
            if data[i] != 0xFF:
                # Malformed stream — copy the remainder untouched
                out += data[i:]
                break
            marker = data[i + 1]
            if marker == 0xFF:          # fill byte
                i += 1
                continue
            if marker == 0xD9:          # EOI
                out += data[i:i + 2]
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:   # TEM / RSTn
                out += data[i:i + 2]
                i += 2
                continue
            if marker == 0xDA:          # SOS → entropy-coded data until EOI
                out += data[i:]
                break

            seglen = int.from_bytes(data[i + 2:i + 4], "big")
            seg = data[i:i + 2 + seglen]
            keep = True
            if marker == 0xFE:                       # COM
                keep = False
            elif 0xE0 <= marker <= 0xEF:             # APPn
                app_n = marker - 0xE0
                if app_n == 0:                       # JFIF
                    keep = True
                elif app_n == 2 and keep_icc and \
                        seg[4:15] == b"ICC_PROFILE":
                    keep = True
                elif app_n == 14 and seg[4:9] == b"Adobe":
                    keep = True                      # colour-transform flag
                else:
                    keep = False                     # EXIF/XMP/IPTC/altro
            if keep:
                out += seg
            i += 2 + seglen
        return bytes(out)

    # ── PNG: chunk-level strip ────────────────────────────────────────────

    def _clean_png(self, src: Path, output: Path, keep_icc: bool) -> bool:
        data = src.read_bytes()
        sig = data[:8]
        if sig != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Non è un file PNG valido")
        out = bytearray(sig)
        i = 8
        n = len(data)
        while i + 12 <= n:
            length = int.from_bytes(data[i:i + 4], "big")
            ctype = data[i + 4:i + 8]
            chunk = data[i:i + 12 + length]
            drop = (ctype in _PNG_META_CHUNKS
                    or (ctype == b"iCCP" and not keep_icc))
            if not drop:
                out += chunk
            if ctype == b"IEND":
                break
            i += 12 + length
        output.write_bytes(bytes(out))
        return True

    # ── Other formats: re-encode without metadata ─────────────────────────

    def _clean_reencode(self, src: Path, output: Path, keep_icc: bool) -> bool:
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img)
            icc = img.info.get("icc_profile") if keep_icc else None
            fmt = (src.suffix.lower().lstrip(".")
                   .replace("jpg", "jpeg").replace("tif", "tiff").upper())
            kw: dict = {}
            if fmt == "WEBP":
                # Re-encode lossless WebP losslessly; lossy gets q=95
                kw = {"lossless": img.info.get("lossless", False),
                      "quality": 95, "method": 4}
            elif fmt == "TIFF":
                kw = {"compression": "tiff_lzw"}
            elif fmt == "GIF":
                kw = {"optimize": True, "save_all": True}
            elif fmt == "BMP":
                kw = {}
            if icc and fmt in ("WEBP", "TIFF"):
                kw["icc_profile"] = icc
            img.save(output, format=fmt or None, **kw)
        return False
