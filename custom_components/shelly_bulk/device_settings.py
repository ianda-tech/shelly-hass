"""Read and write the settings shown when editing one adopted Shelly.

A field is offered only when the device's own GetConfig already contains it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .advanced import write_setting
from .const import DIMMER_COMPONENTS

# Channel settings that can be copied onto other devices. Name and room stay put.
CHANNEL_KEYS = (
    "input_type",
    "input_mode",
    "invert",
    "initial_state",
    "auto_on",
    "auto_on_delay",
    "auto_off",
    "auto_off_delay",
    "fade_rate",
    "transition_duration",
    "transition_up",
    "transition_down",
    "min_brightness",
    "max_brightness",
    "night_mode",
    "night_brightness",
    "night_start",
    "night_end",
)

_OUTPUT_KEYS = {
    "input_mode": "in_mode",
    "initial_state": "initial_state",
    "auto_on": "auto_on",
    "auto_on_delay": "auto_on_delay",
    "auto_off": "auto_off",
    "auto_off_delay": "auto_off_delay",
    "fade_rate": "button_fade_rate",
    "transition_duration": "transition_duration",
}
_NAMESPACES = {"switch": "Switch", "light": "Light", "rgb": "RGB", "rgbw": "RGBW", "cct": "CCT"}


@dataclass
class LiveSettings:
    """Values read from one device, and the field names that device actually has."""

    values: dict[str, Any]
    supported: tuple[str, ...]


def _component(config: dict[str, Any], kind: str, index: int) -> bool:
    return isinstance(config.get(f"{kind}:{index}"), dict)


def _output_kind(config: dict[str, Any], index: int) -> str | None:
    for kind in ("switch", "light", "rgb", "rgbw", "cct"):
        if _component(config, kind, index):
            return kind
    return None


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) is bool(right)
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        try:
            return abs(float(left) - float(right)) < 0.01
        except (TypeError, ValueError):
            return False
    return str(left or "").strip() == str(right or "").strip()


async def read_live_settings(session: Any, channel: int = 0) -> LiveSettings:
    """Read the current RPC config and keep only keys the device returned."""
    config = dict(getattr(session, "config", {}) or {})
    values: dict[str, Any] = {}
    supported: list[str] = []

    sys_cfg = await session.call("Sys.GetConfig")
    device = sys_cfg.get("device") if isinstance(sys_cfg, dict) else None
    if isinstance(device, dict) and "name" in device:
        supported.append("name")
        values["name"] = str(device.get("name") or "")

    if _component(config, "input", channel):
        incoming = await session.call("Input.GetConfig", {"id": channel})
        if isinstance(incoming, dict):
            if "type" in incoming:
                supported.append("input_type")
                values["input_type"] = incoming.get("type") or "switch"
            if "invert" in incoming:
                supported.append("invert")
                values["invert"] = bool(incoming.get("invert"))

    kind = _output_kind(config, channel)
    output: dict[str, Any] = {}
    if kind is not None:
        read = await session.call(f"{_NAMESPACES[kind]}.GetConfig", {"id": channel})
        if isinstance(read, dict):
            output = read
            for field, rpc_key in _OUTPUT_KEYS.items():
                if rpc_key not in output:
                    continue
                if field == "fade_rate" and kind not in DIMMER_COMPONENTS:
                    continue
                supported.append(field)
                values[field] = output.get(rpc_key)
            for field, rpc_key in (
                ("transition_up", "transition_duration_up"),
                ("transition_down", "transition_duration_down"),
            ):
                if rpc_key in output:
                    supported.append(field)
                    values[field] = output.get(rpc_key)
            ramp_up = output.get("ramp_up")
            ramp_down = output.get("ramp_down")
            if "transition_up" not in supported and ramp_up is not None:
                supported.append("transition_up")
                values["transition_up"] = ramp_up
            if "transition_down" not in supported and ramp_down is not None:
                supported.append("transition_down")
                values["transition_down"] = ramp_down
            range_map = output.get("range_map")
            if isinstance(range_map, list) and len(range_map) == 2:
                supported.extend(["min_brightness", "max_brightness"])
                values["min_brightness"] = range_map[0]
                values["max_brightness"] = range_map[1]
            night = output.get("night_mode")
            if isinstance(night, dict):
                supported.append("night_mode")
                values["night_mode"] = bool(night.get("enable"))
                if "brightness" in night:
                    supported.append("night_brightness")
                    values["night_brightness"] = night.get("brightness")
                between = night.get("active_between")
                if isinstance(between, list) and len(between) == 2:
                    supported.extend(["night_start", "night_end"])
                    values["night_start"] = between[0] or ""
                    values["night_end"] = between[1] or ""

    return LiveSettings(values=values, supported=tuple(supported))


async def _write_compound(session: Any, key: str, value: Any, values: dict[str, Any], channel: int, kind: str) -> Any:
    namespace = _NAMESPACES[kind]
    if key in {"min_brightness", "max_brightness"}:
        payload = {"range_map": [int(values["min_brightness"]), int(values["max_brightness"])]}
        await session.call(f"{namespace}.SetConfig", {"id": channel, "config": payload})
        read = await session.call(f"{namespace}.GetConfig", {"id": channel})
        mapping = read.get("range_map") if isinstance(read, dict) else None
        if not isinstance(mapping, list) or len(mapping) != 2:
            return None
        return mapping[0] if key == "min_brightness" else mapping[1]
    if key in {"night_mode", "night_brightness", "night_start", "night_end"}:
        night: dict[str, Any] = {}
        if "night_mode" in values:
            night["enable"] = bool(values.get("night_mode"))
        if values.get("night_brightness") not in (None, ""):
            night["brightness"] = int(values["night_brightness"])
        if values.get("night_start") and values.get("night_end"):
            night["active_between"] = [str(values["night_start"]), str(values["night_end"])]
        await session.call(f"{namespace}.SetConfig", {"id": channel, "config": {"night_mode": night}})
        read = await session.call(f"{namespace}.GetConfig", {"id": channel})
        current = read.get("night_mode") if isinstance(read, dict) else None
        if not isinstance(current, dict):
            return None
        if key == "night_mode":
            return bool(current.get("enable"))
        if key == "night_brightness":
            return current.get("brightness")
        between = current.get("active_between") or ["", ""]
        return between[0] if key == "night_start" else between[1]
    if key in {"transition_up", "transition_down"}:
        rpc_key = "transition_duration_up" if key == "transition_up" else "transition_duration_down"
        await session.call(f"{namespace}.SetConfig", {"id": channel, "config": {rpc_key: float(value)}})
        read = await session.call(f"{namespace}.GetConfig", {"id": channel})
        if isinstance(read, dict) and rpc_key in read:
            return read.get(rpc_key)
        ramp = "ramp_up" if key == "transition_up" else "ramp_down"
        return read.get(ramp) if isinstance(read, dict) else None
    return None


async def apply_live_settings(session: Any, updates: dict[str, Any], *, channel: int = 0) -> dict[str, str]:
    """Write each supplied field that the device supports. Return field errors."""
    current = await read_live_settings(session, channel)
    config = dict(getattr(session, "config", {}) or {})
    kind = _output_kind(config, channel)
    errors: dict[str, str] = {}
    simple = {
        "name": "device_name",
        "input_type": "input_type",
        "input_mode": "input_mode",
        "invert": "invert",
        "initial_state": "power_on_state",
        "auto_on": "auto_on",
        "auto_on_delay": "auto_on_delay",
        "auto_off": "auto_off",
        "auto_off_delay": "auto_off_delay",
        "fade_rate": "fade_rate",
        "transition_duration": "transition_duration",
    }
    for key, value in updates.items():
        if key not in current.supported:
            continue
        try:
            if key in simple:
                read_back, note = await write_setting(session, simple[key], value, channel=channel)
                if note:
                    errors[key] = "not_applied"
                    continue
            elif kind is None:
                errors[key] = "not_applied"
                continue
            else:
                read_back = await _write_compound(session, key, value, updates, channel, kind)
            if not _same(value, read_back):
                errors[key] = "not_applied"
        except Exception:  # noqa: BLE001
            errors[key] = "not_applied"
    return errors


def channel_updates(values: dict[str, Any]) -> dict[str, Any]:
    """Settings that are safe to copy. The device name and room are not included."""
    return {key: values[key] for key in CHANNEL_KEYS if key in values}


def model_is_dimmer(model: str) -> bool:
    """True when the model name is a light or dimmer rather than a relay or plug."""
    text = (model or "").lower()
    if any(marker in text for marker in ("plug", "1pm", "2pm", "3pm", "4pm", "relay")):
        return False
    return any(marker in text for marker in ("dimmer", "rgbw", "rgb", "bulb", "light", "strip", "duo", "vintage"))
