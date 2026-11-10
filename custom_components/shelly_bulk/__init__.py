"""Shelly Bulk: bulk Bluetooth adoption beside Home Assistant's Shelly integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_PROVISIONING_MINUTES,
    DOMAIN,
    SERVICE_APPLY_PROFILE,
    SERVICE_EXPORT_REPORT,
    SERVICE_IMPORT_ALLOWLIST,
    SERVICE_SET_DIMMER_FADE,
    SERVICE_SET_INPUT_MODE,
    SERVICE_START_PROVISIONING,
    SERVICE_STOP_PROVISIONING,
)
from .runtime import FleetRuntime

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

CONFIG_ENTRY = ConfigEntry[FleetRuntime]


def _ids(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _runtime(hass: HomeAssistant, call: ServiceCall) -> FleetRuntime:
    runtimes: dict[str, FleetRuntime] = hass.data.get(DOMAIN, {})
    site = call.data.get("site")
    if site:
        for runtime in runtimes.values():
            if runtime.site_name == site:
                return runtime
        raise ServiceValidationError(f"No Shelly Bulk entry named {site}")
    if len(runtimes) == 1:
        return next(iter(runtimes.values()))
    if not runtimes:
        raise ServiceValidationError("Shelly Bulk is not set up")
    raise ServiceValidationError("More than one Shelly Bulk entry is set up; pass site")


async def async_setup_entry(hass: HomeAssistant, entry: CONFIG_ENTRY) -> bool:
    """Set up Shelly Bulk from a config entry."""
    runtime = FleetRuntime(hass, entry)
    await runtime.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CONFIG_ENTRY) -> bool:
    """Unload a config entry."""
    runtime: FleetRuntime | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime is not None:
        await runtime.async_close()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not hass.data.get(DOMAIN):
        for service in (
            SERVICE_APPLY_PROFILE,
            SERVICE_SET_INPUT_MODE,
            SERVICE_SET_DIMMER_FADE,
            SERVICE_START_PROVISIONING,
            SERVICE_STOP_PROVISIONING,
            SERVICE_EXPORT_REPORT,
            SERVICE_IMPORT_ALLOWLIST,
        ):
            hass.services.async_remove(DOMAIN, service)
    return unloaded


async def _reload(hass: HomeAssistant, entry: CONFIG_ENTRY) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_APPLY_PROFILE):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_PROFILE,
        _apply_profile,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("mac"): cv.string,
                vol.Optional("all_shelly"): cv.boolean,
                vol.Optional("model_contains"): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_INPUT_MODE,
        _set_input_mode,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("mac"): cv.string,
                vol.Optional("input_id", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
                vol.Optional("input_type"): vol.In(["switch", "button"]),
                vol.Optional("input_mode"): vol.In(
                    ["follow", "flip", "momentary", "detached", "activate", "dim", "dual_dim"]
                ),
                vol.Optional("invert"): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DIMMER_FADE,
        _set_dimmer_fade,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("mac"): cv.string,
                vol.Optional("channel", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
                vol.Optional("fade_rate"): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
                vol.Optional("transition_duration"): vol.All(vol.Coerce(float), vol.Range(min=0, max=10800)),
                vol.Optional("transition_up"): vol.All(vol.Coerce(float), vol.Range(min=0, max=10800)),
                vol.Optional("transition_down"): vol.All(vol.Coerce(float), vol.Range(min=0, max=10800)),
            },
            extra=vol.ALLOW_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_PROVISIONING,
        _start,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional(CONF_PROVISIONING_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=180)
                ),
            },
            extra=vol.ALLOW_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_PROVISIONING,
        _stop,
        schema=vol.Schema({vol.Optional("site"): cv.string}, extra=vol.ALLOW_EXTRA),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_REPORT,
        _export,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("format", default="both"): vol.In(["csv", "json", "both"]),
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_ALLOWLIST,
        _import,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Required("filename"): cv.string,
                vol.Optional("replace", default=True): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


async def _apply_profile(call: ServiceCall) -> dict[str, Any] | None:
    runtime = _runtime(call.hass, call)
    rows = await runtime.apply_profile(
        device_ids=_ids(call.data.get("device_id")),
        area_ids=_ids(call.data.get("area_id")),
        mac=call.data.get("mac"),
        all_shelly=bool(call.data.get("all_shelly")),
        model_contains=call.data.get("model_contains"),
    )
    if call.return_response:
        return {"results": rows}
    return None


async def _set_input_mode(call: ServiceCall) -> None:
    runtime = _runtime(call.hass, call)
    await runtime.set_input_mode(
        device_ids=_ids(call.data.get("device_id")),
        area_ids=_ids(call.data.get("area_id")),
        mac=call.data.get("mac"),
        input_id=int(call.data.get("input_id") or 0),
        input_type=call.data.get("input_type"),
        input_mode=call.data.get("input_mode"),
        invert=call.data.get("invert"),
    )


async def _set_dimmer_fade(call: ServiceCall) -> None:
    runtime = _runtime(call.hass, call)
    fade = call.data.get("fade_rate")
    await runtime.set_dimmer_fade(
        device_ids=_ids(call.data.get("device_id")),
        area_ids=_ids(call.data.get("area_id")),
        mac=call.data.get("mac"),
        channel=int(call.data.get("channel") or 0),
        fade_rate=None if fade is None else int(fade),
        transition=call.data.get("transition_duration"),
        transition_up=call.data.get("transition_up"),
        transition_down=call.data.get("transition_down"),
    )


async def _start(call: ServiceCall) -> None:
    runtime = _runtime(call.hass, call)
    minutes = call.data.get(CONF_PROVISIONING_MINUTES)
    await runtime.start_provisioning(None if minutes is None else float(minutes))


async def _stop(call: ServiceCall) -> None:
    await _runtime(call.hass, call).stop_provisioning()


async def _export(call: ServiceCall) -> dict[str, str] | None:
    paths = await _runtime(call.hass, call).async_export_report(call.data.get("format") or "both")
    if call.return_response:
        return paths
    return None


async def _import(call: ServiceCall) -> dict[str, int] | None:
    count = await _runtime(call.hass, call).async_import_allowlist(
        str(call.data["filename"]),
        replace=bool(call.data.get("replace", True)),
    )
    if call.return_response:
        return {"count": count}
    return None

