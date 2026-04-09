from dataclasses import dataclass
from pathlib import Path

# ── Formati supportati ─────────────────────────────────────────────────────────

INPUT_EXTS: set[str] = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".bmp", ".gif", ".tiff", ".tif",
}

OUTPUT_FORMATS: list[str] = ["WebP", "JPEG", "PNG", "TIFF", "BMP", "GIF"]

NO_QUALITY_FORMATS: set[str] = {"BMP", "GIF"}

# ── Preset qualità consigliati ─────────────────────────────────────────────────

QUALITY_DEFAULTS: dict[str, int] = {
    "WebP": 85,
    "JPEG": 85,
    "PNG":  85,
    "TIFF": 90,
    "BMP":  100,
    "GIF":  80,
}

QUALITY_HINTS: dict[str, str] = {
    "WebP": "Consigliato 85 · fino a -35% vs JPEG a parità di qualità",
    "JPEG": "Consigliato 85 · progressivo, ottimizzato (mozjpeg)",
    "PNG":  "Lossless · il cursore agisce sul livello di compressione",
    "TIFF": "Consigliato 90 · compressione LZW, ideale per archivio",
    "BMP":  "Nessuna compressione — qualità non applicabile",
    "GIF":  "Max 256 colori · per animazioni o grafica semplice",
}

EXT_MAP: dict[str, str] = {
    "WebP": ".webp",
    "JPEG": ".jpg",
    "PNG":  ".png",
    "TIFF": ".tiff",
    "BMP":  ".bmp",
    "GIF":  ".gif",
}


# ── Dataclass configurazione ───────────────────────────────────────────────────

@dataclass
class ConversionConfig:
    """All parameters needed for a single conversion job."""
    format:     str        = "WebP"
    quality:    int        = 85
    target_w:   int | None = None
    target_h:   int | None = None
    strip_meta: bool       = True
    output_dir: Path | None = None


# ── Dataclass risultato ────────────────────────────────────────────────────────

@dataclass
class ConversionResult:
    """Outcome of a single conversion — success or failure."""
    source:         Path
    output:         Path
    original_size:  int
    converted_size: int
    success:        bool
    error:          str = ""

    @property
    def delta_pct(self) -> int:
        """Positive = smaller file, negative = larger file."""
        if self.original_size == 0:
            return 0
        return round((1 - self.converted_size / self.original_size) * 100)
