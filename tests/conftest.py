"""Pytest setup for the Shelly Bulk custom integration."""

from __future__ import annotations

import logging

import pytest

# Home Assistant 2026.11 logs these device-registry deprecations for a custom
# integration and raises when it cannot name the integration. Either way the
# suite should fail, which is what caught the 2026.11 entity-add outage.
_DEPRECATED_MARKERS = (
    "deprecated `via_device`",
    "async_get_device`, which is deprecated",
    "merge_connections",
    "merge_identifiers",
)


class _RegistryDeprecations(logging.Handler):
    """Collect device-registry deprecation logs so the test can fail on them."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if any(marker in message for marker in _DEPRECATED_MARKERS):
            self.messages.append(message)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def device_registry_deprecations_are_errors():
    """Fail the test when Home Assistant reports a deprecated device-registry call."""
    handler = _RegistryDeprecations()
    logger = logging.getLogger("homeassistant")
    logger.addHandler(handler)
    yield
    logger.removeHandler(handler)
    if handler.messages:
        pytest.fail("Deprecated device registry API:\n" + "\n".join(handler.messages))
