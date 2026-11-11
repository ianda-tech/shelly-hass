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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from .const import (
    CONF_PROVISIONING_MINUTES,
    DEVICE_LIST_RELATIVE,
    DOMAIN,
    SERVICE_APPLY_PROFILE,
    SERVICE_EXPORT_REPORT,
    SERVICE_IMPORT_ALLOWLIST,
    SERVICE_SET_DIMMER_FADE,
    SERVICE_SET_INPUT_MODE,
    SERVICE_SECURE_DEVICES,
    SERVICE_AUDIT_SECURITY,
    SERVICE_BULK_SET,
    SERVICE_SET_ADVANCED,
    SERVICE_PROVISION_HOTSPOT,
    SERVICE_RETRY_FAILED,
    SERVICE_SCAN_HOTSPOTS,
    SERVICE_START_PROVISIONING,
    SERVICE_STOP_PROVISIONING,
)
from .runtime import FleetRuntime

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

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
        raise ServiceValidationError(f"No Shelly Installer entry named {site}")
    if len(runtimes) == 1:
        return next(iter(runtimes.values()))
    if not runtimes:
        raise ServiceValidationError("Shelly Installer is not set up")
    raise ServiceValidationError("More than one Shelly Installer entry is set up; pass site")


def _reenable_integration_disabled(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Turn entities back on when this integration disabled them.

    A control the user disabled stays off. Home Assistant schedules a reload
    when disabled_by changes, so this must not run on every setup.
    """
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.disabled_by is RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity.entity_id, disabled_by=None)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry before setup. Each step runs once."""
    if entry.version > 1:
        return False
    if entry.minor_version >= 3:
        return True
    if entry.minor_version < 2:
        _reenable_integration_disabled(hass, entry)
    if entry.minor_version < 3:
        from .entity import retire_stale_devices

        retire_stale_devices(hass, entry)
    hass.config_entries.async_update_entry(entry, minor_version=3)
    return True


async def async_remove_config_entry_device(hass: HomeAssistant, config_entry: ConfigEntry, device_entry) -> bool:
    """Let a leftover device be deleted from the device page.

    The Shelly Bulk hub and the current companion of a Shelly that is still
    set up stay. Anything else linked to this entry can be removed.
    """
    from .const import SHELLY_DOMAIN
    from .entity import _current_device

    shelly_ids = {item.entry_id for item in hass.config_entries.async_entries(SHELLY_DOMAIN)}
    return not _current_device(device_entry, config_entry, shelly_ids)


async def async_setup_entry(hass: HomeAssistant, entry: CONFIG_ENTRY) -> bool:
    """Set up Shelly Bulk from a config entry."""
    runtime = FleetRuntime(hass, entry)
    await runtime.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.runtime_data = runtime
    # Register companions before entities. Entity DeviceInfo must not carry
    # via_device, or Home Assistant 2026.11 refuses to add the entity.
    from .entity import ensure_companion_devices

    ensure_companion_devices(hass, entry)
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
            SERVICE_SECURE_DEVICES,
            SERVICE_AUDIT_SECURITY,
            SERVICE_SET_ADVANCED,
            SERVICE_BULK_SET,
            SERVICE_RETRY_FAILED,
            SERVICE_SCAN_HOTSPOTS,
            SERVICE_PROVISION_HOTSPOT,
        ):
            hass.services.async_remove(DOMAIN, service)
    return unloaded


_RELOAD_GUARD: set[str] = set()


async def _reload(hass: HomeAssistant, entry: CONFIG_ENTRY) -> None:
    """Reload once. A write during setup must not start another reload."""
    if entry.entry_id in _RELOAD_GUARD:
        _LOGGER.warning("Skipped a recursive reload of Shelly Installer")
        return
    _RELOAD_GUARD.add(entry.entry_id)
    try:
        await hass.config_entries.async_reload(entry.entry_id)
    finally:
        _RELOAD_GUARD.discard(entry.entry_id)


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
        SERVICE_RETRY_FAILED,
        _retry_failed,
        schema=vol.Schema({vol.Optional("site"): cv.string}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_HOTSPOTS,
        _scan_hotspots,
        schema=vol.Schema({vol.Optional("site"): cv.string}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PROVISION_HOTSPOT,
        _provision_hotspot,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("mac"): cv.string,
                vol.Optional("all"): cv.boolean,
                vol.Optional("dry_run"): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
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
        SERVICE_BULK_SET,
        _bulk_set,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("all"): cv.boolean,
                vol.Optional("all_shelly"): cv.boolean,
                vol.Optional("model"): cv.string,
                vol.Optional("input_type"): cv.string,
                vol.Optional("input_mode"): cv.string,
                vol.Optional("invert"): cv.boolean,
                vol.Optional("initial_state"): cv.string,
                vol.Optional("power_on_state"): cv.string,
                vol.Optional("auto_on"): cv.boolean,
                vol.Optional("auto_off"): cv.boolean,
                vol.Optional("auto_on_delay"): vol.Coerce(float),
                vol.Optional("auto_off_delay"): vol.Coerce(float),
                vol.Optional("fade_rate"): vol.Coerce(int),
                vol.Optional("transition_duration"): vol.Coerce(float),
                vol.Optional("min_brightness"): vol.Coerce(int),
                vol.Optional("max_brightness"): vol.Coerce(int),
                vol.Optional("night_mode"): cv.boolean,
                vol.Optional("night_brightness"): vol.Coerce(int),
                vol.Optional("night_start"): cv.string,
                vol.Optional("night_end"): cv.string,
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
                vol.Optional("filename", default=DEVICE_LIST_RELATIVE): cv.string,
                vol.Optional("replace", default=True): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


    hass.services.async_register(
        DOMAIN,
        SERVICE_SECURE_DEVICES,
        _secure_devices,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("mac"): cv.string,
                vol.Optional("all_shelly"): cv.boolean,
                vol.Optional("rotate_password"): cv.boolean,
                vol.Optional("disable_cloud"): cv.boolean,
                vol.Optional("disable_ap"): cv.boolean,
                vol.Optional("disable_ble_rpc"): cv.boolean,
                vol.Optional("disable_mqtt"): cv.boolean,
                vol.Optional("disable_ws"): cv.boolean,
                vol.Optional("disable_debug"): cv.boolean,
                vol.Optional("firmware_manual"): cv.boolean,
                vol.Optional("restrict_web_ui"): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_AUDIT_SECURITY,
        _audit_security,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("mac"): cv.string,
                vol.Optional("all_shelly"): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ADVANCED,
        _set_advanced,
        schema=vol.Schema(
            {
                vol.Optional("site"): cv.string,
                vol.Optional("mac"): cv.string,
                vol.Optional("all_shelly"): cv.boolean,
                vol.Optional("channel", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
                vol.Optional("bluetooth"): cv.boolean,
                vol.Optional("ble_rpc"): cv.boolean,
                vol.Optional("scanner_mode"): vol.In(["active", "auto", "passive", "disabled"]),
                vol.Optional("cloud"): cv.boolean,
                vol.Optional("access_point"): cv.boolean,
                vol.Optional("mqtt"): cv.boolean,
                vol.Optional("eco_mode"): cv.boolean,
                vol.Optional("status_led"): cv.boolean,
                vol.Optional("debug_logging"): cv.boolean,
                vol.Optional("input_type"): vol.In(["switch", "button"]),
                vol.Optional("input_mode"): cv.string,
                vol.Optional("power_on_state"): cv.string,
                vol.Optional("auto_on"): cv.boolean,
                vol.Optional("auto_off"): cv.boolean,
                vol.Optional("auto_on_delay"): vol.Coerce(float),
                vol.Optional("auto_off_delay"): vol.Coerce(float),
                vol.Optional("fade_rate"): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
                vol.Optional("transition_duration"): vol.Coerce(float),
                vol.Optional("device_name"): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


def _selectors(call: ServiceCall) -> dict[str, Any]:
    return {
        "device_ids": _ids(call.data.get("device_id")),
        "area_ids": _ids(call.data.get("area_id")),
        "mac": call.data.get("mac"),
        "all_shelly": bool(call.data.get("all_shelly")),
        "model_contains": call.data.get("model_contains"),
        "channel": call.data.get("channel") or 0,
    }


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


async def _retry_failed(call: ServiceCall) -> dict[str, Any] | None:
    macs = _runtime(call.hass, call).retry_failed()
    if call.return_response:
        return {"macs": macs, "count": len(macs)}
    return None


async def _scan_hotspots(call: ServiceCall) -> dict[str, Any] | None:
    found = await _runtime(call.hass, call).scan_hotspots()
    if call.return_response:
        return {"count": len(found), "access_points": found}
    return None


async def _provision_hotspot(call: ServiceCall) -> dict[str, Any] | None:
    results = await _runtime(call.hass, call).provision_hotspots(
        mac=call.data.get("mac"),
        all_found=bool(call.data.get("all")),
        dry_run=bool(call.data.get("dry_run")),
    )
    if call.return_response:
        return {"count": len(results), "results": results}
    return None


async def _export(call: ServiceCall) -> dict[str, str] | None:
    paths = await _runtime(call.hass, call).async_export_report(call.data.get("format") or "both")
    if call.return_response:
        return paths
    return None


async def _secure_devices(call: ServiceCall) -> dict[str, Any] | None:
    keys = (
        "rotate_password",
        "disable_cloud",
        "disable_ap",
        "disable_ble_rpc",
        "disable_mqtt",
        "disable_ws",
        "disable_debug",
        "firmware_manual",
        "restrict_web_ui",
    )
    overrides = {key: call.data[key] for key in keys if key in call.data}
    rows = await _runtime(call.hass, call).secure_devices(**_selectors(call), **overrides)
    if call.return_response:
        return {"results": rows}
    return None


async def _audit_security(call: ServiceCall) -> dict[str, Any] | None:
    rows = await _runtime(call.hass, call).audit_devices(**_selectors(call))
    if call.return_response:
        return {"results": rows}
    return None


async def _set_advanced(call: ServiceCall) -> dict[str, Any] | None:
    setting_keys = (
        "bluetooth",
        "ble_rpc",
        "scanner_mode",
        "cloud",
        "access_point",
        "mqtt",
        "eco_mode",
        "status_led",
        "debug_logging",
        "input_type",
        "input_mode",
        "power_on_state",
        "auto_on",
        "auto_off",
        "auto_on_delay",
        "auto_off_delay",
        "fade_rate",
        "transition_duration",
        "device_name",
    )
    settings = {key: call.data[key] for key in setting_keys if key in call.data}
    rows = await _runtime(call.hass, call).set_advanced(settings, **_selectors(call))
    if call.return_response:
        return {"results": rows}
    return None


async def _bulk_set(call: ServiceCall) -> dict[str, int] | None:
    from .groups import DIMMER_FIELDS, select_cards

    runtime = _runtime(call.hass, call)
    cards = runtime.device_cards()
    data = call.data
    if data.get("all") or data.get("all_shelly"):
        chosen = cards
    elif data.get("model"):
        chosen = select_cards(cards, "model", model=str(data["model"]))
    else:
        chosen = []
    device_ids = _ids(data.get("device_id"))
    area_ids = _ids(data.get("area_id"))
    if device_ids or area_ids:
        entries = runtime._select_shelly_entries(
            device_ids=device_ids,
            area_ids=area_ids,
            mac=data.get("mac"),
            all_shelly=False,
            model_contains=None,
        )
        ids = {entry.entry_id for entry in entries}
        picked = [card for card in cards if card.entry_id in ids]
        chosen = [card for card in chosen if card.entry_id in ids] if data.get("model") else picked
    if not chosen:
        raise ServiceValidationError("Choose all, a model, an area, or devices")
    updates = {key: data[key] for key in DIMMER_FIELDS if key in data}
    if "power_on_state" in data and "initial_state" not in updates:
        updates["initial_state"] = data["power_on_state"]
    if "input_mode" in updates:
        updates["input_mode"] = data["input_mode"]
    if not updates:
        raise ServiceValidationError("Choose at least one setting to change")
    started = runtime.start_bulk_apply([card.entry_id for card in chosen], updates)
    if call.return_response:
        return {"started": started}
    return None


async def _import(call: ServiceCall) -> dict[str, int] | None:
    count = await _runtime(call.hass, call).async_import_allowlist(
        str(call.data.get("filename") or DEVICE_LIST_RELATIVE),
        replace=bool(call.data.get("replace", True)),
    )
    if call.return_response:
        return {"count": count}
    return None

