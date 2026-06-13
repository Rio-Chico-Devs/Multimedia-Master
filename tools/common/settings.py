"""
Persistent application settings — shared by every Multimedia Master tool.

A single JSON file lives at ~/.multimedia_master/settings.json. Each tool reads
and writes its own namespace (e.g. "image_converter", "audio_manager"), so keys
from different tools never collide.

Design goals:
  • Never raise. A missing/corrupt file yields defaults; a failed write is
    swallowed. Persistence is a convenience, not a correctness requirement.
  • Atomic writes. We write to a temp file and os.replace() it so a crash
    mid-write can't truncate the existing settings.
  • Thread-safe. A module-level lock guards the read-modify-write cycle, since
    several tabs may persist concurrently from background threads.

Usage:
    from common.settings import Settings
    s = Settings("image_converter")
    fmt = s.get("last_format", "WebP")
    s.set(last_format="JPEG", quality=90)   # persisted immediately
    s.add_recent("/path/to/folder")         # bounded MRU list under "recent"
    for p in s.get_recent():
        ...
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_CONFIG_DIR  = Path.home() / ".multimedia_master"
_CONFIG_FILE = _CONFIG_DIR / "settings.json"
_LOCK        = threading.RLock()
_RECENT_MAX  = 12


def _load_all() -> dict[str, Any]:
    try:
        with _CONFIG_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_all(data: dict[str, Any]) -> None:
    """Atomically persist the whole settings document."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_CONFIG_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, _CONFIG_FILE)
        finally:
            # If replace succeeded the temp is gone; this only fires on error.
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        pass


class Settings:
    """Namespaced view over the shared settings file for a single tool."""

    def __init__(self, namespace: str):
        self._ns = namespace

    # ── Scalar values ─────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        with _LOCK:
            return _load_all().get(self._ns, {}).get(key, default)

    def set(self, **kwargs: Any) -> None:
        """Persist one or more key/value pairs in this tool's namespace."""
        with _LOCK:
            data = _load_all()
            section = data.setdefault(self._ns, {})
            section.update(kwargs)
            _save_all(data)

    # ── Recent-items MRU list ─────────────────────────────────────────────────

    def get_recent(self, key: str = "recent") -> list[str]:
        val = self.get(key, [])
        return list(val) if isinstance(val, list) else []

    def add_recent(self, item: str, key: str = "recent",
                   limit: int = _RECENT_MAX) -> None:
        """Push item to the front of an MRU list, de-duplicated and capped."""
        item = str(item)
        with _LOCK:
            data = _load_all()
            section = data.setdefault(self._ns, {})
            lst = [x for x in section.get(key, []) if x != item]
            lst.insert(0, item)
            section[key] = lst[:limit]
            _save_all(data)

    def clear_recent(self, key: str = "recent") -> None:
        self.set(**{key: []})
