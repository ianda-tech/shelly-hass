"""Group adopted Shellies for a bulk settings change.

Labels use the Home Assistant name when someone set one. Otherwise they use the
model and the last four characters of the MAC. The raw Shelly hostname is not shown.
"""

from __future__ import annotations

from dataclasses import dataclass

from .device_settings import model_is_dimmer
from .util import display_mac, normalize_mac

RELAY_FIELDS = (
    "input_type",
    "input_mode",
    "invert",
    "initial_state",
    "auto_on",
    "auto_on_delay",
    "auto_off",
    "auto_off_delay",
)
DIMMER_FIELDS = RELAY_FIELDS + (
    "fade_rate",
    "transition_duration",
    "min_brightness",
    "max_brightness",
    "night_mode",
    "night_brightness",
    "night_start",
    "night_end",
)


@dataclass(frozen=True)
class DeviceCard:
    """One adopted Shelly, already labelled for a form."""

    entry_id: str
    label: str
    room: str
    area_id: str
    model: str
    friendly: str
    mac: str
    ip: str
    unnamed: bool
    dimmer: bool


def friendly_model(model: str) -> str:
    """Short model name. Drops a leading 'Shelly ' from the aioshelly name."""
    code = (model or "").strip()
    try:
        from aioshelly.const import MODEL_NAMES

        named = MODEL_NAMES.get(code)
        if named:
            return str(named).removeprefix("Shelly ").strip() or code
    except Exception:  # noqa: BLE001
        pass
    if code.lower().startswith("shelly "):
        return code[7:].strip()
    return code or "Shelly"


def _last4(mac: str) -> str:
    try:
        compact = normalize_mac(mac)
    except ValueError:
        compact = "".join(char for char in mac.upper() if char in "0123456789ABCDEF")
    return compact[-4:] if compact else ""


def looks_like_hostname(name: str, mac: str) -> bool:
    """True for the default Shelly hostname, which repeats the MAC."""
    text = (name or "").strip().lower()
    if not text:
        return True
    try:
        compact = normalize_mac(mac).lower()
    except ValueError:
        compact = ""
    folded = "".join(char for char in text if char in "0123456789abcdef")
    if compact and compact in folded:
        return True
    return text.startswith("shelly") and "-" in text


def short_name(name_by_user: str, device_name: str, model: str, mac: str) -> tuple[str, bool]:
    """Return ``(label name, unnamed)``. A user-set name wins over the hostname."""
    custom = (name_by_user or "").strip()
    if custom:
        return custom, False
    if not looks_like_hostname(device_name, mac):
        return device_name.strip(), False
    friendly = friendly_model(model)
    tail = _last4(mac)
    if tail:
        return f"{friendly} · {tail}", True
    return friendly, True


def device_label(name: str, room: str, mac: str, ip: str) -> str:
    shown_mac = ""
    if mac:
        try:
            shown_mac = display_mac(mac)
        except ValueError:
            shown_mac = mac
    parts = [name, room or "no room"]
    if shown_mac:
        parts.append(shown_mac)
    parts.append(ip or "no ip")
    return " · ".join(parts)


def model_options(cards: list[DeviceCard]) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    friendly: dict[str, str] = {}
    for card in cards:
        key = card.model or card.friendly or "unknown"
        counts[key] = counts.get(key, 0) + 1
        friendly[key] = card.friendly or key
    options = []
    for key in sorted(counts, key=lambda item: friendly[item].lower()):
        name = friendly[key]
        label = f"{name} ({key}), {counts[key]} devices" if name != key else f"{key}, {counts[key]} devices"
        options.append({"value": key, "label": label})
    return options


def room_options(cards: list[DeviceCard]) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.room] = counts.get(card.room, 0) + 1
    options = []
    for room in sorted(counts, key=lambda item: (item == "", item.lower())):
        label = "No room" if room == "" else room
        options.append({"value": room or "__none__", "label": f"{label}, {counts[room]} devices"})
    return options


def select_cards(
    cards: list[DeviceCard],
    kind: str,
    *,
    model: str = "",
    room: str = "",
    entry_ids: set[str] | None = None,
    exclude_id: str = "",
) -> list[DeviceCard]:
    """Return the devices in one group. ``exclude_id`` drops the device just edited."""
    chosen: list[DeviceCard]
    if kind == "all":
        chosen = list(cards)
    elif kind == "unnamed":
        chosen = [card for card in cards if card.unnamed]
    elif kind == "model":
        needle = (model or "").lower()
        chosen = [
            card
            for card in cards
            if card.model == model or card.friendly.lower() == needle or needle in card.model.lower() or needle in card.friendly.lower()
        ]
    elif kind == "room":
        key = "" if room in {"", "__none__"} else room
        chosen = [card for card in cards if card.room == key]
    elif kind == "individual":
        ids = entry_ids or set()
        chosen = [card for card in cards if card.entry_id in ids]
    else:
        chosen = []
    if exclude_id:
        chosen = [card for card in chosen if card.entry_id != exclude_id]
    return chosen


def fields_for(cards: list[DeviceCard]) -> tuple[str, ...]:
    """Settings to offer. Dimmer fields appear when any selected device is a dimmer."""
    if any(card.dimmer for card in cards):
        return DIMMER_FIELDS
    return RELAY_FIELDS


def ticked_updates(user_input: dict, fields: tuple[str, ...] | list[str]) -> dict:
    """Settings whose 'change this' toggle is on."""
    return {key: user_input.get(key) for key in fields if user_input.get(f"change_{key}")}


def confirmation_text(cards: list[DeviceCard], *, limit: int = 12) -> str:
    shown = [card.label for card in cards[:limit]]
    extra = len(cards) - len(shown)
    body = "\n".join(shown)
    if extra:
        body += f"\nand {extra} more"
    return f"This will change {len(cards)} devices.\n{body}"
