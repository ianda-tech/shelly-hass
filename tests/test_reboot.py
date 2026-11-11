"""Startup and refresh must not write settings or reboot devices."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shelly_bulk.advanced import write_setting
from custom_components.shelly_bulk.const import DOMAIN
from custom_components.shelly_bulk.profile import plan_security_calls, security_from_entry

from test_integration import _entry


class _RecordingSession:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.calls: list[str] = []
        self.shelly = {"gen": 2, "id": "device", "auth_en": True, "model": "S3SW-001P8EU", "ver": "1"}

    async def call(self, method, params=None):
        self.calls.append(method)
        if method == "Cloud.GetConfig":
            return {"enable": False}
        if method == "Switch.GetConfig":
            return dict(self.config["switch:0"])
        if "SetConfig" in method or method == "Shelly.Reboot":
            raise AssertionError(method)
        return {}

    async def shutdown(self) -> None:
        return None


async def test_matching_cloud_value_is_not_written() -> None:
    class Session(_RecordingSession):
        async def call(self, method, params=None):
            self.calls.append(method)
            if method == "Cloud.GetConfig":
                return {"enable": False}
            if method == "Cloud.SetConfig":
                self.calls.append("wrote")
                return {"restart_required": True}
            return {}

    session = Session({})
    read_back, note = await write_setting(session, "cloud", False)
    assert read_back is False
    assert note is None
    assert "Cloud.SetConfig" not in session.calls
    assert "Shelly.Reboot" not in session.calls

    session.calls.clear()

    async def _changed(method, params=None):
        session.calls.append(method)
        if method == "Cloud.GetConfig":
            return {"enable": True} if session.calls.count("Cloud.GetConfig") == 1 else {"enable": False}
        if method == "Cloud.SetConfig":
            return {"restart_required": True}
        return {}

    session.call = _changed
    read_back, _note = await write_setting(session, "cloud", False)
    assert read_back is False
    assert session.calls.count("Cloud.SetConfig") == 1
    read_back, _note = await write_setting(session, "cloud", False)
    assert session.calls.count("Cloud.SetConfig") == 1


def test_security_plan_skips_settings_the_device_already_has() -> None:
    security = security_from_entry(
        {"timezone": "UTC"},
        {"disable_cloud": True, "disable_ap": True, "disable_ble_rpc": True},
        "Porch",
    )
    config = {
        "sys": {"device": {"name": "Porch"}, "location": {"tz": "UTC"}},
        "cloud": {"enable": False},
        "wifi": {"ap": {"enable": False}},
        "ble": {"enable": True, "rpc": {"enable": False}},
    }
    calls = plan_security_calls(security, config)
    assert calls == []


async def test_setup_and_refresh_send_no_setconfig_or_reboot(hass, monkeypatch) -> None:
    seen: list[str] = []

    class Session:
        config = {
            "switch:0": {"id": 0, "in_mode": "follow", "initial_state": "match_input", "auto_off_delay": 0},
            "mqtt": {},
            "ble": {"enable": True, "rpc": {"enable": False}},
            "cloud": {"enable": False},
            "wifi": {"ap": {"enable": False}},
            "sys": {
                "device": {"name": "Porch", "eco_mode": False},
                "location": {"tz": "UTC"},
                "debug": {"mqtt": {"enable": False}, "websocket": {"enable": False}, "udp": {"addr": None}},
            },
        }
        shelly = {"gen": 2, "id": "device", "auth_en": True, "model": "S3SW-001P8EU", "ver": "1"}

        async def call(self, method, params=None):
            seen.append(method)
            if method == "Shelly.GetStatus":
                return {"wifi": {"sta_ip": "192.0.2.10", "ssid": "example", "rssi": -40}}
            if method == "BLE.GetConfig":
                return self.config["ble"]
            if method == "Cloud.GetConfig":
                return self.config["cloud"]
            if method == "WiFi.GetConfig":
                return self.config["wifi"]
            if method == "MQTT.GetConfig":
                return {"enable": False}
            if method == "Sys.GetConfig":
                return self.config["sys"]
            if method == "Switch.GetConfig":
                return self.config["switch:0"]
            if method == "PLUGS_UI.GetConfig" or method == "POWERSTRIP_UI.GetConfig":
                return {"_error": "missing"}
            return {}

        async def shutdown(self) -> None:
            return None

    async def _open(*_args, **_kwargs):
        return Session()

    monkeypatch.setattr("custom_components.shelly_bulk.runtime.async_open_rpc", _open)
    entry = _entry()
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="48F6EEBA6EFC",
        title="Porch",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, "model": "S3SW-001P8EU"},
    )
    entry.add_to_hass(hass)
    shelly.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    await runtime.refresh_network(shelly)
    await runtime.refresh_network(shelly)
    assert seen
    assert not any("SetConfig" in method or method == "Shelly.Reboot" for method in seen)


async def test_reload_listener_does_not_recurse(hass, monkeypatch) -> None:
    from custom_components.shelly_bulk import _reload
    from custom_components.shelly_bulk.runtime import update_entry_if_changed

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert update_entry_if_changed(hass, entry, options=dict(entry.options), data=dict(entry.data)) is False

    depth = {"n": 0}

    async def _enter(_entry_id):
        depth["n"] += 1
        await _reload(hass, entry)

    monkeypatch.setattr(hass.config_entries, "async_reload", _enter)
    await _reload(hass, entry)
    assert depth["n"] == 1
