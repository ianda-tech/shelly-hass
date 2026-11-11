"""Join a Shelly setup AP on wlan0 when Bluetooth provisioning is closed.

Home Assistant OS and Supervised expose the host network through the Supervisor.
This module only updates wlan0. end0 is read so it can be checked and is never written.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from typing import Any, Awaitable, Callable

from .util import display_mac, normalize_mac

_LOGGER = logging.getLogger(__name__)

WLAN0 = "wlan0"
END0 = "end0"
SHELLY_AP_HOST = "192.168.33.1"
WORSE_METRIC_GAP = 200
WATCHDOG_SECONDS = 75
JOIN_WAIT_SECONDS = 20
LAN_WAIT_SECONDS = 40
RESTORE_TIMEOUT = 15
BATCH_PAUSE_SECONDS = 8

_SSID_MAC = re.compile(r"^shelly[0-9a-z]*-([0-9a-f]{12})$", re.IGNORECASE)

RpcCaller = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]
LanWaiter = Callable[[list[str]], Awaitable[Any]]
Adopted = Callable[[Any, str], Awaitable[None]]


class HotspotRefused(Exception):
    """A safety check stopped the hotspot attempt before, or while, wlan0 changed."""

    def __init__(self, reason: str, *, host: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.host = host


class _Payload:
    """JSON body for the Supervisor interface update."""

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def to_dict(self) -> dict[str, Any]:
        return self._body


def mac_plus(mac: str, delta: int) -> str:
    """Return a MAC that is ``delta`` above ``mac``, wrapping at 48 bits."""
    value = (int(normalize_mac(mac), 16) + delta) & ((1 << 48) - 1)
    return f"{value:012X}"


def parse_shelly_ssid(ssid: str) -> dict[str, str] | None:
    """Return the STA, BSSID, and BLE MACs encoded in a Shelly setup SSID.

    The hex in ``Shelly1PMMiniG3-48F6EEB96270`` is the Wi-Fi MAC. The AP BSSID
    is that MAC plus one, and the BLE MAC is that MAC plus two.
    """
    match = _SSID_MAC.match(ssid.strip())
    if match is None:
        return None
    sta = match.group(1).upper()
    return {"sta_mac": sta, "bssid_mac": mac_plus(sta, 1), "ble_mac": mac_plus(sta, 2)}


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _addresses(ipv4: dict[str, Any] | None) -> list[str]:
    if not isinstance(ipv4, dict):
        return []
    found: list[str] = []
    for item in ipv4.get("address") or []:
        text = str(item).split("/", 1)[0]
        if text:
            found.append(text)
    return found


def _ap_address(interface: dict[str, Any]) -> str | None:
    for address in _addresses(interface.get("ipv4")):
        if address.startswith("192.168.33."):
            return address
    return None


def end0_fingerprint(interface: dict[str, Any]) -> tuple[Any, ...]:
    """Values that must stay the same for the whole attempt."""
    ipv4 = interface.get("ipv4") if isinstance(interface.get("ipv4"), dict) else {}
    return (
        bool(interface.get("enabled")),
        bool(interface.get("connected")),
        bool(interface.get("primary")),
        str(interface.get("mac") or ""),
        str((ipv4 or {}).get("method") or ""),
        tuple(_addresses(ipv4)),
        str((ipv4 or {}).get("gateway") or ""),
        (ipv4 or {}).get("route_metric"),
    )


def default_route_interface(interfaces: list[dict[str, Any]]) -> str | None:
    """Return the connected interface with a gateway and the best route metric."""
    best_name: str | None = None
    best_metric: int | None = None
    for interface in interfaces:
        if not interface.get("connected"):
            continue
        ipv4 = interface.get("ipv4") if isinstance(interface.get("ipv4"), dict) else {}
        if not ipv4 or not ipv4.get("gateway"):
            continue
        metric = ipv4.get("route_metric")
        metric_value = 0 if metric is None else int(metric)
        if best_metric is None or metric_value < best_metric:
            best_name = str(interface.get("interface") or "")
            best_metric = metric_value
    return best_name


def assess_network(interfaces: list[dict[str, Any]]) -> dict[str, Any]:
    """Refuse unless end0 is the connected primary with the default route.

    wlan0 may exist and be disabled. It must not be the primary or the only
    interface. This does not change anything.
    """
    by_name = {str(item.get("interface") or ""): item for item in interfaces}
    wlan = by_name.get(WLAN0)
    if wlan is None:
        raise HotspotRefused(
            "wlan0 is not available. Hotspot provisioning needs a Wi-Fi adapter.",
            host=True,
        )
    if len(by_name) < 2:
        raise HotspotRefused(
            "wlan0 is the only network interface. Refusing to change the primary link.",
            host=True,
        )
    if wlan.get("primary"):
        raise HotspotRefused(
            "wlan0 is the primary interface. Refusing to join a Shelly setup AP.",
            host=True,
        )
    end0 = by_name.get(END0)
    if end0 is None:
        raise HotspotRefused("end0 is not available. Refusing to change the network.", host=True)
    if not end0.get("connected"):
        raise HotspotRefused("end0 is not connected. Refusing to join a setup AP.", host=True)
    if not end0.get("primary"):
        raise HotspotRefused(
            "end0 is not the primary interface. Refusing to join a setup AP.",
            host=True,
        )
    route = default_route_interface(interfaces)
    if route != END0:
        raise HotspotRefused(
            "end0 does not have the default route. Refusing to join a setup AP.",
            host=True,
        )
    return {"end0": end0, "wlan0": wlan, "fingerprint": end0_fingerprint(end0)}


def join_payload(ssid: str, end0_metric: int | None) -> dict[str, Any]:
    """Enable wlan0 on the open setup AP with a worse route metric than end0."""
    base = 100 if end0_metric is None else int(end0_metric)
    return {
        "enabled": True,
        "ipv4": {"method": "auto", "route_metric": base + WORSE_METRIC_GAP},
        "ipv6": {"method": "disabled"},
        "wifi": {
            "mode": "infrastructure",
            "auth": "open",
            "ssid": ssid,
        },
    }


def restore_payload(wlan0: dict[str, Any]) -> dict[str, Any]:
    """Put wlan0 back. A disabled adapter is disabled again, with no Wi-Fi profile."""
    enabled = bool(wlan0.get("enabled"))
    ipv4 = wlan0.get("ipv4") if isinstance(wlan0.get("ipv4"), dict) else {}
    method = str((ipv4 or {}).get("method") or ("auto" if enabled else "disabled"))
    if not enabled:
        method = "disabled"
    body: dict[str, Any] = {"enabled": enabled, "ipv4": {"method": method}}
    wifi = wlan0.get("wifi") if isinstance(wlan0.get("wifi"), dict) else None
    if enabled and wifi and wifi.get("ssid"):
        body["wifi"] = {
            "mode": wifi.get("mode") or "infrastructure",
            "auth": wifi.get("auth") or "open",
            "ssid": wifi.get("ssid"),
        }
    return body


def match_access_points(
    access_points: list[dict[str, Any]],
    *,
    allowlist: set[str],
    adopted: set[str],
    require_allowlist: bool,
) -> list[dict[str, Any]]:
    """Keep Shelly setup APs that are on the known list or not adopted yet."""
    found: list[dict[str, Any]] = []
    for point in access_points:
        ssid = str(point.get("ssid") or "")
        parsed = parse_shelly_ssid(ssid)
        if parsed is None:
            continue
        identities = {parsed["sta_mac"], parsed["ble_mac"], parsed["bssid_mac"]}
        on_list = bool(identities & allowlist)
        already = bool(identities & adopted)
        if require_allowlist:
            eligible = on_list and not already
            reason = "" if eligible else ("already adopted" if already else "not on the device list")
        else:
            eligible = not already
            reason = "" if eligible else "already adopted"
        found.append(
            {
                "ssid": ssid,
                "signal": int(point.get("signal") or 0),
                "ap_mac": str(point.get("mac") or ""),
                "sta_mac": parsed["sta_mac"],
                "ble_mac": parsed["ble_mac"],
                "bssid_mac": parsed["bssid_mac"],
                "eligible": eligible,
                "reason": reason,
            }
        )
    found.sort(key=lambda item: (-item["signal"], item["sta_mac"]))
    return found


class SupervisorNetwork:
    """Supervisor network API. Updates are refused for every interface except wlan0."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def interfaces(self) -> list[dict[str, Any]]:
        info = await self._client.network.info()
        raw = _plain(info)
        if isinstance(raw, dict):
            items = raw.get("interfaces") or []
        else:
            items = getattr(info, "interfaces", [])
        return [_plain(item) if not isinstance(item, dict) else item for item in items]

    async def access_points(self) -> list[dict[str, Any]]:
        points = await self._client.network.access_points(WLAN0)
        normalised: list[dict[str, Any]] = []
        for point in points:
            raw = _plain(point)
            if not isinstance(raw, dict):
                raw = {
                    "ssid": getattr(point, "ssid", ""),
                    "signal": getattr(point, "signal", 0),
                    "mac": getattr(point, "mac", ""),
                }
            normalised.append(raw)
        return normalised

    async def update_interface(self, interface: str, config: dict[str, Any]) -> None:
        if interface != WLAN0:
            raise HotspotRefused(
                f"Refusing to update {interface}. Only wlan0 may change, and end0 is left alone.",
                host=True,
            )
        await self._client.network.update_interface(interface, config=_Payload(config))


async def open_supervisor_network(hass: Any) -> SupervisorNetwork:
    """Return the Supervisor network client, or refuse when it is not there."""
    components = getattr(getattr(hass, "config", None), "components", ())
    if "hassio" not in components:
        raise HotspotRefused(
            "The Supervisor is not available. Hotspot provisioning needs Home Assistant OS or Supervised.",
            host=True,
        )
    try:
        from homeassistant.components.hassio import get_supervisor_client
    except ImportError as err:
        raise HotspotRefused(
            "The Supervisor is not available. Hotspot provisioning needs Home Assistant OS or Supervised.",
            host=True,
        ) from err
    try:
        client = get_supervisor_client(hass)
    except Exception as err:  # noqa: BLE001
        raise HotspotRefused(
            "The Supervisor is not available. Hotspot provisioning needs Home Assistant OS or Supervised.",
            host=True,
        ) from err
    return SupervisorNetwork(client)


class HotspotSession:
    """Scan setup APs and provision one device at a time."""

    def __init__(
        self,
        network: SupervisorNetwork,
        *,
        site_ssid: str,
        site_password: str,
        disable_ap: bool,
        fleet_password: str = "",
        dry_run: bool = False,
        rpc: RpcCaller | None = None,
        wait_for_lan: LanWaiter | None = None,
        on_adopted: Adopted | None = None,
        watchdog: float = WATCHDOG_SECONDS,
        auth_params: Callable[[str, str], dict[str, str]] | None = None,
    ) -> None:
        self.network = network
        self.site_ssid = site_ssid
        self.site_password = site_password
        self.disable_ap = disable_ap
        self.fleet_password = fleet_password
        self.dry_run = dry_run
        self._rpc = rpc or _post_rpc
        self._wait_for_lan = wait_for_lan
        self._on_adopted = on_adopted
        self._watchdog = watchdog
        self._auth_params = auth_params
        self._changed = False
        self._snapshot: dict[str, Any] | None = None

    async def targets_from_scan(
        self,
        *,
        allowlist: set[str],
        adopted: set[str],
        require_allowlist: bool,
    ) -> list[dict[str, Any]]:
        interfaces = await self.network.interfaces()
        if not any(str(item.get("interface")) == WLAN0 for item in interfaces):
            raise HotspotRefused(
                "wlan0 is not available. Hotspot provisioning needs a Wi-Fi adapter.",
                host=True,
            )
        points = await self.network.access_points()
        return match_access_points(
            points,
            allowlist=allowlist,
            adopted=adopted,
            require_allowlist=require_allowlist,
        )

    async def provision_all(self, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        eligible = [item for item in targets if item.get("eligible", True)]
        for index, target in enumerate(eligible):
            result = await self.provision_one(target)
            results.append(result)
            if result.get("host"):
                break
            if not self.dry_run and index + 1 < len(eligible):
                await asyncio.sleep(BATCH_PAUSE_SECONDS)
        return results

    async def provision_one(self, target: dict[str, Any]) -> dict[str, Any]:
        self._changed = False
        self._snapshot = None
        try:
            await asyncio.wait_for(self._provision(target), self._watchdog)
        except TimeoutError:
            return self._result(
                target,
                "failed",
                "watchdog",
                "Timed out while wlan0 was in use. wlan0 is restored to its previous state.",
            )
        except HotspotRefused as err:
            return self._result(target, "failed", "refused", err.reason, host=err.host)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Hotspot provisioning failed for %s", target.get("sta_mac"))
            return self._result(target, "failed", "error", str(err))
        else:
            status = "dry_run" if self.dry_run else "ok"
            step = "dry_run" if self.dry_run else "done"
            message = (
                f"Would provision {display_mac(target['sta_mac'])} from {target['ssid']} "
                "without changing wlan0 or end0."
                if self.dry_run
                else f"Provisioned {display_mac(target['sta_mac'])} onto the site Wi-Fi."
            )
            return self._result(target, status, step, message)
        finally:
            if self._changed and self._snapshot is not None:
                await self._restore(self._snapshot)

    async def _provision(self, target: dict[str, Any]) -> None:
        if not self.site_ssid:
            raise HotspotRefused("The site Wi-Fi SSID is not set on Shelly Installer.")
        interfaces = await self.network.interfaces()
        decision = assess_network(interfaces)
        self._snapshot = copy.deepcopy(decision["wlan0"])
        if self.dry_run:
            return
        ipv4 = decision["end0"].get("ipv4") if isinstance(decision["end0"].get("ipv4"), dict) else {}
        payload = join_payload(target["ssid"], (ipv4 or {}).get("route_metric"))
        # Mark wlan0 dirty before the request. A timeout while the Supervisor
        # applies the change still has to put the adapter back.
        self._changed = True
        await self.network.update_interface(WLAN0, payload)
        local_ip = await self._wait_for_address(decision["fingerprint"])
        await self._push_wifi(local_ip, target)
        if not await self._restore(self._snapshot):
            raise HotspotRefused(
                "Could not restore wlan0 after sending Wi-Fi settings. end0 was not changed.",
                host=True,
            )
        self._changed = False
        if self._wait_for_lan is None:
            return
        entry = await self._wait_for_lan([target["sta_mac"], target["ble_mac"]])
        if entry is None:
            raise HotspotRefused(
                f"{display_mac(target['sta_mac'])} did not appear on the LAN after joining the site Wi-Fi."
            )
        if self._on_adopted is not None:
            await self._on_adopted(entry, target["sta_mac"])

    async def _wait_for_address(self, fingerprint: tuple[Any, ...]) -> str:
        deadline = asyncio.get_running_loop().time() + JOIN_WAIT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            interfaces = await self.network.interfaces()
            self._guard_end0(interfaces, fingerprint)
            by_name = {str(item.get("interface")): item for item in interfaces}
            address = _ap_address(by_name.get(WLAN0) or {})
            if address:
                return address
            await asyncio.sleep(0.5)
        raise HotspotRefused(
            f"wlan0 did not get an address on the Shelly setup network {SHELLY_AP_HOST}. end0 was not changed."
        )

    def _guard_end0(self, interfaces: list[dict[str, Any]], fingerprint: tuple[Any, ...]) -> None:
        by_name = {str(item.get("interface")): item for item in interfaces}
        end0 = by_name.get(END0)
        if end0 is None or end0_fingerprint(end0) != fingerprint or default_route_interface(interfaces) != END0:
            raise HotspotRefused(
                "end0 or the default route changed. Restoring wlan0 and stopping.",
                host=True,
            )
        wlan = by_name.get(WLAN0) or {}
        if wlan.get("primary"):
            raise HotspotRefused(
                "wlan0 became the primary interface. Restoring wlan0 and stopping.",
                host=True,
            )

    async def _push_wifi(self, local_ip: str, target: dict[str, Any]) -> None:
        config: dict[str, Any] = {
            "sta": {"enable": True, "ssid": self.site_ssid, "pass": self.site_password},
        }
        if self.disable_ap:
            config["ap"] = {"enable": False}
        await self._rpc(local_ip, "WiFi.SetConfig", {"config": config})
        if not self.fleet_password:
            return
        info = await self._rpc(local_ip, "Shelly.GetDeviceInfo", {})
        device_id = str(info.get("id") or "")
        if not device_id or self._auth_params is None:
            return
        await self._rpc(local_ip, "Shelly.SetAuth", self._auth_params(device_id, self.fleet_password))

    async def _restore(self, snapshot: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(
                self.network.update_interface(WLAN0, restore_payload(snapshot)),
                RESTORE_TIMEOUT,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not restore wlan0 to its previous state")
            return False
        return True

    def _result(
        self,
        target: dict[str, Any],
        status: str,
        step: str,
        message: str,
        *,
        host: bool = False,
    ) -> dict[str, Any]:
        return {
            "mac": display_mac(str(target.get("sta_mac") or "")),
            "ssid": target.get("ssid") or "",
            "ip": SHELLY_AP_HOST,
            "status": status,
            "step": step,
            "signal": target.get("signal"),
            "host": host,
            "error": message,
        }


async def _post_rpc(local_ip: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """POST a Shelly RPC bound to the wlan0 address, not to end0."""
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=8)
    connector = aiohttp.TCPConnector(local_addr=(local_ip, 0))
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                f"http://{SHELLY_AP_HOST}/rpc/{method}",
                json=params,
                timeout=timeout,
            ) as response:
                if response.status >= 400:
                    raise HotspotRefused(f"Shelly {method} returned HTTP {response.status}.")
                try:
                    body = await response.json(content_type=None)
                except Exception:  # noqa: BLE001
                    body = {}
    except HotspotRefused:
        raise
    except Exception as err:  # noqa: BLE001
        raise HotspotRefused(f"Could not call Shelly {method} on {SHELLY_AP_HOST} via {local_ip}.") from err
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        return body["result"]
    return body if isinstance(body, dict) else {}
