"""Parse Shelly BLE manufacturer data.

The block layout matches ``aioshelly.ble.manufacturer_data`` (Allterco company
id ``0x0BA9``, flags / MAC / model blocks).
"""

from __future__ import annotations

from typing import Any

from .const import ALLTERCO_MFID, FLAG_AUTH_ENABLED, FLAG_RPC_OVER_BLE

BLOCK_FLAGS = 0x01
BLOCK_MAC = 0x0A
BLOCK_MODEL = 0x0B


def parse_shelly_manufacturer_data(
    manufacturer_data: dict[int, bytes] | None,
) -> dict[str, Any] | None:
    """Return flags, MAC and model id from a Shelly advertisement."""
    if not manufacturer_data:
        return None
    data = manufacturer_data.get(ALLTERCO_MFID)
    if not data:
        return None
    parsed: dict[str, Any] = {}
    offset = 0
    while offset < len(data):
        block_type = data[offset]
        offset += 1
        if block_type == BLOCK_FLAGS and offset + 2 <= len(data):
            parsed["flags"] = int.from_bytes(data[offset : offset + 2], "little")
            offset += 2
        elif block_type == BLOCK_MAC and offset + 6 <= len(data):
            parsed["mac"] = "".join(f"{byte:02X}" for byte in reversed(data[offset : offset + 6]))
            offset += 6
        elif block_type == BLOCK_MODEL and offset + 2 <= len(data):
            parsed["model_id"] = int.from_bytes(data[offset : offset + 2], "little")
            offset += 2
        else:
            break
    return parsed or None


def rpc_over_ble_enabled(flags: int) -> bool:
    """Return True when the device is still accepting BLE RPC."""
    return bool(flags & FLAG_RPC_OVER_BLE)


def auth_enabled(flags: int) -> bool:
    """Return True when the advertisement says device authentication is on."""
    return bool(flags & FLAG_AUTH_ENABLED)
