"""
Minimal offline license-key system — checksum-based, no network calls.

This is intentionally lightweight: anyone who extracts _SECRET from the
distributed exe can forge valid keys. It's a purchase deterrent for
solo/small customers, not DRM. If stronger protection is ever needed,
swap the checksum for a signed scheme (e.g. Ed25519) without touching the
call sites below — is_activated()/activate() stay the same.

Key format:  <SLUG>-<CHECKSUM>
  SLUG       derived from a customer identifier (email, name, order id...)
  CHECKSUM   8 hex chars = sha256(SLUG + SECRET)[:8]

App side (not wired into startup yet — call this where you want to gate):
    from common.license import is_activated, activate

    if not is_activated():
        key = ask_user_for_key()   # your own dialog
        if not activate(key):
            show_error("Chiave non valida")

Seller side, to issue a key for a new customer:
    python -m common.license generate "customer@example.com"
"""
from __future__ import annotations

import hashlib
import sys

from common.settings import Settings

# Not a real secret — embedded in the distributed app. See module docstring.
_SECRET = "multimedia-master-2025-license-salt"

_settings = Settings("license")


def _checksum(slug: str) -> str:
    return hashlib.sha256(f"{slug}{_SECRET}".encode("utf-8")).hexdigest()[:8].upper()


def _slugify(identifier: str) -> str:
    slug = "".join(c for c in identifier.upper() if c.isalnum())[:12]
    return slug or "USER"


def generate_key(identifier: str) -> str:
    """Issue a license key for `identifier` (e.g. customer email)."""
    slug = _slugify(identifier)
    return f"{slug}-{_checksum(slug)}"


def verify_key(key: str) -> bool:
    """Check a key's checksum — no disk access."""
    key = key.strip().upper()
    if "-" not in key:
        return False
    slug, _, checksum = key.rpartition("-")
    return bool(slug) and _checksum(slug) == checksum


def is_activated() -> bool:
    key = _settings.get("key", "")
    return bool(key) and verify_key(key)


def activate(key: str) -> bool:
    """Validate and persist `key`. Returns False without saving if invalid."""
    if not verify_key(key):
        return False
    _settings.set(key=key.strip().upper())
    return True


def deactivate() -> None:
    _settings.set(key="")


if __name__ == "__main__":
    # Seller-side CLI: python -m common.license generate <customer-identifier>
    if len(sys.argv) == 3 and sys.argv[1] == "generate":
        print(generate_key(sys.argv[2]))
    else:
        print("Usage: python -m common.license generate <customer-identifier>")
