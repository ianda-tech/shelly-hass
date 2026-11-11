"""One periodic read per Shelly, shared by every control on that device.

Entity setup must not wait on the network. The first read is a background
task. Later reads run on a 60 second interval, one session per device, and
the fleet semaphore stops a slow device from opening more than its share of
connections.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .advanced import SWITCH_SETTINGS, _output_kind, read_setting

_LOGGER = logging.getLogger(__name__)

SETTINGS_INTERVAL = timedelta(seconds=60)
DEVICE_READ_TIMEOUT = 20

_SETTING_KEYS = (
    *SWITCH_SETTINGS,
    "auto_off_delay",
    "fade_rate",
    "transition_duration",
)
_OUTPUT_NAMESPACE = {
    "switch": "Switch",
    "light": "Light",
    "rgb": "RGB",
    "rgbw": "RGBW",
    "cct": "CCT",
}


class ShellyDeviceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Config and status for one core Shelly entry."""

    def __init__(self, runtime, shelly_entry) -> None:
        super().__init__(
            runtime.hass,
            _LOGGER,
            config_entry=runtime.entry,
            name=f"Shelly Installer {shelly_entry.title or shelly_entry.entry_id}",
            update_interval=SETTINGS_INTERVAL,
        )
        self.runtime = runtime
        self.shelly_entry = shelly_entry

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self._fetch(), DEVICE_READ_TIMEOUT)
        except TimeoutError as err:
            raise UpdateFailed(f"{self.shelly_entry.title} timed out") from err
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> dict[str, Any]:
        entry = self.shelly_entry
        host = str(entry.data.get("host") or "")
        session = await self.runtime._open_shelly(entry, attempts=1)
        try:
            settings: dict[str, Any] = {}
            for key in _SETTING_KEYS:
                settings[key] = await read_setting(session, key)
            config = dict(getattr(session, "config", {}) or {})
            output = await _read_output(session, config)
            consumption = await _read_consumption(session, config)
            network = await _read_network(session, host)
        finally:
            await session.shutdown()
        self.runtime._network[entry.entry_id] = network
        self.runtime.publish_shelly_link(entry, network["ip"])
        self.runtime._consumption_cache[entry.entry_id] = consumption
        return {
            "online": True,
            "settings": settings,
            "output": output,
            "consumption": consumption,
            "network": network,
        }

    def patch_setting(self, key: str, value: Any) -> None:
        """Publish a value just written, without opening another session."""
        data = dict(self.data or {})
        settings = dict(data.get("settings") or {})
        settings[key] = value
        data["settings"] = settings
        data["online"] = True
        self.async_set_updated_data(data)

    def patch_output(self, *, kind: str | None = None, in_mode: str | None = None, initial_state: str | None = None) -> None:
        data = dict(self.data or {})
        output = dict(data.get("output") or {})
        if kind is not None:
            output["kind"] = kind
        if in_mode is not None:
            output["in_mode"] = in_mode
        if initial_state is not None:
            output["initial_state"] = initial_state
        data["output"] = output
        data["online"] = True
        self.async_set_updated_data(data)

    def patch_consumption(self, channel: int, value: str) -> None:
        data = dict(self.data or {})
        consumption = dict(data.get("consumption") or {})
        values = dict(consumption.get("values") or {})
        values[channel] = value
        values[str(channel)] = value
        consumption["values"] = values
        data["consumption"] = consumption
        data["online"] = True
        self.async_set_updated_data(data)


async def _read_output(session, config: dict[str, Any]) -> dict[str, Any]:
    kind = _output_kind(config, 0)
    if kind is None:
        return {"kind": None, "in_mode": None, "initial_state": None}
    namespace = _OUTPUT_NAMESPACE[kind]
    current = await session.call(f"{namespace}.GetConfig", {"id": 0})
    if not isinstance(current, dict):
        return {"kind": kind, "in_mode": None, "initial_state": None}
    return {
        "kind": kind,
        "in_mode": current.get("in_mode"),
        "initial_state": current.get("initial_state"),
    }


async def _read_consumption(session, config: dict[str, Any]) -> dict[str, Any]:
    from .device_type import channel_consumption, switch_channels

    channels = switch_channels(config)
    sys_cfg = await session.call("Sys.GetConfig")
    ui = sys_cfg.get("ui_data") if isinstance(sys_cfg, dict) else None
    raw = ui.get("consumption_types") if isinstance(ui, dict) else None
    types = list(raw) if isinstance(raw, list) else []
    return {
        "channels": channels,
        "types": types,
        "values": {channel: channel_consumption(types, channel) for channel in channels},
    }


async def _read_network(session, host: str) -> dict[str, Any]:
    ip = host
    ssid = ""
    rssi = None
    try:
        status = await session.call("Shelly.GetStatus")
    except Exception:  # noqa: BLE001
        status = None
    wifi = status.get("wifi") if isinstance(status, dict) else None
    if isinstance(wifi, dict):
        ip = str(wifi.get("sta_ip") or ip)
        ssid = str(wifi.get("ssid") or "")
        rssi = wifi.get("rssi")
    return {"ip": ip, "ssid": ssid, "rssi": rssi}
