"""Secure profile and advanced settings against a fake RPC session."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shelly_bulk.const import CONF_FLEET_PASSWORD, CONF_SITE_NAME, DOMAIN
from custom_components.shelly_bulk.security import SecureProfile, evaluate_security

PASSWORD = "example-device-pass"


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.config = {"switch:0": {"id": 0, "in_mode": "follow", "initial_state": "off"}, "mqtt": {"enable": True}}
        self._shelly = {"id": "shelly1-00000000000a", "gen": 2, "auth_en": False, "model": "SNSW-001X16EU", "ver": "1.2.0"}
        self._configs = {
            "Cloud.GetConfig": {"enable": True},
            "WiFi.GetConfig": {"ap": {"enable": True}},
            "BLE.GetConfig": {"enable": True, "rpc": {"enable": True}},
            "MQTT.GetConfig": {"enable": True},
            "Ws.GetConfig": {"enable": False},
            "Sys.GetConfig": {
                "device": {"name": "Example", "eco_mode": False, "discoverable": True},
                "debug": {
                    "mqtt": {"enable": False},
                    "websocket": {"enable": True},
                    "udp": {"addr": None},
                    "file_log": {"enable": False},
                },
                "rpc_udp": {"listen_port": None},
            },
        }

    @property
    def shelly(self):
        return self._shelly

    async def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "Shelly.GetDeviceInfo":
            return dict(self._shelly)
        if method == "Shelly.SetAuth":
            assert PASSWORD not in str(params)
            self._shelly["auth_en"] = True
            return None
        if method.endswith(".SetConfig") and isinstance(params, dict):
            self._merge(method.replace(".SetConfig", ".GetConfig"), params.get("config") or {})
            return {"restart_required": False}
        if method.endswith(".GetConfig"):
            if method == "Input.GetConfig":
                return {"id": 0, "type": "switch"}
            if method == "Switch.GetConfig":
                return dict(self.config["switch:0"])
            return self._configs.get(method, {"_error": "missing"})
        return {}

    def _merge(self, getter: str, config: dict) -> None:
        current = self._configs.setdefault(getter, {})
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                current[key].update(value)
            else:
                current[key] = value
        if getter == "Switch.GetConfig":
            self.config["switch:0"].update(config)

    async def shutdown(self) -> None:
        return None


def test_checklist_marks_missing_mqtt_as_not_a_failure() -> None:
    state = {
        "shelly": {"auth_en": True, "ver": "1.2.0"},
        "cloud": {"enable": False},
        "wifi": {"ap": {"enable": False}},
        "ble": {"enable": True, "rpc": {"enable": False}},
        "mqtt": {"_error": "not found"},
        "ws": {"enable": False},
        "sys": {"device": {"discoverable": False}, "debug": {}, "rpc_udp": {}},
    }
    profile = SecureProfile(disable_mqtt=True, restrict_web_ui=True, firmware_manual=True)
    report = evaluate_security(state, profile, True)
    assert report["ok"] is True
    assert report["mqtt_off"] is None
    assert report["auth_on"] is True
    assert PASSWORD not in str(report)


async def test_secure_devices_rotates_password_and_reconnects(hass, monkeypatch) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="example-site",
        title="Example site",
        data={
            CONF_SITE_NAME: "Example site",
            "wifi_ssid": "example-ssid",
            "wifi_password": "example-wifi-pass",
            CONF_FLEET_PASSWORD: PASSWORD,
            "timezone": "UTC",
        },
        options={"secure_disable_mqtt": True, "secure_restrict_web_ui": True, "secure_firmware_manual": True},
    )
    entry.add_to_hass(hass)
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="00000000000A",
        title="Example Shelly",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80},
    )
    shelly.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    fake = FakeSession()
    opens: list[tuple] = []

    async def _open(_hass, host, port, username, password, verify_ssl):
        opens.append((username, password))
        return fake

    monkeypatch.setattr("custom_components.shelly_bulk.runtime.async_open_rpc", _open)

    result = await hass.services.async_call(
        DOMAIN,
        "secure_devices",
        {"mac": "00000000000A", "disable_mqtt": True},
        blocking=True,
        return_response=True,
    )
    report = result["results"][0]
    assert report["ok"] is True
    assert report["auth_on"] is True
    assert report["cloud_off"] is True
    assert report["ap_off"] is True
    assert report["ble_rpc_off"] is True
    assert report["reconnected"] is True
    assert PASSWORD not in str(result)
    assert any(method == "Shelly.SetAuth" for method, _params in fake.calls)
    assert any(method == "Cloud.SetConfig" for method, _params in fake.calls)
    assert opens[-1] == ("admin", PASSWORD)
    assert shelly.data[CONF_USERNAME] == "admin"
    assert shelly.data[CONF_PASSWORD] == PASSWORD
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    audit_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_security_audit")
    assert audit_id is not None
    assert hass.states.get(audit_id).state == "1/1"


async def test_secure_devices_leaves_an_existing_password_unchanged(hass, monkeypatch) -> None:
    stored = "already-on-the-shelly"
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="example-site",
        title="Example site",
        data={
            CONF_SITE_NAME: "Example site",
            "wifi_ssid": "example-ssid",
            "wifi_password": "example-wifi-pass",
            CONF_FLEET_PASSWORD: PASSWORD,
            "timezone": "UTC",
        },
        options={},
    )
    entry.add_to_hass(hass)
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="00000000000A",
        title="Example Shelly",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, CONF_USERNAME: "admin", CONF_PASSWORD: stored},
    )
    shelly.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    fake = FakeSession()
    fake._shelly["auth_en"] = True

    async def _open(_hass, host, port, username, password, verify_ssl):
        return fake

    monkeypatch.setattr("custom_components.shelly_bulk.runtime.async_open_rpc", _open)
    result = await hass.services.async_call(
        DOMAIN,
        "secure_devices",
        {"mac": "00000000000A"},
        blocking=True,
        return_response=True,
    )
    report = result["results"][0]
    assert report["auth_on"] is True
    assert not any(method == "Shelly.SetAuth" for method, _params in fake.calls)
    assert shelly.data[CONF_PASSWORD] == stored
    assert shelly.data[CONF_USERNAME] == "admin"
    assert any("already has a login" in note for note in report["notes"])
    assert stored not in str(result)
    assert PASSWORD not in str(result)


async def test_advanced_service_reads_back_and_skips_missing_led(hass, monkeypatch) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SITE_NAME: "Example site", "wifi_ssid": "example-ssid", "wifi_password": "x", "timezone": "UTC"},
        options={},
    )
    entry.add_to_hass(hass)
    shelly = MockConfigEntry(
        domain="shelly",
        unique_id="00000000000A",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, CONF_USERNAME: "admin", CONF_PASSWORD: PASSWORD},
    )
    shelly.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    fake = FakeSession()

    async def _open(*_args, **_kwargs):
        return fake

    monkeypatch.setattr("custom_components.shelly_bulk.runtime.async_open_rpc", _open)
    result = await hass.services.async_call(
        DOMAIN,
        "set_advanced",
        {"mac": "00000000000A", "cloud": False, "input_mode": "detached", "status_led": False, "scanner_mode": "active"},
        blocking=True,
        return_response=True,
    )
    row = result["results"][0]
    assert row["read_back"]["cloud"] is False
    assert row["read_back"]["input_mode"] == "detached"
    assert row["read_back"]["status_led"] is None
    assert any("LED" in note for note in row["notes"])
    assert shelly.options["ble_scanner_mode"] == "active"
    assert PASSWORD not in str(result)

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    cloud = registry.async_get_entity_id("switch", DOMAIN, f"{shelly.entry_id}_cloud")
    assert cloud is not None
    assert registry.async_get(cloud).disabled_by is RegistryEntryDisabler.INTEGRATION
