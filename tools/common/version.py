"""Application version — single source of truth for all Multimedia Master tools."""
from __future__ import annotations

import sys
from pathlib import Path

__version__   = "2.1.0"
__build_year__ = "2025"
APP_NAME      = "Multimedia Master"

# The PDF Manager also ships on its own, built from this same source tree
# (MM_TARGET=pdf — see MultimediaMaster.spec). A product sold on its own must
# not name itself after the suite it was carved out of: a customer who bought
# only the PDF Manager should never see "Multimedia Master" in a title bar or
# an About box, advertising two tools that aren't in their build.
#
# Keys are the EXE `name=` values the spec produces, so adding a standalone
# target means adding its name here too.
_STANDALONE_NAMES = {
    "PdfManager": "PDF Manager",
}


def product_name() -> str:
    """Display name of the running product.

    The full suite — and every dev-mode run, frozen or not — keeps APP_NAME.
    A standalone build reports its own name instead.
    """
    if getattr(sys, "frozen", False):
        return _STANDALONE_NAMES.get(Path(sys.executable).stem, APP_NAME)
    return APP_NAME


def is_standalone() -> bool:
    """True when running as a single-tool product rather than the full suite."""
    return product_name() != APP_NAME
