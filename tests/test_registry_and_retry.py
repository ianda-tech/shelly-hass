"""Home Assistant 2026.11 device registry calls, and retrying failed adoptions."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.shelly_bulk.const import ALLTERCO_MFID, DOMAIN
from custom_components.shelly_bulk.entity import device_by_identifier, shelly_device_info
from custom_components.shelly_bulk.models import AllowDevice

from test_integration import _entry


def _advert(flags: int) -> dict[int, bytes]:
    # MAC bytes are reversed. 6,5,4,3,2,1 is 01:02:03:04:05:06.
    return {ALLTERCO_MFID: bytes([0x01, flags & 0xFF, (flags >> 8) & 0xFF, 0x0A, 6, 5, 4, 3, 2, 1])}


async def test_entities_add_when_the_core_device_owns_the_mac(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    entry = _entry()
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="shelly1pmminig3-48f6eeba6efc",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "S3SW-001P8EU"},
    )
    entry.add_to_hass(hass)
    shelly.add_to_hass(hass)
    registry = dr.async_get(hass)
    core = registry.async_get_or_create(
        config_entry_id=shelly.entry_id,
        identifiers={("shelly", "48F6EEBA6EFC")},
        connections={(dr.CONNECTION_NETWORK_MAC, "48:f6:ee:ba:6e:fc")},
        name="shelly1pmminig3-48f6eeba6efc",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    info = shelly_device_info(hass, shelly)
    assert "via_device" not in info
    assert info["via_device_id"] == core.id
    companion = device_by_identifier(
        registry,
        ("shelly_bulk", f"companion_{shelly.entry_id}"),
        entry.entry_id,
    )
    assert companion is not None
    assert companion.via_device_id == core.id
    assert companion.connections == set()
    assert (dr.CONNECTION_NETWORK_MAC, "48:f6:ee:ba:6e:fc") in registry.async_get(core.id).connections

    registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    domains = {item.domain for item in registered if item.device_id == companion.id}
    assert {"button", "number", "select", "sensor", "switch"} <= domains


async def test_power_cycle_is_suggested_only_without_ble_rpc(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]

    runtime.record("00000000000C", "failed", "Could not connect.")
    assert "power-cycle" not in runtime.results[-1]["error"].lower()

    runtime.provisioner.note_advertisement(_advert(0x0004), "with-rpc")
    runtime.record("010203040506", "failed", "Could not connect.")
    assert "power-cycle" not in runtime.results[-1]["error"].lower()

    runtime.provisioner.note_advertisement(_advert(0x0001), "no-rpc")
    runtime.record("010203040506", "failed", "Could not connect.")
    assert "Power-cycle" in runtime.results[-1]["error"]
    assert "without Bluetooth RPC" in runtime.results[-1]["error"]


async def test_retry_failed_requeues_the_mac_for_the_next_advertisement(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    mac = "00000000000A"
    runtime.allowlist.devices[mac] = AllowDevice(mac=mac)
    runtime.provisioner.active = True
    runtime.provisioner._done.add(mac)
    runtime.provisioner._flows_tried.add("flow-1")
    runtime.provisioner._flow_mac["flow-1"] = mac
    runtime.record(mac, "failed", "Provisioning failed after the configured retries.")
    assert runtime.failed == 1

    started: list[tuple[str, str]] = []

    async def _guarded(flow_id, seen):
        started.append((flow_id, seen))

    monkeypatch.setattr(runtime.provisioner, "_guarded", _guarded)
    response = await hass.services.async_call(
        DOMAIN,
        "retry_failed",
        {},
        blocking=True,
        return_response=True,
    )
    assert response["count"] == 1
    assert response["macs"] == ["00:00:00:00:00:0A"]
    assert runtime.failed == 0
    assert runtime.results == []
    assert mac not in runtime.provisioner._done
    assert "flow-1" not in runtime.provisioner._flows_tried

    hass.config_entries.flow.async_progress = lambda include_uninitialized=False: [
        {
            "flow_id": "flow-1",
            "handler": "shelly",
            "step_id": "bluetooth_confirm",
            "context": {"source": "bluetooth", "unique_id": "00:00:00:00:00:0A"},
        }
    ]
    await runtime.provisioner.scan_once()
    await hass.async_block_till_done()
    assert started == [("flow-1", mac)]

    runtime.record(mac, "failed", "Could not connect.")
    button = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{entry.entry_id}_retry_failed")
    assert button is not None
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert runtime.failed == 0
    assert runtime.results == []


async def test_the_same_mac_is_not_counted_or_retried_twice(hass, monkeypatch) -> None:
    async def _offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _offline,
    )
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    mac = "00000000000A"
    runtime.allowlist.devices[mac] = AllowDevice(mac=mac)
    runtime.record(mac, "failed", "Provisioning failed after the configured retries.")
    runtime.record(mac, "failed", "Provisioning failed after the configured retries.")
    assert runtime.failed == 1
    assert len(runtime.failed_devices()) == 1
    assert runtime.failed_devices()[0]["mac"] == "00:00:00:00:00:0A"
    assert "retries" in runtime.failed_devices()[0]["reason"]
    assert runtime.failed_devices()[0]["at"]

    runtime.provisioner.active = True
    hass.config_entries.flow.async_progress = lambda *args, **kwargs: [
        {
            "flow_id": "flow-again",
            "handler": "shelly",
            "step_id": "wifi_scan_failed",
            "context": {"source": "bluetooth", "unique_id": "00:00:00:00:00:0A"},
        }
    ]
    await runtime.provisioner.scan_once()
    assert runtime.provisioner._inflight == set()
    assert runtime.failed == 1
