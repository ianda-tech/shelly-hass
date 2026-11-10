"""Open a short-lived aioshelly RPC session over IP.

The integration uses the aioshelly package already installed for Home Assistant's
core Shelly integration. It is imported lazily so config-flow tests do not need
a device connection.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession


class AuthRequiredError(Exception):
    """The device rejected the connection because authentication is enabled."""


class RpcSession:
    """Small facade over ``RpcDevice`` so callers and tests share one shape."""

    def __init__(self, device: Any) -> None:
        self._device = device

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return await self._device.call_rpc(method, params)

    async def shutdown(self) -> None:
        await self._device.shutdown()

    @property
    def config(self) -> dict[str, Any]:
        return self._device.config

    @property
    def shelly(self) -> dict[str, Any]:
        return self._device.shelly


def _auth_error(err: BaseException) -> bool:
    return type(err).__name__ == "InvalidAuthError"


async def async_open_rpc(
    hass: HomeAssistant,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    verify_ssl: bool,
) -> RpcSession:
    """Connect and initialise. Closes the device if initialisation fails."""
    from aioshelly.common import ConnectionOptions
    from aioshelly.rpc_device import RpcDevice

    options = ConnectionOptions(
        ip_address=host,
        username=username or None,
        password=password if username else None,
        port=port,
        verify_ssl=verify_ssl,
    )
    device = await RpcDevice.create(async_get_clientsession(hass), None, options)
    try:
        await device.initialize()
    except Exception as err:
        try:
            await device.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if _auth_error(err):
            raise AuthRequiredError(str(err)) from err
        raise
    return RpcSession(device)


async def async_execute_calls(session: RpcSession, calls: list[Any], notes: list[str], redact) -> bool:
    """Run planned calls. A rejected multi-key config is retried field by field.

    Returns True when any successful call asked for a reboot.
    """
    restart = False
    for call in calls:
        result = await _call_flexible(session, call.method, call.params, call.label, notes, redact)
        if isinstance(result, dict) and result.get("restart_required"):
            restart = True
    return restart


async def _call_flexible(session, method, params, label, notes, redact) -> Any:
    config = (params or {}).get("config") if isinstance(params, dict) else None
    try:
        return await session.call(method, params)
    except Exception as err:  # noqa: BLE001
        if not isinstance(config, dict) or len(config) <= 1:
            notes.append(f"{label}: {redact(str(err))}")
            return None
        notes.append(f"{label}: full update was rejected ({redact(str(err))}); trying one field at a time")
        last = None
        for key, value in config.items():
            piece: dict[str, Any] = {"config": {key: value}}
            if "id" in params:
                piece["id"] = params["id"]
            try:
                last = await session.call(method, piece)
            except Exception as piece_err:  # noqa: BLE001
                notes.append(f"{label}: skipped {key} ({redact(str(piece_err))})")
        return last
