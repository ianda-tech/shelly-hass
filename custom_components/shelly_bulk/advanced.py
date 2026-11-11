"""Read and write documented Gen2+ settings, then read them back.

A missing component is reported as unsupported instead of failing the device.
"""

from __future__ import annotations

from typing import Any

from .const import BLE_SCANNER_MODES, DIMMER_COMPONENTS, OUTPUT_COMPONENTS

_CHANNEL_READ = {
    "input_mode": "in_mode",
    "power_on_state": "initial_state",
    "auto_on": "auto_on",
    "auto_off": "auto_off",
    "auto_on_delay": "auto_on_delay",
    "auto_off_delay": "auto_off_delay",
    "fade_rate": "button_fade_rate",
    "transition_duration": "transition_duration",
}

SWITCH_SETTINGS = (
    "bluetooth",
    "ble_rpc",
    "cloud",
    "access_point",
    "mqtt",
    "eco_mode",
    "status_led",
    "debug_logging",
)
SELECT_SETTINGS = ("scanner_mode", "input_mode", "power_on_state")


def _component(config: dict[str, Any], kind: str, index: int) -> dict[str, Any] | None:
    value = config.get(f"{kind}:{index}")
    return value if isinstance(value, dict) else None


def _output_kind(config: dict[str, Any], index: int) -> str | None:
    for kind in ("switch", "light", "rgb", "rgbw", "cct"):
        if _component(config, kind, index) is not None:
            return kind
    return None


async def _read(session: Any, method: str, params: dict | None = None) -> Any:
    return await session.call(method, params)


async def read_setting(session: Any, key: str, *, channel: int = 0) -> Any:
    """Return the current value, or None when this device has no such component."""
    config = dict(getattr(session, "config", {}) or {})
    if key == "bluetooth":
        ble = await _read(session, "BLE.GetConfig")
        return bool(ble.get("enable")) if isinstance(ble, dict) else None
    if key == "ble_rpc":
        ble = await _read(session, "BLE.GetConfig")
        if not isinstance(ble, dict):
            return None
        rpc = ble.get("rpc") if isinstance(ble.get("rpc"), dict) else {}
        return bool(rpc.get("enable"))
    if key == "cloud":
        cloud = await _read(session, "Cloud.GetConfig")
        return bool(cloud.get("enable")) if isinstance(cloud, dict) else None
    if key == "access_point":
        wifi = await _read(session, "WiFi.GetConfig")
        ap = wifi.get("ap") if isinstance(wifi, dict) and isinstance(wifi.get("ap"), dict) else None
        return bool(ap.get("enable")) if ap else None
    if key == "mqtt":
        if "mqtt" not in config:
            return None
        mqtt = await _read(session, "MQTT.GetConfig")
        return bool(mqtt.get("enable")) if isinstance(mqtt, dict) else None
    if key == "eco_mode":
        sys_cfg = await _read(session, "Sys.GetConfig")
        device = sys_cfg.get("device") if isinstance(sys_cfg, dict) else None
        if not isinstance(device, dict) or "eco_mode" not in device:
            return None
        return bool(device.get("eco_mode"))
    if key == "status_led":
        if "plugs_ui" not in config and "powerstrip_ui" not in config:
            return None
        method = "PLUGS_UI.GetConfig" if "plugs_ui" in config else "POWERSTRIP_UI.GetConfig"
        ui = await _read(session, method)
        leds = ui.get("leds") if isinstance(ui, dict) else None
        if not isinstance(leds, dict):
            return None
        return leds.get("mode") not in (None, "off")
    if key == "debug_logging":
        sys_cfg = await _read(session, "Sys.GetConfig")
        debug = sys_cfg.get("debug") if isinstance(sys_cfg, dict) else None
        if not isinstance(debug, dict):
            return None
        mqtt = debug.get("mqtt") if isinstance(debug.get("mqtt"), dict) else {}
        websocket = debug.get("websocket") if isinstance(debug.get("websocket"), dict) else {}
        udp = debug.get("udp") if isinstance(debug.get("udp"), dict) else {}
        return bool(mqtt.get("enable") or websocket.get("enable") or udp.get("addr"))
    if key in _CHANNEL_READ:
        kind = _output_kind(config, channel)
        if kind is None:
            return None
        namespace = {"switch": "Switch", "light": "Light", "rgb": "RGB", "rgbw": "RGBW", "cct": "CCT"}[kind]
        current = await _read(session, f"{namespace}.GetConfig", {"id": channel})
        if not isinstance(current, dict) or _CHANNEL_READ[key] not in current:
            return None
        return current.get(_CHANNEL_READ[key])
    if key == "device_name":
        sys_cfg = await _read(session, "Sys.GetConfig")
        device = sys_cfg.get("device") if isinstance(sys_cfg, dict) else None
        return device.get("name") if isinstance(device, dict) else None
    return None


async def write_setting(session: Any, key: str, value: Any, *, channel: int = 0) -> tuple[Any, str | None]:
    """Set one documented field and return the value read back.

    The second item is a note when the device has no component for the setting.
    """
    config = dict(getattr(session, "config", {}) or {})
    if key == "bluetooth":
        current = await _read(session, "BLE.GetConfig")
        rpc = True
        if isinstance(current, dict) and isinstance(current.get("rpc"), dict):
            rpc = bool(current["rpc"].get("enable", True))
        await session.call("BLE.SetConfig", {"config": {"enable": bool(value), "rpc": {"enable": rpc}}})
        return await read_setting(session, key), None
    if key == "ble_rpc":
        current = await _read(session, "BLE.GetConfig")
        enabled = True
        if isinstance(current, dict):
            enabled = bool(current.get("enable", True))
        await session.call(
            "BLE.SetConfig",
            {"config": {"enable": enabled, "rpc": {"enable": bool(value)}}},
        )
        return await read_setting(session, key), None
    if key == "cloud":
        await session.call("Cloud.SetConfig", {"config": {"enable": bool(value)}})
        return await read_setting(session, key), None
    if key == "access_point":
        await session.call("WiFi.SetConfig", {"config": {"ap": {"enable": bool(value)}}})
        return await read_setting(session, key), None
    if key == "mqtt":
        if "mqtt" not in config:
            return None, "MQTT component is not present on this device"
        await session.call("MQTT.SetConfig", {"config": {"enable": bool(value)}})
        return await read_setting(session, key), None
    if key == "eco_mode":
        await session.call("Sys.SetConfig", {"config": {"device": {"eco_mode": bool(value)}}})
        read = await read_setting(session, key)
        if read is None:
            return None, "eco_mode is not present on this device"
        return read, None
    if key == "status_led":
        if "plugs_ui" not in config and "powerstrip_ui" not in config:
            return None, "No LED UI component on this device"
        method = "PLUGS_UI.SetConfig" if "plugs_ui" in config else "POWERSTRIP_UI.SetConfig"
        mode = "power" if value else "off"
        await session.call(method, {"config": {"leds": {"mode": mode}}})
        return await read_setting(session, key), None
    if key == "debug_logging":
        if value:
            debug = {"websocket": {"enable": True}, "mqtt": {"enable": False}, "udp": {"addr": None}}
        else:
            debug = {
                "mqtt": {"enable": False},
                "websocket": {"enable": False},
                "udp": {"addr": None},
                "file_log": {"enable": False},
            }
        await session.call("Sys.SetConfig", {"config": {"debug": debug, "rpc_udp": {"listen_port": None}}})
        return await read_setting(session, key), None
    if key == "device_name":
        await session.call("Sys.SetConfig", {"config": {"device": {"name": str(value)}}})
        return await read_setting(session, key), None
    if key in {
        "input_mode",
        "power_on_state",
        "input_type",
        "auto_on",
        "auto_off",
        "auto_on_delay",
        "auto_off_delay",
        "fade_rate",
        "transition_duration",
        "invert",
    }:
        return await _write_channel(session, config, key, value, channel)
    return None, f"Unknown setting {key}"


async def _write_channel(session: Any, config: dict[str, Any], key: str, value: Any, channel: int) -> tuple[Any, str | None]:
    if key in {"input_type", "invert"}:
        if _component(config, "input", channel) is None:
            return None, f"input:{channel} is not present"
        field = "type" if key == "input_type" else "invert"
        sent = bool(value) if key == "invert" else value
        await session.call("Input.SetConfig", {"id": channel, "config": {field: sent}})
        read = await session.call("Input.GetConfig", {"id": channel})
        return (read.get(field) if isinstance(read, dict) else None), None
    kind = _output_kind(config, channel)
    if kind is None:
        return None, f"No output on channel {channel}"
    namespace = {"switch": "Switch", "light": "Light", "rgb": "RGB", "rgbw": "RGBW", "cct": "CCT"}[kind]
    payload: dict[str, Any] = {}
    if key == "input_mode":
        payload["in_mode"] = value
    elif key == "power_on_state":
        payload["initial_state"] = value
    elif key == "auto_on":
        payload["auto_on"] = bool(value)
    elif key == "auto_off":
        payload["auto_off"] = bool(value)
    elif key == "auto_on_delay":
        payload["auto_on_delay"] = float(value)
    elif key == "auto_off_delay":
        payload["auto_off_delay"] = float(value)
    elif key == "fade_rate":
        if kind not in DIMMER_COMPONENTS:
            return None, f"{kind}:{channel} is not a dimmer"
        payload["button_fade_rate"] = int(value)
    elif key == "transition_duration":
        if kind not in DIMMER_COMPONENTS and kind not in OUTPUT_COMPONENTS:
            return None, f"{kind}:{channel} has no transition"
        payload["transition_duration"] = float(value)
    await session.call(f"{namespace}.SetConfig", {"id": channel, "config": payload})
    read = await session.call(f"{namespace}.GetConfig", {"id": channel})
    if not isinstance(read, dict):
        return None, "read-back failed"
    field = {
        "input_mode": "in_mode",
        "power_on_state": "initial_state",
        "auto_on": "auto_on",
        "auto_off": "auto_off",
        "auto_on_delay": "auto_on_delay",
        "auto_off_delay": "auto_off_delay",
        "fade_rate": "button_fade_rate",
        "transition_duration": "transition_duration",
    }[key]
    return read.get(field), None


def scanner_mode_valid(mode: str) -> bool:
    return mode in BLE_SCANNER_MODES
