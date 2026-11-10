"""Diagnostics with site secrets removed."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import CONF_FLEET_PASSWORD, CONF_WIFI_PASSWORD, CONF_WIFI_SSID, DOMAIN
from .runtime import FleetRuntime


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry
) -> dict[str, Any]:
    runtime: FleetRuntime = hass.data[DOMAIN][entry.entry_id]
    data = dict(entry.data)
    for key in (CONF_WIFI_SSID, CONF_WIFI_PASSWORD, CONF_FLEET_PASSWORD):
        if data.get(key):
            data[key] = "***"
    recent = []
    for row in runtime.results[-20:]:
        cleaned = dict(row)
        if cleaned.get("error"):
            cleaned["error"] = runtime.redact(str(cleaned["error"]))
        recent.append(cleaned)
    return {
        "data": data,
        "options": dict(entry.options),
        "adopted": runtime.adopted,
        "failed": runtime.failed,
        "pending": runtime.pending,
        "last_error": runtime.redact(runtime.last_error),
        "allowlist_count": len(runtime.allowlist.devices),
        "provisioning_active": runtime.provisioning_active,
        "recent": recent,
    }
