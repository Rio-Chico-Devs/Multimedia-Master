"""
Frozen-build-aware "missing dependency" messages.

In dev mode a `pip install X` instruction is actionable. In a compiled exe
there is no Python environment for the customer to run pip in — telling
them to do so is just confusing. pip_hint() picks the right tail message
for whichever mode is currently running.
"""
from __future__ import annotations

import sys


def pip_hint(packages: str) -> str:
    if getattr(sys, "frozen", False):
        return "funzione non disponibile in questa build (componente opzionale mancante)"
    return f"esegui: pip install {packages}"
