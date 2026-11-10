"""Redact site secrets before they reach logs, diagnostics, or reports."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable, Iterable


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace known secret values with a fixed mask.

    Very short values are left alone so a 1-2 character password cannot blank
    ordinary words. Callers should still avoid logging secrets in the first place.
    """
    cleaned = [secret for secret in secrets if isinstance(secret, str) and len(secret) >= 4]
    for secret in sorted(set(cleaned), key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


class SecretFilter(logging.Filter):
    """Logging filter that masks whatever the provider currently considers secret."""

    def __init__(self, provider: Callable[[], Iterable[str]]) -> None:
        super().__init__()
        self._provider = provider

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            secrets = list(self._provider())
            record.msg = redact(record.getMessage(), secrets)
            record.args = ()
            if record.exc_info:
                record.exc_text = redact(
                    "".join(traceback.format_exception(*record.exc_info)),
                    secrets,
                )
                record.exc_info = None
        except Exception:  # noqa: BLE001 - never break logging
            return True
        return True
