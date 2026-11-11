"""Load a user-supplied CSV allowlist from the Home Assistant config directory."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from .models import AllowDevice, Allowlist, ChannelSettings, merge_channel
from .util import normalize_mac, parse_bool, parse_number

# A single "input" cell can carry the installer's shorthand.
INPUT_ALIASES: dict[str, tuple[str | None, str | None]] = {
    "switch": ("switch", "follow"),
    "toggle": ("switch", "flip"),
    "button": ("button", None),
    "momentary": ("button", "momentary"),
    "detached": (None, "detached"),
    "activation": (None, "activate"),
    "activate": (None, "activate"),
    "dim": ("button", "dim"),
    "dual_dim": ("button", "dual_dim"),
}

HEADER_ALIASES = {
    "area": "room",
    "model": "model_hint",
    "mac_address": "mac",
    "macaddress": "mac",
}


def resolve_config_path(config_dir: str, filename: str) -> Path:
    """Resolve ``filename`` inside the Home Assistant config directory.

    Absolute paths are accepted only when they already live under that directory.
    """
    if not filename or not filename.strip() or filename.strip() != filename:
        raise ValueError("outside_config")
    root = Path(config_dir).resolve()
    candidate = Path(filename)
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not target.is_relative_to(root):
        raise ValueError("outside_config")
    return target


def _cell(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def channel_from_row(row: dict[str, str]) -> ChannelSettings:
    """Build channel overrides from one CSV row. Blank cells stay unset."""
    settings = ChannelSettings()
    alias = _cell(row, "input").lower()
    if alias in INPUT_ALIASES:
        input_type, input_mode = INPUT_ALIASES[alias]
        settings.input_type = input_type
        settings.input_mode = input_mode
    if _cell(row, "input_type"):
        settings.input_type = _cell(row, "input_type").lower()
    if _cell(row, "input_mode"):
        settings.input_mode = _cell(row, "input_mode").lower()
    if _cell(row, "invert"):
        settings.invert = parse_bool(_cell(row, "invert"))
    if _cell(row, "initial_state"):
        settings.initial_state = _cell(row, "initial_state").lower()
    if _cell(row, "auto_on"):
        settings.auto_on = parse_bool(_cell(row, "auto_on"))
    if _cell(row, "auto_on_delay"):
        number = parse_number(_cell(row, "auto_on_delay"))
        settings.auto_on_delay = number
    if _cell(row, "auto_off"):
        settings.auto_off = parse_bool(_cell(row, "auto_off"))
    if _cell(row, "auto_off_delay"):
        settings.auto_off_delay = parse_number(_cell(row, "auto_off_delay"))
    if _cell(row, "fade_rate"):
        number = parse_number(_cell(row, "fade_rate"))
        settings.fade_rate = int(number) if number is not None else None
    if _cell(row, "transition"):
        settings.transition = parse_number(_cell(row, "transition"))
    if _cell(row, "transition_up"):
        settings.transition_up = parse_number(_cell(row, "transition_up"))
    if _cell(row, "transition_down"):
        settings.transition_down = parse_number(_cell(row, "transition_down"))
    if _cell(row, "min_brightness"):
        number = parse_number(_cell(row, "min_brightness"))
        settings.min_brightness = int(number) if number is not None else None
    if _cell(row, "max_brightness"):
        number = parse_number(_cell(row, "max_brightness"))
        settings.max_brightness = int(number) if number is not None else None
    if _cell(row, "night_mode"):
        settings.night_mode = parse_bool(_cell(row, "night_mode"))
    if _cell(row, "night_brightness"):
        number = parse_number(_cell(row, "night_brightness"))
        settings.night_brightness = int(number) if number is not None else None
    if _cell(row, "night_start"):
        settings.night_start = _cell(row, "night_start")
    if _cell(row, "night_end"):
        settings.night_end = _cell(row, "night_end")
    if _cell(row, "power_on_brightness"):
        number = parse_number(_cell(row, "power_on_brightness"))
        settings.power_on_brightness = int(number) if number is not None else None
    if _cell(row, "button_dimming"):
        settings.button_dimming = _cell(row, "button_dimming").lower()
    return settings


def _normalise_row(raw: dict[str, Any]) -> dict[str, str]:
    row: dict[str, str] = {}
    for key, value in raw.items():
        if not key:
            continue
        name = key.strip().lower().replace(" ", "_")
        name = HEADER_ALIASES.get(name, name)
        row[name] = "" if value is None else str(value).strip()
    return row


def without_csv_comments(text: str) -> str:
    """Drop lines whose first non-space character is #. Those are notes, not rows."""
    kept = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    if text.endswith("\n"):
        return "\n".join(kept) + "\n"
    return "\n".join(kept)


def merge_allowlist(base: Allowlist, incoming: Allowlist) -> None:
    """Merge rows. A blank incoming cell does not wipe a stored name, room, or hint."""
    for mac, device in incoming.devices.items():
        current = base.devices.get(mac)
        if current is None:
            base.devices[mac] = device
            continue
        if device.name:
            current.name = device.name
        if device.room:
            current.room = device.room
        if device.model_hint:
            current.model_hint = device.model_hint
        current.all_channels = merge_channel(current.all_channels, device.all_channels)
        for index, settings in device.by_channel.items():
            current.by_channel[index] = merge_channel(
                current.by_channel.get(index, ChannelSettings()), settings
            )


def parse_allowlist_csv(text: str) -> tuple[Allowlist, list[str]]:
    """Parse CSV text into an allowlist. Returns human-readable row errors."""
    allowlist = Allowlist()
    errors: list[str] = []
    reader = csv.DictReader(io.StringIO(without_csv_comments(text)))
    if not reader.fieldnames or not any(
        (name or "").strip().lower().replace(" ", "_") in {"mac", "mac_address", "macaddress"}
        for name in reader.fieldnames
    ):
        return allowlist, ["CSV must include a mac column"]
    for line_no, raw in enumerate(reader, start=2):
        row = _normalise_row(raw)
        if not row.get("mac"):
            continue
        try:
            mac = normalize_mac(row["mac"])
        except ValueError:
            errors.append(f"line {line_no}: invalid MAC")
            continue
        channel_text = row.get("channel", "")
        channel: int | None
        if channel_text == "":
            channel = None
        else:
            try:
                channel = int(channel_text)
            except ValueError:
                errors.append(f"line {line_no}: invalid channel")
                continue
        device = allowlist.devices.get(mac) or AllowDevice(mac=mac)
        if row.get("name"):
            device.name = row["name"]
        if row.get("room"):
            device.room = row["room"]
        if row.get("model_hint"):
            device.model_hint = row["model_hint"]
        settings = channel_from_row(row)
        if channel is None:
            device.all_channels = settings
        else:
            device.by_channel[channel] = settings
        allowlist.devices[mac] = device
    return allowlist, errors
