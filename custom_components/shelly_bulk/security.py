"""Secure profile: harden a Gen2+ Shelly and read the result back.

Passwords are hashed for Shelly.SetAuth and are never placed on the checklist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .profile import build_set_auth

Redact = Callable[[str], str]


@dataclass
class SecureProfile:
    """Hardening checklist. Optional items stay off unless the user enables them."""

    rotate_password: bool = True
    disable_cloud: bool = True
    disable_ap: bool = True
    disable_ble_rpc: bool = True
    disable_mqtt: bool = False
    disable_ws: bool = False
    disable_debug: bool = True
    firmware_manual: bool = False
    restrict_web_ui: bool = False


SECURE_OPTION_DEFAULTS: dict[str, bool] = {
    "secure_rotate_password": True,
    "secure_disable_cloud": True,
    "secure_disable_ap": True,
    "secure_disable_ble_rpc": True,
    "secure_disable_mqtt": False,
    "secure_disable_ws": False,
    "secure_disable_debug": True,
    "secure_firmware_manual": False,
    "secure_restrict_web_ui": False,
}

_SERVICE_TO_OPTION = {
    "rotate_password": "secure_rotate_password",
    "disable_cloud": "secure_disable_cloud",
    "disable_ap": "secure_disable_ap",
    "disable_ble_rpc": "secure_disable_ble_rpc",
    "disable_mqtt": "secure_disable_mqtt",
    "disable_ws": "secure_disable_ws",
    "disable_debug": "secure_disable_debug",
    "firmware_manual": "secure_firmware_manual",
    "restrict_web_ui": "secure_restrict_web_ui",
}


def secure_profile_from(options: dict[str, Any], overrides: dict[str, Any] | None = None) -> SecureProfile:
    """Build the checklist from options, with per-call overrides."""
    overrides = overrides or {}
    values: dict[str, bool] = {}
    for service_key, option_key in _SERVICE_TO_OPTION.items():
        if service_key in overrides and overrides[service_key] is not None:
            values[service_key] = bool(overrides[service_key])
        else:
            values[service_key] = bool(options.get(option_key, SECURE_OPTION_DEFAULTS[option_key]))
    return SecureProfile(**values)


def _unsupported(payload: Any) -> bool:
    return not isinstance(payload, dict) or "_error" in payload


async def _try_call(session: Any, method: str, params: dict | None, notes: list[str], label: str, redact: Redact) -> Any:
    try:
        return await session.call(method, params)
    except Exception as err:  # noqa: BLE001
        notes.append(f"{label}: {redact(str(err))}")
        return {"_error": redact(str(err))}


async def read_security_state(session: Any, notes: list[str], redact: Redact) -> dict[str, Any]:
    """Read the documented config objects used by the checklist."""
    state: dict[str, Any] = {"shelly": dict(getattr(session, "shelly", {}) or {})}
    info = await _try_call(session, "Shelly.GetDeviceInfo", None, notes, "device info", redact)
    if isinstance(info, dict) and "_error" not in info:
        state["shelly"] = info
    for key, method in (
        ("cloud", "Cloud.GetConfig"),
        ("wifi", "WiFi.GetConfig"),
        ("ble", "BLE.GetConfig"),
        ("mqtt", "MQTT.GetConfig"),
        ("ws", "Ws.GetConfig"),
        ("sys", "Sys.GetConfig"),
    ):
        state[key] = await _try_call(session, method, None, notes, key, redact)
    return state


async def apply_secure_profile(
    session: Any,
    profile: SecureProfile,
    password: str,
    notes: list[str],
    redact: Redact,
) -> bool:
    """Apply every requested hardening call except the password, then SetAuth last.

    Returns True when Shelly.SetAuth was sent. The caller reconnects afterwards
    because digest auth changes under the open session.
    """
    if profile.disable_cloud:
        await _try_call(session, "Cloud.SetConfig", {"config": {"enable": False}}, notes, "cloud", redact)
        await _try_call(session, "Cloud.GetConfig", None, notes, "cloud read-back", redact)
    if profile.disable_ap:
        await _try_call(
            session, "WiFi.SetConfig", {"config": {"ap": {"enable": False}}}, notes, "access point", redact
        )
        await _try_call(session, "WiFi.GetConfig", None, notes, "access point read-back", redact)
    if profile.disable_ble_rpc:
        await _try_call(
            session,
            "BLE.SetConfig",
            {"config": {"enable": True, "rpc": {"enable": False}}},
            notes,
            "bluetooth rpc",
            redact,
        )
        await _try_call(session, "BLE.GetConfig", None, notes, "bluetooth read-back", redact)
    if profile.disable_mqtt:
        await _try_call(session, "MQTT.SetConfig", {"config": {"enable": False}}, notes, "mqtt", redact)
        await _try_call(session, "MQTT.GetConfig", None, notes, "mqtt read-back", redact)
    if profile.disable_ws:
        await _try_call(session, "Ws.SetConfig", {"config": {"enable": False}}, notes, "outbound websocket", redact)
        await _try_call(session, "Ws.GetConfig", None, notes, "websocket read-back", redact)
    if profile.disable_debug:
        debug_config = {
            "debug": {
                "mqtt": {"enable": False},
                "websocket": {"enable": False},
                "udp": {"addr": None},
                "file_log": {"enable": False},
            },
            "rpc_udp": {"listen_port": None},
        }
        result = await _try_call(session, "Sys.SetConfig", {"config": debug_config}, notes, "debug logging", redact)
        if isinstance(result, dict) and "_error" in result:
            await _try_call(
                session,
                "Sys.SetConfig",
                {
                    "config": {
                        "debug": {
                            "mqtt": {"enable": False},
                            "websocket": {"enable": False},
                            "udp": {"addr": None},
                        }
                    }
                },
                notes,
                "debug logging (without file log)",
                redact,
            )
        await _try_call(session, "Sys.GetConfig", None, notes, "debug read-back", redact)
    if profile.restrict_web_ui:
        await _try_call(
            session,
            "Sys.SetConfig",
            {"config": {"device": {"discoverable": False}}},
            notes,
            "web ui discovery",
            redact,
        )
        await _try_call(session, "Sys.GetConfig", None, notes, "discoverable read-back", redact)
    if profile.firmware_manual:
        notes.append(
            "Firmware stays manual: Shelly.Update was not called. "
            "Gen2+ has no documented auto-update switch; cloud push stops when cloud is off."
        )
    if not profile.rotate_password:
        return False
    shelly = dict(getattr(session, "shelly", {}) or {})
    if shelly.get("auth_en"):
        notes.append(
            "Device already has a login. The password was not changed. "
            "Home Assistant keeps the password stored on the Shelly entry."
        )
        return False
    device_id = str(shelly.get("id") or "")
    if not device_id:
        info = await _try_call(session, "Shelly.GetDeviceInfo", None, notes, "device id", redact)
        if isinstance(info, dict):
            device_id = str(info.get("id") or "")
    if not device_id:
        notes.append("Shelly.SetAuth skipped: device id missing")
        return False
    params = build_set_auth(device_id, password)
    result = await _try_call(session, "Shelly.SetAuth", params, notes, "authentication", redact)
    if isinstance(result, dict) and "_error" in result:
        return False
    notes.append("Device authentication set. The password was not recorded.")
    return True


def evaluate_security(state: dict[str, Any], profile: SecureProfile, reconnected: bool) -> dict[str, Any]:
    """Turn a read-back into a checklist. Missing components are not failures."""
    shelly = state.get("shelly") if isinstance(state.get("shelly"), dict) else {}
    cloud = state.get("cloud") if isinstance(state.get("cloud"), dict) else {}
    wifi = state.get("wifi") if isinstance(state.get("wifi"), dict) else {}
    ble = state.get("ble") if isinstance(state.get("ble"), dict) else {}
    mqtt = state.get("mqtt") if isinstance(state.get("mqtt"), dict) else {}
    ws = state.get("ws") if isinstance(state.get("ws"), dict) else {}
    sys_cfg = state.get("sys") if isinstance(state.get("sys"), dict) else {}
    debug = sys_cfg.get("debug") if isinstance(sys_cfg.get("debug"), dict) else {}
    device = sys_cfg.get("device") if isinstance(sys_cfg.get("device"), dict) else {}
    rpc_udp = sys_cfg.get("rpc_udp") if isinstance(sys_cfg.get("rpc_udp"), dict) else {}
    ap = wifi.get("ap") if isinstance(wifi.get("ap"), dict) else {}
    ble_rpc = ble.get("rpc") if isinstance(ble.get("rpc"), dict) else {}

    def present(payload: Any) -> bool:
        return isinstance(payload, dict) and "_error" not in payload

    auth_on = bool(shelly.get("auth_en")) if present(shelly) else None
    cloud_off = (cloud.get("enable") is False) if present(cloud) else None
    ap_off = (ap.get("enable") is False) if present(wifi) else None
    ble_on = bool(ble.get("enable")) if present(ble) else None
    ble_rpc_off = (ble_rpc.get("enable") is False) if present(ble) else None
    mqtt_off = (mqtt.get("enable") is False) if present(mqtt) else None
    ws_off = (ws.get("enable") is False) if present(ws) else None
    debug_off = None
    if present(sys_cfg) and debug:
        udp = debug.get("udp") if isinstance(debug.get("udp"), dict) else {}
        file_log = debug.get("file_log") if isinstance(debug.get("file_log"), dict) else {}
        mqtt_log = debug.get("mqtt") if isinstance(debug.get("mqtt"), dict) else {}
        ws_log = debug.get("websocket") if isinstance(debug.get("websocket"), dict) else {}
        debug_off = (
            mqtt_log.get("enable") is not True
            and ws_log.get("enable") is not True
            and not udp.get("addr")
            and file_log.get("enable") is not True
            and rpc_udp.get("listen_port") in (None, 0)
        )
    discoverable = device.get("discoverable") if present(sys_cfg) and "discoverable" in device else None
    web_restricted = None
    if auth_on is not None:
        web_restricted = auth_on is True and (discoverable is False or discoverable is None)
    firmware_manual = None
    if profile.firmware_manual:
        firmware_manual = cloud_off is not False

    checks = {
        "auth_on": auth_on,
        "cloud_off": cloud_off,
        "ap_off": ap_off,
        "ble_on": ble_on,
        "ble_rpc_off": ble_rpc_off,
        "mqtt_off": mqtt_off,
        "ws_off": ws_off,
        "debug_off": debug_off,
        "firmware_manual": firmware_manual,
        "web_ui_restricted": web_restricted,
        "reconnected": reconnected,
    }
    issues: list[str] = []
    wanted = {
        "auth_on": profile.rotate_password,
        "cloud_off": profile.disable_cloud,
        "ap_off": profile.disable_ap,
        "ble_rpc_off": profile.disable_ble_rpc,
        "mqtt_off": profile.disable_mqtt,
        "ws_off": profile.disable_ws,
        "debug_off": profile.disable_debug,
        "firmware_manual": profile.firmware_manual,
        "web_ui_restricted": profile.restrict_web_ui,
    }
    for key, required in wanted.items():
        if not required:
            continue
        value = checks[key]
        if value is False:
            issues.append(f"{key}: not in the requested state after read-back")
    if profile.rotate_password and reconnected is False:
        issues.append("reconnected: Home Assistant could not open the device with the new password")
    return {
        "firmware": shelly.get("ver") or shelly.get("fw_id") or "",
        "model": shelly.get("model") or "",
        **checks,
        "issues": issues,
        "ok": not issues,
    }
