"""Hotspot provisioning must not touch end0, and must put wlan0 back."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.shelly_bulk.hotspot import (
    HotspotRefused,
    HotspotSession,
    SupervisorNetwork,
    assess_network,
    join_payload,
    mac_plus,
    open_supervisor_network,
    parse_shelly_ssid,
    restore_payload,
)
from custom_components.shelly_bulk.models import AllowDevice

import custom_components.shelly_bulk.hotspot as hotspot


SSID = "Shelly1PMMiniG3-48F6EEB96270"
STA = "48F6EEB96270"


def _end0(**changes) -> dict:
    interface = {
        "interface": "end0",
        "enabled": True,
        "connected": True,
        "primary": True,
        "mac": "02:00:00:00:00:01",
        "ipv4": {
            "method": "static",
            "address": ["192.0.2.10/24"],
            "gateway": "192.0.2.1",
            "route_metric": 100,
        },
    }
    interface.update(changes)
    return interface


def _wlan(**changes) -> dict:
    interface = {
        "interface": "wlan0",
        "enabled": False,
        "connected": False,
        "primary": False,
        "mac": "02:00:00:00:00:02",
        "ipv4": {"method": "disabled", "address": [], "gateway": None, "route_metric": None},
    }
    interface.update(changes)
    return interface


class FakeNetwork:
    """Stand-in for the Supervisor network client."""

    def __init__(self, interfaces: list[dict], points: list[dict] | None = None, *, on_join=None) -> None:
        self.interfaces = interfaces
        self.points = points or []
        self.calls: list[tuple[str, dict]] = []
        self.on_join = on_join

    async def info(self):
        return {"interfaces": self.interfaces}

    async def access_points(self, interface: str):
        assert interface == "wlan0"
        return self.points

    async def update_interface(self, interface: str, config) -> None:
        body = config.to_dict() if hasattr(config, "to_dict") else config
        self.calls.append((interface, body))
        if body.get("enabled"):
            if self.on_join is not None:
                await self.on_join(self, body)
            else:
                self._associate(body)
        else:
            for item in self.interfaces:
                if item["interface"] == "wlan0":
                    item["enabled"] = False
                    item["connected"] = False
                    item["primary"] = False
                    item["ipv4"] = {
                        "method": "disabled",
                        "address": [],
                        "gateway": None,
                        "route_metric": None,
                    }

    def _associate(self, body: dict) -> None:
        for item in self.interfaces:
            if item["interface"] != "wlan0":
                continue
            item["enabled"] = True
            item["connected"] = True
            item["primary"] = False
            item["ipv4"] = {
                "method": "auto",
                "address": ["192.168.33.2/24"],
                "gateway": "192.168.33.1",
                "route_metric": body["ipv4"]["route_metric"],
            }


def _client(interfaces, points=None, **kwargs) -> SupervisorNetwork:
    return SupervisorNetwork(SimpleNamespace(network=FakeNetwork(interfaces, points, **kwargs)))


def _session(network: SupervisorNetwork, **kwargs) -> HotspotSession:
    calls: list[tuple[str, str, dict]] = []

    async def _rpc(local_ip: str, method: str, params: dict) -> dict:
        calls.append((local_ip, method, params))
        if method == "Shelly.GetDeviceInfo":
            return {"id": "shelly1pmminig3-48f6eeb96270"}
        return {}

    session = HotspotSession(
        network,
        site_ssid="house",
        site_password="secret-wifi",
        disable_ap=True,
        rpc=kwargs.pop("rpc", _rpc),
        **kwargs,
    )
    session.rpc_calls = calls  # type: ignore[attr-defined]
    return session


def _target() -> dict:
    return {
        "ssid": SSID,
        "signal": 62,
        "sta_mac": STA,
        "ble_mac": mac_plus(STA, 2),
        "bssid_mac": mac_plus(STA, 1),
        "eligible": True,
        "reason": "",
    }


def test_ssid_mac_offsets() -> None:
    parsed = parse_shelly_ssid(SSID)
    assert parsed is not None
    assert parsed["sta_mac"] == STA
    assert parsed["bssid_mac"] == mac_plus(STA, 1)
    assert parsed["ble_mac"] == mac_plus(STA, 2)
    assert parse_shelly_ssid("neighbour") is None


def test_join_payload_is_wlan_only_and_worse_metric() -> None:
    payload = join_payload(SSID, 100)
    assert payload["enabled"] is True
    assert payload["ipv4"] == {"method": "auto", "route_metric": 300}
    assert payload["wifi"]["auth"] == "open"
    assert payload["wifi"]["ssid"] == SSID
    assert "end0" not in payload
    assert restore_payload(_wlan()) == {"enabled": False, "ipv4": {"method": "disabled"}}


@pytest.mark.parametrize(
    ("interfaces", "message"),
    [
        ([_wlan()], "only network interface"),
        ([_end0(), _wlan(primary=True)], "wlan0 is the primary"),
        ([_end0(connected=False), _wlan()], "end0 is not connected"),
        ([_end0(primary=False), _wlan()], "end0 is not the primary"),
        ([_wlan()], "only network interface"),
        (
            [
                {
                    "interface": "eth1",
                    "enabled": True,
                    "connected": True,
                    "primary": True,
                    "ipv4": {
                        "method": "auto",
                        "address": ["10.0.0.8/24"],
                        "gateway": "10.0.0.1",
                        "route_metric": 50,
                    },
                },
                _wlan(),
            ],
            "end0 is not available",
        ),
        (
            [
                _end0(
                    ipv4={
                        "method": "static",
                        "address": ["192.0.2.10/24"],
                        "gateway": None,
                        "route_metric": 100,
                    }
                ),
                _wlan(),
            ],
            "default route",
        ),
    ],
)
def test_assess_refuses_before_any_change(interfaces, message) -> None:
    with pytest.raises(HotspotRefused, match=message):
        assess_network(interfaces)


async def test_supervisor_missing_is_refused() -> None:
    hass = SimpleNamespace(config=SimpleNamespace(components=set()))
    with pytest.raises(HotspotRefused, match="Supervisor"):
        await open_supervisor_network(hass)


async def test_refuses_to_update_end0() -> None:
    class Boom:
        async def update_interface(self, interface, config):
            raise AssertionError(interface)

    network = SupervisorNetwork(SimpleNamespace(network=Boom()))
    with pytest.raises(HotspotRefused, match="end0"):
        await network.update_interface("end0", {"enabled": True})


async def test_provision_restores_wlan0_and_sends_wifi_from_that_address(monkeypatch) -> None:
    monkeypatch.setattr(hotspot, "BATCH_PAUSE_SECONDS", 0)
    network = _client([_end0(), _wlan()], [{"ssid": SSID, "signal": 62, "mac": "AA:BB:CC:DD:EE:FF"}])
    session = _session(network)
    found = await session.targets_from_scan(allowlist={STA}, adopted=set(), require_allowlist=True)
    assert found[0]["eligible"] is True
    assert found[0]["signal"] == 62
    results = await session.provision_all(found)
    assert results[0]["status"] == "ok"
    assert results[0]["mac"] == "48:F6:EE:B9:62:70"
    fake = network._client.network
    assert [interface for interface, _body in fake.calls] == ["wlan0", "wlan0"]
    assert fake.calls[0][1]["wifi"]["ssid"] == SSID
    assert fake.calls[1][1] == {"enabled": False, "ipv4": {"method": "disabled"}}
    assert session.rpc_calls[0][0] == "192.168.33.2"
    assert session.rpc_calls[0][1] == "WiFi.SetConfig"
    assert session.rpc_calls[0][2]["config"]["sta"]["ssid"] == "house"
    assert session.rpc_calls[0][2]["config"]["ap"] == {"enable": False}
    assert "end0" not in fake.calls[0][1]


async def test_end0_change_aborts_and_restores_without_rpc() -> None:
    async def _steal(fake: FakeNetwork, _body: dict) -> None:
        fake._associate(_body)
        for item in fake.interfaces:
            if item["interface"] == "end0":
                item["primary"] = False

    network = _client([_end0(), _wlan()], on_join=_steal)
    session = _session(network)
    result = await session.provision_one(_target())
    assert result["status"] == "failed"
    assert result["host"] is True
    assert "end0" in result["error"]
    fake = network._client.network
    assert [interface for interface, _body in fake.calls] == ["wlan0", "wlan0"]
    assert fake.calls[-1][1]["enabled"] is False
    assert session.rpc_calls == []


async def test_failure_during_join_still_restores_wlan0(monkeypatch) -> None:
    monkeypatch.setattr(hotspot, "WATCHDOG_SECONDS", 0.05)

    async def _hang(fake: FakeNetwork, body: dict) -> None:
        fake.calls.append(("applied", body))
        await asyncio.sleep(5)

    network = _client([_end0(), _wlan()], on_join=_hang)
    session = _session(network, watchdog=0.05)
    result = await session.provision_one(_target())
    assert result["status"] == "failed"
    assert result["step"] == "watchdog"
    fake = network._client.network
    assert fake.calls[-1][0] == "wlan0"
    assert fake.calls[-1][1]["enabled"] is False
    assert session.rpc_calls == []


async def test_dry_run_does_not_update_the_supervisor() -> None:
    network = _client([_end0(), _wlan()])
    session = _session(network, dry_run=True)
    result = await session.provision_one(_target())
    assert result["status"] == "dry_run"
    assert network._client.network.calls == []
    assert session.rpc_calls == []


async def test_unsafe_network_does_not_update_and_stops_the_batch(monkeypatch) -> None:
    monkeypatch.setattr(hotspot, "BATCH_PAUSE_SECONDS", 0)
    network = _client([_end0(connected=False), _wlan()])
    session = _session(network)
    second = dict(_target())
    second["sta_mac"] = "48F6EEB96280"
    second["ssid"] = "Shelly1PMMiniG3-48F6EEB96280"
    results = await session.provision_all([_target(), second])
    assert len(results) == 1
    assert results[0]["host"] is True
    assert network._client.network.calls == []


async def test_service_dry_run_uses_the_supervisor_client(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    from test_integration import _entry

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    from custom_components.shelly_bulk.const import DOMAIN

    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime.allowlist.devices[STA] = AllowDevice(mac=STA)
    network = _client([_end0(), _wlan()], [{"ssid": SSID, "signal": 40, "mac": "02:00:00:00:00:22"}])

    async def _open(_hass):
        return network

    monkeypatch.setattr(hotspot, "open_supervisor_network", _open)
    response = await hass.services.async_call(
        DOMAIN,
        "provision_hotspot",
        {"dry_run": True, "mac": STA},
        blocking=True,
        return_response=True,
    )
    assert response["count"] == 1
    assert response["results"][0]["status"] == "dry_run"
    assert network._client.network.calls == []
    assert runtime.hotspot_found[0]["signal"] == 40
