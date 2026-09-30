"""
Frozen-build-aware path helpers.

A PyInstaller onefile build extracts bundled files to a temporary directory
(sys._MEIPASS) that is deleted the moment the process exits — fine for
reading bundled source/resources, useless for anything that must persist
(crash logs, settings). exe_dir() always resolves to the directory next to
the real .exe, stable across runs, in both dev mode and frozen builds
(onefile or onedir).
"""
from __future__ import annotations

import sys
from pathlib import Path


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # tools/common/paths.py -> repo root
    return Path(__file__).resolve().parent.parent.parent


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (assets/).

    NOT the same as exe_dir(). PyInstaller unpacks bundled data to
    sys._MEIPASS, which is a temporary directory in a onefile build and the
    _internal/ subfolder next to the exe in a onedir build — in neither case
    the directory the exe itself sits in. Resolving a bundled asset against
    exe_dir() therefore yields a path that does not exist, and callers that
    treat a missing asset as cosmetic (see common.ui.icon) then fail without
    saying anything.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else exe_dir()


def _data_dir_name() -> str:
    """Per-user data folder name, distinct for each product built from this
    source tree, so two installed products never share a log directory — and
    so one product's folder never carries another's name."""
    if getattr(sys, "frozen", False):
        # The exe's own name, which the spec sets per product.
        return Path(sys.executable).stem
    from common.version import PRODUCT_SLUG
    return PRODUCT_SLUG


def icon_path() -> Path:
    """Path to the app icon, stable across dev mode and frozen builds."""
    return resource_dir() / "assets" / "icon.ico"


def _user_log_dir() -> Path:
    """Per-user log directory, for builds that must not write beside the exe."""
    from common.version import PRODUCT_SLUG
    return Path.home() / f".{PRODUCT_SLUG}" / "logs"


def crash_log_path(tool_name: str) -> Path:
    """Stable, writable crash-log location for `tool_name`."""
    if getattr(sys, "frozen", False):
        from common.version import IS_ONEFILE
        if IS_ONEFILE:
            # A single-file build is meant to be dropped anywhere — the
            # desktop, a USB stick, Downloads. Writing a logs\ folder beside
            # it would litter whatever directory the user picked, so logs go
            # to the per-user data folder alongside settings instead.
            log_dir = _user_log_dir()
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                return log_dir / f"{tool_name}_crash.log"
            except OSError:
                pass   # fall through to the temp-dir fallback below
        log_dir = exe_dir() / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir / f"{tool_name}_crash.log"
        except OSError:
            # exe installed to a read-only location (e.g. Program Files
            # without admin rights) — fall back to a per-user writable dir
            # rather than crash before the crash logger even exists.
            import tempfile
            fallback = Path(tempfile.gettempdir()) / _data_dir_name() / "logs"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback / f"{tool_name}_crash.log"
    return exe_dir() / "tools" / tool_name / "crash.log"
