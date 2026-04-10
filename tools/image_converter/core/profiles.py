from dataclasses import dataclass
from core.formats import ConversionConfig


@dataclass(frozen=True)
class Profile:
    name:        str
    config:      ConversionConfig
    description: str = ""


# ── Profili predefiniti ────────────────────────────────────────────────────────

PROFILES: list[Profile] = [
    Profile(
        name="Personalizzato",
        config=ConversionConfig(),
        description="Usa le impostazioni manuali",
    ),
    Profile(
        name="Web ottimizzato",
        config=ConversionConfig(format="WebP", quality=82, strip_meta=True),
        description="WebP q82 · metadati rimossi · ideale per siti web",
    ),
    Profile(
        name="Social media",
        config=ConversionConfig(
            format="JPEG", quality=88, target_w=1200, strip_meta=True
        ),
        description="JPEG q88 · max 1200 px · metadati rimossi",
    ),
    Profile(
        name="Stampa",
        config=ConversionConfig(format="TIFF", quality=95, strip_meta=False),
        description="TIFF LZW q95 · metadati preservati · alta qualità",
    ),
    Profile(
        name="Archivio PNG",
        config=ConversionConfig(format="PNG", quality=95, strip_meta=False),
        description="PNG lossless · metadati preservati · archiviazione",
    ),
]

PROFILE_NAMES: list[str] = [p.name for p in PROFILES]


def get_profile(name: str) -> Profile | None:
    return next((p for p in PROFILES if p.name == name), None)
