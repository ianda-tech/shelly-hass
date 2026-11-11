"""Consumption type and device profile.

Consumption type is UI data. Home Assistant's Shelly integration shows a relay
as a light when the value starts with "light", and as a switch otherwise.
Changing it does not reboot the device.

A device profile (switch or cover on a 2PM, for example) is listed by
Shelly.ListProfiles. Shelly.SetProfile reboots the device by itself when the
profile actually changes. This module never calls Shelly.Reboot.
"""

from __future__ import annotations

from typing import Any

CONSUMPTION_TYPES: tuple[str, ...] = (
    "switch",
    "light",
    "fan",
    "socket",
    "outlet",
    "heating",
    "refrigeration",
    "other",
)

CONSUMPTION_LABELS: dict[str, str] = {
    "switch": "Switch",
    "light": "Light",
    "fan": "Fan",
    "socket": "Socket",
    "outlet": "Outlet",
    "heating": "Heating",
    "refrigeration": "Refrigeration",
    "other": "Other",
}


def normalize_consumption(value: Any) -> str:
    """Map an empty cell to switch. Home Assistant treats a blank the same way."""
    text = str(value or "").strip().lower()
    return text or "switch"


def switch_channels(config: dict[str, Any]) -> list[int]:
    """Return switch component ids present in a Shelly config."""
    found: list[int] = []
    for key in config:
        prefix, separator, index = key.partition(":")
        if prefix == "switch" and separator and index.isdigit():
            found.append(int(index))
    return sorted(found)


def channel_consumption(types: list[Any], channel: int) -> str:
    if channel < 0 or channel >= len(types):
        return "switch"
    return normalize_consumption(types[channel])


def consumption_list_with(types: list[Any], channel: int, value: str) -> list[str] | None:
    """Return the full list to write, or None when this channel already matches."""
    wanted = normalize_consumption(value)
    if channel_consumption(types, channel) == wanted:
        return None
    updated = [normalize_consumption(item) for item in types]
    while len(updated) <= channel:
        updated.append("switch")
    updated[channel] = wanted
    return updated


def site_default_output(options: dict[str, Any] | None) -> str:
    """Site default consumption type. Missing or unknown values mean light."""
    raw = str((options or {}).get("default_output_type") or "").strip().lower()
    return raw if raw in CONSUMPTION_TYPES else "light"


async def apply_default_output(session: Any, default: str, overrides: set[int]) -> bool:
    """Set every switch channel to the site default except ones the user overrode.

    Writes only when a channel differs. Does not reboot the device.
    """
    config = dict(getattr(session, "config", {}) or {})
    channels = [channel for channel in switch_channels(config) if channel not in overrides]
    if not channels:
        return False
    sys_cfg = await session.call("Sys.GetConfig")
    if not isinstance(sys_cfg, dict):
        sys_cfg = {}
    ui = sys_cfg.get("ui_data")
    ui = dict(ui) if isinstance(ui, dict) else {}
    current = ui.get("consumption_types")
    working = list(current) if isinstance(current, list) else []
    changed = False
    for channel in channels:
        updated = consumption_list_with(working, channel, default)
        if updated is None:
            continue
        working = updated
        changed = True
    if not changed:
        return False
    ui["consumption_types"] = working
    await session.call("Sys.SetConfig", {"config": {"ui_data": ui}})
    return True


def profile_names(payload: Any) -> list[str]:
    """Names from Shelly.ListProfiles. One name, or a failed call, means no choice."""
    if not isinstance(payload, dict):
        return []
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or len(profiles) < 2:
        return []
    return sorted(str(name) for name in profiles)


async def write_consumption(session: Any, channel: int, value: str) -> tuple[str | None, bool]:
    """Set one switch channel's consumption type. Skip the write when it matches.

    The string is None when the device has no switch on that channel.
    The bool is True only when Sys.SetConfig was sent. This never reboots.
    """
    config = dict(getattr(session, "config", {}) or {})
    if channel not in switch_channels(config):
        return None, False
    sys_cfg = await session.call("Sys.GetConfig")
    if not isinstance(sys_cfg, dict):
        sys_cfg = {}
    ui = sys_cfg.get("ui_data")
    ui = dict(ui) if isinstance(ui, dict) else {}
    current = ui.get("consumption_types")
    current_list = list(current) if isinstance(current, list) else []
    updated = consumption_list_with(current_list, channel, value)
    if updated is None:
        return channel_consumption(current_list, channel), False
    ui["consumption_types"] = updated
    await session.call("Sys.SetConfig", {"config": {"ui_data": ui}})
    return normalize_consumption(value), True


async def write_profile(session: Any, name: str) -> bool:
    """Change profile only when the device lists it and it is not already active.

    Shelly reboots itself after a real change. Returns True when SetProfile was sent.
    """
    wanted = str(name or "").strip()
    if not wanted:
        return False
    info = await session.call("Shelly.GetDeviceInfo")
    current = str(info.get("profile") or "") if isinstance(info, dict) else ""
    try:
        listed = await session.call("Shelly.ListProfiles")
    except Exception:
        return False
    if wanted not in profile_names(listed) or wanted == current:
        return False
    await session.call("Shelly.SetProfile", {"name": wanted})
    return True
