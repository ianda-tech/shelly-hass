"""Classify Shelly BLE advertisements and flash an output for Identify."""

from __future__ import annotations

from dataclasses import dataclass

from .ble import auth_enabled, parse_shelly_manufacturer_data, rpc_over_ble_enabled
from .device_list import placeholder_name
from .util import normalize_mac

IDENTIFY_SECONDS = 2


@dataclass
class HeardShelly:
    """One Shelly advertisement heard by a Home Assistant scanner or proxy."""

    mac: str
    model_hint: str
    rssi: int
    source: str
    rpc: bool
    auth: bool


def model_hint_from(model_id: object, local_name: str = "") -> str:
    """Prefer the aioshelly model name, then the advertisement name."""
    try:
        from aioshelly.ble import get_name_from_model_id

        if isinstance(model_id, int):
            name = get_name_from_model_id(model_id)
            if name:
                return str(name)
    except Exception:  # noqa: BLE001
        pass
    if local_name:
        return local_name
    if model_id is not None:
        return f"model {model_id}"
    return ""


def heard_from_advert(
    name: str,
    manufacturer_data: dict | None,
    rssi: int = 0,
    source: str = "",
) -> HeardShelly | None:
    """Return a Shelly advertisement, or None when the payload is not Shelly."""
    parsed = parse_shelly_manufacturer_data(manufacturer_data)
    if not parsed or "mac" not in parsed:
        return None
    try:
        mac = normalize_mac(str(parsed["mac"]))
    except ValueError:
        return None
    flags = int(parsed.get("flags") or 0)
    return HeardShelly(
        mac=mac,
        model_hint=model_hint_from(parsed.get("model_id"), name or ""),
        rssi=int(rssi or 0),
        source=str(source or ""),
        rpc=rpc_over_ble_enabled(flags),
        auth=auth_enabled(flags),
    )


def rows_for_discovery(
    heard: list[HeardShelly],
    *,
    known: set[str],
    already_added: set[str],
    adopt: bool,
) -> tuple[list[dict[str, str]], list[str]]:
    """Rows to append, and MACs whose setup window is closed.

    Known and already-added MACs are skipped. Auth-enabled devices are skipped.
    Existing rows are not returned, so a later append cannot overwrite them.
    """
    rows: list[dict[str, str]] = []
    locked: list[str] = []
    seen = set(known) | set(already_added)
    for item in heard:
        if item.mac in seen or item.auth:
            continue
        seen.add(item.mac)
        if not item.rpc:
            locked.append(item.mac)
            continue
        rows.append(
            {
                "mac": item.mac,
                "name": placeholder_name(item.model_hint, item.mac) if adopt else "",
                "room": "",
                "model_hint": item.model_hint,
                "rssi": str(item.rssi),
                "source": item.source,
            }
        )
    return rows, locked


def identify_enabled_by_default(model: str) -> bool:
    """Lights can start enabled. Relays, plugs, and unknown models stay off.

    Toggling a relay can energise a connected load. An unknown model is treated
    the same way until someone enables the button.
    """
    text = (model or "").lower()
    if not text:
        return False
    if any(marker in text for marker in ("plug", "1pm", "2pm", "3pm", "4pm", "relay")):
        return False
    return any(marker in text for marker in ("dimmer", "rgbw", "rgb", "bulb", "light", "strip", "duo", "vintage"))


async def identify_output(session, seconds: float = IDENTIFY_SECONDS) -> str:
    """Toggle the first output for a few seconds. Raises ValueError when there is none."""
    config = getattr(session, "config", {}) or {}
    keys = {str(key).lower() for key in config}
    if any(key.startswith("switch:") for key in keys):
        await session.call("Switch.Set", {"id": 0, "toggle_after": seconds})
        return "Switch.Set"
    for component, method in (
        ("light", "Light.Set"),
        ("rgb", "RGB.Set"),
        ("rgbw", "RGBW.Set"),
        ("cct", "CCT.Set"),
    ):
        if any(key.startswith(f"{component}:") for key in keys):
            await session.call(method, {"id": 0, "on": True, "toggle_after": seconds})
            return method
    raise ValueError("no_output")
