from pathlib import Path
from PIL import Image

from core.formats import ConversionConfig, ConversionResult, EXT_MAP


class ImageConverter:
    """
    Pure image conversion engine — zero UI dependencies.

    Usage:
        converter = ImageConverter()
        result = converter.convert(Path("photo.jpg"), config)
    """

    def convert(self, source: Path, config: ConversionConfig) -> ConversionResult:
        fmt = config.format
        ext = EXT_MAP[fmt]
        out_dir = config.output_dir or source.parent
        out_path = self._unique_path(out_dir, source.stem, ext)

        try:
            img = Image.open(source)
            icc = img.info.get("icc_profile")   # preserve color profile

            img = self._normalize_mode(img, fmt)
            img = self._resize(img, config)

            kw = self._save_kwargs(fmt, config.quality, icc, config.strip_meta)
            img.save(out_path, format=fmt, **kw)

            return ConversionResult(
                source=source,
                output=out_path,
                original_size=source.stat().st_size,
                converted_size=out_path.stat().st_size,
                success=True,
            )

        except Exception as exc:
            return ConversionResult(
                source=source,
                output=out_path,
                original_size=source.stat().st_size,
                converted_size=0,
                success=False,
                error=str(exc),
            )

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _unique_path(directory: Path, stem: str, ext: str) -> Path:
        """Return a path that does not overwrite any existing file."""
        path = directory / (stem + "_converted" + ext)
        counter = 1
        while path.exists():
            path = directory / f"{stem}_converted_{counter}{ext}"
            counter += 1
        return path

    @staticmethod
    def _normalize_mode(img: Image.Image, fmt: str) -> Image.Image:
        """
        Ensure the image color mode is compatible with the target format.
        Handles transparency compositing (white background for JPEG/BMP).
        """
        if fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "P", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            mask = img.split()[-1] if img.mode in ("RGBA", "LA") else None
            bg.paste(img, mask=mask)
            return bg

        if fmt not in ("GIF",) and img.mode == "P":
            return img.convert("RGBA")

        if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            return img.convert("RGB")

        return img

    @staticmethod
    def _resize(img: Image.Image, config: ConversionConfig) -> Image.Image:
        """
        Proportional resize — never enlarges the image.
        If only one dimension is given, the other is calculated automatically.
        """
        if not config.target_w and not config.target_h:
            return img

        tw = config.target_w or img.width
        th = config.target_h or img.height
        ratio = min(tw / img.width, th / img.height, 1.0)
        nw = max(1, int(img.width  * ratio))
        nh = max(1, int(img.height * ratio))
        return img.resize((nw, nh), Image.LANCZOS)

    @staticmethod
    def _save_kwargs(
        fmt: str, quality: int, icc: bytes | None, strip_meta: bool
    ) -> dict:
        """Build format-specific keyword arguments for Pillow's save()."""
        if fmt == "JPEG":
            kw: dict = {"quality": quality, "optimize": True, "progressive": True}
            if icc and not strip_meta:
                kw["icc_profile"] = icc
            return kw

        if fmt == "PNG":
            # quality 100 → compress 0 (fast), quality 1 → compress 9 (slow/small)
            compress = max(0, min(9, round((100 - quality) / 11)))
            return {"compress_level": compress, "optimize": True}

        if fmt == "WebP":
            return {"quality": quality, "method": 4}

        if fmt == "TIFF":
            return {"compression": "tiff_lzw"}

        if fmt == "GIF":
            return {"optimize": True}

        return {}
