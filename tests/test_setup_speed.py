"""Entry setup must not wait for device RPC."""

from __future__ import annotations

import asyncio
import inspect

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant.common import MockConfigEntry

from custom_components.shelly_bulk.const import DOMAIN
from custom_components.shelly_bulk.number import LiveNumber
from custom_components.shelly_bulk.select import ConsumptionTypeSelect, OutputSelect
from custom_components.shelly_bulk.sensor import ShellyIpSensor
from custom_components.shelly_bulk.switch import AdvancedSwitch

from test_integration import _entry


def test_added_to_hass_does_not_call_rpc() -> None:
    for cls in (AdvancedSwitch, LiveNumber, OutputSelect, ConsumptionTypeSelect, ShellyIpSensor):
        source = inspect.getsource(cls.async_added_to_hass)
        assert "read_device_setting" not in source
        assert "refresh_network" not in source
        assert "_refresh" not in source
        assert "_open_shelly" not in source


async def test_setup_with_many_offline_devices_returns_quickly(hass, monkeypatch) -> None:
    release = asyncio.Event()
    started = 0

    async def _hang(*_args, **_kwargs):
        nonlocal started
        started += 1
        if started % 2 == 0:
            raise TimeoutError("device offline")
        await release.wait()
        raise TimeoutError("device offline")

    monkeypatch.setattr(
        "custom_components.shelly_bulk.runtime.FleetRuntime._connect_with_retries",
        _hang,
    )
    entry = _entry()
    entry.add_to_hass(hass)
    for index in range(120):
        MockConfigEntry(
            domain="shelly",
            unique_id=f"{index:012X}",
            title=f"shelly-{index}",
            data={"host": f"192.0.2.{index % 200}", "port": 80, "model": "S3SW-001P8EU"},
        ).add_to_hass(hass)

    await asyncio.wait_for(hass.config_entries.async_setup(entry.entry_id), 8)
    assert entry.state is ConfigEntryState.LOADED
    switches = [state for state in hass.states.async_all("switch") if state.entity_id.endswith("_cloud")]
    assert len(switches) == 120
    assert all(state.state == "unavailable" for state in switches)

    release.set()
    await hass.async_block_till_done()
