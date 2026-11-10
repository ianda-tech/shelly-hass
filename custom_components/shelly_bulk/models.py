"""Datatypes for allowlists, channel profiles, and adoption results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class ChannelSettings:
    """Per-channel Shelly settings. None means do not send that field."""

    input_type: str | None = None
    input_mode: str | None = None
    invert: bool | None = None
    initial_state: str | None = None
    auto_on: bool | None = None
    auto_on_delay: float | None = None
    auto_off: bool | None = None
    auto_off_delay: float | None = None
    fade_rate: int | None = None
    transition: float | None = None
    transition_up: float | None = None
    transition_down: float | None = None
    min_brightness: int | None = None
    max_brightness: int | None = None
    night_mode: bool | None = None
    night_brightness: int | None = None
    night_start: str | None = None
    night_end: str | None = None
    power_on_brightness: int | None = None
    button_dimming: str | None = None

    def is_empty(self) -> bool:
        return all(value is None for value in asdict(self).values())


def channel_to_dict(settings: ChannelSettings) -> dict[str, Any]:
    return {key: value for key, value in asdict(settings).items() if value is not None}


def channel_from_dict(data: dict[str, Any] | None) -> ChannelSettings:
    if not data:
        return ChannelSettings()
    known = {item.name for item in fields(ChannelSettings)}
    return ChannelSettings(**{key: value for key, value in data.items() if key in known})


def merge_channel(base: ChannelSettings, override: ChannelSettings) -> ChannelSettings:
    """Overlay override fields that were actually set."""
    merged = asdict(base)
    for key, value in asdict(override).items():
        if value is not None:
            merged[key] = value
    return ChannelSettings(**merged)


@dataclass
class SecuritySettings:
    """Security and identity applied over RPC after Wi-Fi join."""

    disable_cloud: bool = False
    disable_ap: bool = False
    disable_ble_rpc: bool = True
    timezone: str = ""
    device_name: str = ""


@dataclass(frozen=True)
class RpcCall:
    """One Gen2+ RPC call. ``config`` keys may be dropped individually on error."""

    method: str
    params: dict[str, Any]
    label: str


@dataclass
class AllowDevice:
    """One allowlist row, plus optional per-channel overrides."""

    mac: str
    name: str = ""
    room: str = ""
    model_hint: str = ""
    all_channels: ChannelSettings = field(default_factory=ChannelSettings)
    by_channel: dict[int, ChannelSettings] = field(default_factory=dict)

    def settings_for(self, index: int, base: ChannelSettings) -> ChannelSettings:
        merged = merge_channel(base, self.all_channels)
        extra = self.by_channel.get(index)
        if extra is not None:
            merged = merge_channel(merged, extra)
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {
            "mac": self.mac,
            "name": self.name,
            "room": self.room,
            "model_hint": self.model_hint,
            "all_channels": channel_to_dict(self.all_channels),
            "by_channel": {
                str(index): channel_to_dict(settings)
                for index, settings in self.by_channel.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AllowDevice:
        channels = {
            int(index): channel_from_dict(settings)
            for index, settings in (data.get("by_channel") or {}).items()
        }
        return cls(
            mac=data["mac"],
            name=data.get("name") or "",
            room=data.get("room") or "",
            model_hint=data.get("model_hint") or "",
            all_channels=channel_from_dict(data.get("all_channels")),
            by_channel=channels,
        )


@dataclass
class Allowlist:
    """MAC-keyed allowlist stored in Home Assistant's .storage."""

    devices: dict[str, AllowDevice] = field(default_factory=dict)

    def __contains__(self, mac: str) -> bool:
        from .util import normalize_mac

        try:
            return normalize_mac(mac) in self.devices
        except ValueError:
            return False

    def get(self, mac: str) -> AllowDevice | None:
        from .util import normalize_mac

        try:
            return self.devices.get(normalize_mac(mac))
        except ValueError:
            return None

    def to_dict(self) -> dict[str, Any]:
        return {mac: device.to_dict() for mac, device in self.devices.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Allowlist:
        devices = {
            mac: AllowDevice.from_dict(payload) for mac, payload in (data or {}).items()
        }
        return cls(devices=devices)
