"""Pytest setup for the Shelly Bulk custom integration."""

from __future__ import annotations

pytest_plugins = "pytest_homeassistant_custom_component"

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
