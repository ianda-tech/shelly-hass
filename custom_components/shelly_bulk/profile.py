"""Build Gen2+ RPC calls for a Shelly Bulk profile.

Field names follow the Shelly Gen2 RPC docs (Switch, Input, Light, Sys, Cloud,
WiFi, BLE, Shelly). Fields that differ by model are included only when the
device's current config already exposes them, or are dropped one key at a time
when the device rejects the call.
"""

from __future__ import annotations

from typing import Any

from .const import (
    COMPONENT_NAMESPACES,
    CONF_APPLY_DIMMER_PROFILE,
    CONF_APPLY_INPUT_PROFILE,
    CONF_APPLY_OUTPUT_PROFILE,
    CONF_AUTO_OFF,
    CONF_AUTO_OFF_DELAY,
    CONF_AUTO_ON,
    CONF_AUTO_ON_DELAY,
    CONF_BUTTON_DIMMING,
    CONF_BUTTON_FADE_RATE,
    CONF_INITIAL_STATE,
    CONF_INPUT_INVERT,
    CONF_INPUT_MODE,
    CONF_INPUT_TYPE,
    CONF_MAX_BRIGHTNESS,
    CONF_MIN_BRIGHTNESS,
    CONF_NIGHT_BRIGHTNESS,
    CONF_NIGHT_END,
    CONF_NIGHT_MODE,
    CONF_NIGHT_START,
    CONF_POWER_ON_BRIGHTNESS,
    CONF_TRANSITION_DOWN,
    CONF_TRANSITION_DURATION,
    CONF_TRANSITION_UP,
    DIMMER_COMPONENTS,
    LIGHT_IN_MODES,
    LIGHT_INITIAL_STATES,
    OUTPUT_COMPONENTS,
    POWER_ON_BRIGHTNESS_KEYS,
    RAMP_DOWN_KEYS,
    RAMP_UP_KEYS,
    SWITCH_IN_MODES,
    SWITCH_INITIAL_STATES,
    UNCHANGED,
)
from .models import AllowDevice, ChannelSettings, RpcCall, SecuritySettings, channel_from_dict
from .pairing import InvalidDeviceValue, resolved_pair
from .util import valid_hhmm


def _set(value: Any) -> bool:
    return value not in (None, "", UNCHANGED)


def channel_from_options(options: dict[str, Any]) -> ChannelSettings:
    """Translate the options-flow profile into channel fields.

    Sections the installer has not switched on contribute nothing, so an adopted
    device is not rewritten with placeholder values.
    """
    settings = ChannelSettings()
    if options.get(CONF_APPLY_INPUT_PROFILE):
        if _set(options.get(CONF_INPUT_TYPE)):
            settings.input_type = str(options[CONF_INPUT_TYPE])
        if _set(options.get(CONF_INPUT_MODE)):
            settings.input_mode = str(options[CONF_INPUT_MODE])
        invert = options.get(CONF_INPUT_INVERT)
        if invert == "yes":
            settings.invert = True
        elif invert == "no":
            settings.invert = False
    if options.get(CONF_APPLY_OUTPUT_PROFILE):
        if _set(options.get(CONF_INITIAL_STATE)):
            settings.initial_state = str(options[CONF_INITIAL_STATE])
        settings.auto_on = bool(options.get(CONF_AUTO_ON))
        if options.get(CONF_AUTO_ON_DELAY) not in (None, ""):
            settings.auto_on_delay = float(options[CONF_AUTO_ON_DELAY])
        settings.auto_off = bool(options.get(CONF_AUTO_OFF))
        if options.get(CONF_AUTO_OFF_DELAY) not in (None, ""):
            settings.auto_off_delay = float(options[CONF_AUTO_OFF_DELAY])
    if options.get(CONF_APPLY_DIMMER_PROFILE):
        if options.get(CONF_BUTTON_FADE_RATE) not in (None, ""):
            settings.fade_rate = int(options[CONF_BUTTON_FADE_RATE])
        if options.get(CONF_TRANSITION_DURATION) not in (None, ""):
            settings.transition = float(options[CONF_TRANSITION_DURATION])
        if options.get(CONF_TRANSITION_UP) not in (None, ""):
            settings.transition_up = float(options[CONF_TRANSITION_UP])
        if options.get(CONF_TRANSITION_DOWN) not in (None, ""):
            settings.transition_down = float(options[CONF_TRANSITION_DOWN])
        if options.get(CONF_MIN_BRIGHTNESS) not in (None, ""):
            settings.min_brightness = int(options[CONF_MIN_BRIGHTNESS])
        if options.get(CONF_MAX_BRIGHTNESS) not in (None, ""):
            settings.max_brightness = int(options[CONF_MAX_BRIGHTNESS])
        night = options.get(CONF_NIGHT_MODE)
        if night == "on":
            settings.night_mode = True
        elif night == "off":
            settings.night_mode = False
        if options.get(CONF_NIGHT_BRIGHTNESS) not in (None, ""):
            settings.night_brightness = int(options[CONF_NIGHT_BRIGHTNESS])
        if _set(options.get(CONF_NIGHT_START)):
            settings.night_start = str(options[CONF_NIGHT_START])
        if _set(options.get(CONF_NIGHT_END)):
            settings.night_end = str(options[CONF_NIGHT_END])
        if options.get(CONF_POWER_ON_BRIGHTNESS) not in (None, ""):
            settings.power_on_brightness = int(options[CONF_POWER_ON_BRIGHTNESS])
        if _set(options.get(CONF_BUTTON_DIMMING)):
            settings.button_dimming = str(options[CONF_BUTTON_DIMMING])
    return settings


def security_from_entry(
    data: dict[str, Any],
    options: dict[str, Any],
    device_name: str = "",
) -> SecuritySettings:
    """Security flags live in options; timezone is config-entry data."""
    return SecuritySettings(
        disable_cloud=bool(options.get("disable_cloud")),
        disable_ap=bool(options.get("disable_ap")),
        disable_ble_rpc=bool(options.get("disable_ble_rpc", True)),
        timezone=str(data.get("timezone") or ""),
        device_name=device_name,
    )


def _split_component(key: str) -> tuple[str, int] | None:
    name, separator, index = key.partition(":")
    if not separator or name not in COMPONENT_NAMESPACES or not index.isdigit():
        return None
    return name, int(index)


def _map_in_mode(mode: str | None, kind: str, notes: list[str], label: str) -> str | None:
    if not mode:
        return None
    requested = mode.lower()
    if kind in DIMMER_COMPONENTS and requested == "momentary":
        notes.append(
            f"{label}: momentary is not a {kind} in_mode; using dim "
            "(short press toggles, hold dims)"
        )
        requested = "dim"
    allowed = LIGHT_IN_MODES if kind in DIMMER_COMPONENTS else SWITCH_IN_MODES
    if kind == "input":
        return None
    if requested not in allowed:
        notes.append(f"{label}: in_mode {requested!r} is not valid for {kind}; skipped")
        return None
    return requested


def _output_config(kind: str, settings: ChannelSettings, existing: dict[str, Any], notes: list[str], label: str) -> dict[str, Any]:
    config: dict[str, Any] = {}
    mode = settings.button_dimming if kind in DIMMER_COMPONENTS and settings.button_dimming else settings.input_mode
    mapped = _map_in_mode(mode, kind, notes, label)
    if mapped:
        config["in_mode"] = mapped
    if settings.initial_state:
        allowed = LIGHT_INITIAL_STATES if kind in DIMMER_COMPONENTS else SWITCH_INITIAL_STATES
        if settings.initial_state in allowed:
            config["initial_state"] = settings.initial_state
        else:
            notes.append(
                f"{label}: initial_state {settings.initial_state!r} is not valid for {kind}; skipped"
            )
    if config.get("in_mode") or config.get("initial_state"):
        try:
            paired_mode, paired_initial, note = resolved_pair(
                kind,
                existing.get("in_mode"),
                existing.get("initial_state"),
                new_mode=config.get("in_mode"),
                new_initial=config.get("initial_state"),
            )
        except InvalidDeviceValue as err:
            notes.append(f"{label}: {err}")
            config.pop("in_mode", None)
            config.pop("initial_state", None)
        else:
            config["in_mode"] = paired_mode
            config["initial_state"] = paired_initial
            if note:
                notes.append(f"{label}: {note}")
    if settings.auto_on is not None:
        config["auto_on"] = settings.auto_on
    if settings.auto_on_delay is not None:
        config["auto_on_delay"] = settings.auto_on_delay
    if settings.auto_off is not None:
        config["auto_off"] = settings.auto_off
    if settings.auto_off_delay is not None:
        config["auto_off_delay"] = settings.auto_off_delay
    if kind not in DIMMER_COMPONENTS:
        return config
    if settings.fade_rate is not None:
        if 1 <= int(settings.fade_rate) <= 5:
            config["button_fade_rate"] = int(settings.fade_rate)
        else:
            notes.append(f"{label}: button_fade_rate must be 1-5; skipped")
    if settings.transition is not None:
        config["transition_duration"] = settings.transition
    _apply_split_ramps(config, settings, existing, notes, label)
    if settings.min_brightness is not None and settings.max_brightness is not None:
        low = int(settings.min_brightness)
        high = int(settings.max_brightness)
        if 0 <= low < high <= 100:
            config["range_map"] = [low, high]
        else:
            notes.append(f"{label}: brightness range must be 0-100 with min < max; skipped")
    elif settings.min_brightness is not None or settings.max_brightness is not None:
        notes.append(f"{label}: min and max brightness must both be set; range_map skipped")
    if settings.night_mode is True:
        start = settings.night_start or ""
        end = settings.night_end or ""
        night: dict[str, Any] = {"enable": True}
        if settings.night_brightness is not None:
            night["brightness"] = int(settings.night_brightness)
        if valid_hhmm(start) and valid_hhmm(end):
            night["active_between"] = [start, end]
            config["night_mode"] = night
        else:
            notes.append(f"{label}: night mode needs start and end as HH:MM; skipped")
    elif settings.night_mode is False:
        config["night_mode"] = {"enable": False}
    if settings.power_on_brightness is not None:
        for key in POWER_ON_BRIGHTNESS_KEYS:
            if key in existing:
                config[key] = int(settings.power_on_brightness)
                break
        else:
            notes.append(
                f"{label}: power-on brightness is not a field on this component "
                "(checked power_on_brightness, initial_brightness, brightness); not sent"
            )
    return config


def _apply_split_ramps(
    config: dict[str, Any],
    settings: ChannelSettings,
    existing: dict[str, Any],
    notes: list[str],
    label: str,
) -> None:
    if settings.transition_up is None and settings.transition_down is None:
        return
    up_key = next((key for key in RAMP_UP_KEYS if key in existing), None)
    down_key = next((key for key in RAMP_DOWN_KEYS if key in existing), None)
    if up_key and settings.transition_up is not None:
        config[up_key] = settings.transition_up
    if down_key and settings.transition_down is not None:
        config[down_key] = settings.transition_down
    if up_key or down_key:
        return
    notes.append(
        f"{label}: this component has no separate ramp up/down field "
        "(looked for transition_duration_up/down and ramp_up/down); "
        "transition_duration is the verified ramp"
    )
    if CONF_TRANSITION_DURATION not in config and "transition_duration" not in config:
        if settings.transition is None and settings.transition_up is not None:
            config["transition_duration"] = settings.transition_up


def plan_security_calls(security: SecuritySettings) -> list[RpcCall]:
    """Calls that harden a device after it has joined Wi-Fi.

    Home Assistant's own BLE flow always turns the AP and BLE RPC off. Passing
    the installer's choice here puts them back if they were unchecked.
    """
    calls: list[RpcCall] = []
    sys_config: dict[str, Any] = {}
    if security.device_name:
        sys_config["device"] = {"name": security.device_name}
    if security.timezone:
        sys_config["location"] = {"tz": security.timezone}
    if sys_config:
        calls.append(RpcCall("Sys.SetConfig", {"config": sys_config}, "system"))
    if security.disable_cloud:
        calls.append(RpcCall("Cloud.SetConfig", {"config": {"enable": False}}, "cloud"))
    calls.append(
        RpcCall(
            "WiFi.SetConfig",
            {"config": {"ap": {"enable": not security.disable_ap}}},
            "wifi access point",
        )
    )
    calls.append(
        RpcCall(
            "BLE.SetConfig",
            {
                "config": {
                    "enable": True,
                    "rpc": {"enable": not security.disable_ble_rpc},
                }
            },
            "bluetooth",
        )
    )
    return calls


def plan_channel_calls(
    config: dict[str, Any],
    base: ChannelSettings,
    device: AllowDevice | None,
) -> tuple[list[RpcCall], list[str]]:
    """Plan Input/Switch/Light/RGB/RGBW/CCT updates from merged channel settings."""
    calls: list[RpcCall] = []
    notes: list[str] = []
    for key, existing in config.items():
        parsed = _split_component(key)
        if parsed is None or not isinstance(existing, dict):
            continue
        kind, index = parsed
        settings = device.settings_for(index, base) if device else base
        if settings.is_empty():
            continue
        namespace = COMPONENT_NAMESPACES[kind]
        label = f"{kind}:{index}"
        if kind == "input":
            payload: dict[str, Any] = {}
            if settings.input_type in {"switch", "button"}:
                payload["type"] = settings.input_type
            elif settings.input_type:
                notes.append(f"{label}: input type {settings.input_type!r} is not switch or button; skipped")
            if settings.invert is not None:
                payload["invert"] = settings.invert
            if payload:
                calls.append(
                    RpcCall(f"{namespace}.SetConfig", {"id": index, "config": payload}, label)
                )
            continue
        if kind not in OUTPUT_COMPONENTS:
            continue
        payload = _output_config(kind, settings, existing, notes, label)
        if payload:
            calls.append(RpcCall(f"{namespace}.SetConfig", {"id": index, "config": payload}, label))
    return calls, notes


def plan_config_calls(
    *,
    security: SecuritySettings | None,
    options: dict[str, Any],
    config: dict[str, Any],
    device: AllowDevice | None,
) -> tuple[list[RpcCall], list[str]]:
    """Return the RPC plan for one device. Authentication and firmware are separate."""
    calls: list[RpcCall] = []
    if security is not None:
        calls.extend(plan_security_calls(security))
    channel_calls, notes = plan_channel_calls(config, channel_from_options(options), device)
    calls.extend(channel_calls)
    return calls, notes


def build_set_auth(device_id: str, password: str) -> dict[str, str]:
    """Build Shelly.SetAuth params. The password is hashed and not returned."""
    import hashlib

    digest = hashlib.sha256(f"admin:{device_id}:{password}".encode()).hexdigest()
    return {"user": "admin", "realm": device_id, "ha1": digest}


def channel_override_from_mapping(data: dict[str, Any]) -> ChannelSettings:
    """Build channel settings from a service payload."""
    return channel_from_dict(data)
