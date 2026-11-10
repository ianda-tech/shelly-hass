"""Small pure helpers shared by the integration."""

from __future__ import annotations

import re
from typing import Any


_HEX = frozenset("0123456789ABCDEF")
_SLUG = re.compile(r"[^a-z0-9]+")
_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def normalize_mac(value: str) -> str:
    """Return a 12-character upper-case MAC with no separators."""
    compact = "".join(char for char in value.upper() if char in _HEX)
    if len(compact) != 12:
        raise ValueError(f"invalid MAC: {value!r}")
    return compact


def display_mac(value: str) -> str:
    """Return a colon-separated MAC."""
    compact = normalize_mac(value)
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def slugify(value: str) -> str:
    """Return a stable id fragment."""
    slug = _SLUG.sub("-", value.strip().lower()).strip("-")
    return slug or "site"


def valid_hhmm(value: str) -> bool:
    """Return True for an HH:MM clock value Shelly accepts."""
    return bool(_HHMM.match(value.strip()))


def parse_bool(value: str | None) -> bool | None:
    """Parse a CSV boolean. Empty or unknown values stay unset."""
    if value is None:
        return None
    text = value.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def parse_number(value: str | None) -> float | None:
    """Parse a CSV number. Empty stays unset."""
    if value is None or not str(value).strip():
        return None
    return float(str(value).strip())


def coerce_number(value: Any) -> float | None:
    """Coerce a config-flow number, treating blanks as unset."""
    if value is None or value == "":
        return None
    return float(value)


def as_int(value: Any) -> int | None:
    """Return an int when the value is a whole number."""
    number = coerce_number(value)
    if number is None:
        return None
    if not number.is_integer():
        raise ValueError(f"expected a whole number, got {value!r}")
    return int(number)
