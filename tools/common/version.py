"""
Version and product identity — the single source of truth for every tool.

WHY the product name is not a constant here:
    This package is shared verbatim by every product built from this tree,
    and each of those products is sold on its own. A customer must find no
    mention of a product they did not buy anywhere in their install — not in
    a title bar, not in a settings folder, not even in a docstring inside
    the shipped sources. A name hardcoded here would ship to all of them.

    So the build spec writes _stamp.py next to this file at build time,
    carrying that build's identity, and this module reads it back. Adding a
    product means teaching the spec one more stamp; nothing in this package
    ever names a product.

Running from source there is no stamp, so the identity is derived from the
checkout's own folder name. That path is dev-mode only — every frozen build
is stamped — so a renamed checkout only ever affects the developer's own
title bars and settings folder, never a customer's.
"""
from __future__ import annotations

from pathlib import Path

__version__    = "2.1.0"
__build_year__ = "2025"


def _identity() -> tuple[str, str, bool]:
    """(display name, slug, standalone?) of the running product."""
    try:
        from common import _stamp
        return (_stamp.PRODUCT_NAME, _stamp.PRODUCT_SLUG,
                _stamp.IS_STANDALONE)
    except ImportError:
        # Dev mode: tools/common/version.py -> repo root.
        folder = Path(__file__).resolve().parents[2].name
        return folder.replace("-", " "), folder.replace("-", "_").lower(), False


#: Name shown to the user (title bars, About box, desktop notifications).
PRODUCT_NAME: str
#: Filesystem-safe identifier for per-product directories and license salts.
PRODUCT_SLUG: str
#: True when this build holds a single tool and is sold on its own.
IS_STANDALONE: bool

PRODUCT_NAME, PRODUCT_SLUG, IS_STANDALONE = _identity()


def product_name() -> str:
    """Display name of the running product."""
    return PRODUCT_NAME


def is_standalone() -> bool:
    """True when this build holds a single tool and is sold on its own."""
    return IS_STANDALONE
