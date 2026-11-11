"""Config flow, provisioning, and service tests against a Home Assistant harness."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shelly_bulk.const import (
    CONF_BLE_SCANNER_MODE,
    CONF_DISABLE_AP,
    CONF_DISABLE_BLE_RPC,
    CONF_DISABLE_CLOUD,
    CONF_FLEET_PASSWORD,
    CONF_REQUIRE_ALLOWLIST,
    CONF_SITE_NAME,
    CONF_TIMEZONE,
    CONF_UPDATE_FIRMWARE,
    CONF_WIFI_PASSWORD,
    CONF_WIFI_SSID,
    DOMAIN,
)
from custom_components.shelly_bulk.diagnostics import async_get_config_entry_diagnostics

USER = {
    CONF_SITE_NAME: "Example site",
    CONF_WIFI_SSID: "example-ssid",
    CONF_WIFI_PASSWORD: "example-wifi-pass",
    CONF_FLEET_PASSWORD: "example-fleet-pass",
    CONF_TIMEZONE: "UTC",
}
BEHAVIOUR = {
    CONF_DISABLE_CLOUD: True,
    CONF_DISABLE_AP: True,
    CONF_DISABLE_BLE_RPC: True,
    CONF_UPDATE_FIRMWARE: False,
    CONF_REQUIRE_ALLOWLIST: True,
    CONF_BLE_SCANNER_MODE: "active",
    "concurrency": 2,
    "retries": 1,
    "provisioning_minutes": 30,
}


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="example-site",
        title="Example site",
        data=dict(USER),
        options=dict(BEHAVIOUR),
    )


async def test_config_flow_stores_site_values_and_rejects_bad_timezone(hass) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    bad = dict(USER)
    bad[CONF_TIMEZONE] = "Not/AZone"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], bad)
    assert result["errors"]["timezone"] == "invalid_timezone"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["step_id"] == "behaviour"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], BEHAVIOUR)
    assert result["type"] == "create_entry"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data[CONF_TIMEZONE] == "UTC"
    assert entry.data[CONF_WIFI_PASSWORD] == "example-wifi-pass"
    assert entry.options[CONF_BLE_SCANNER_MODE] == "active"
    assert entry.options[CONF_REQUIRE_ALLOWLIST] is True


async def test_blank_timezone_is_accepted(hass) -> None:
    hass.config.time_zone = "Europe/London"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "user"
    payload = dict(USER)
    payload[CONF_TIMEZONE] = ""
    result = await hass.config_entries.flow.async_configure(result["flow_id"], payload)
    assert result["step_id"] == "behaviour"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], BEHAVIOUR)
    assert result["type"] == "create_entry"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data[CONF_TIMEZONE] == ""


async def test_options_can_clear_timezone(hass) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "security"}
    )
    assert result["step_id"] == "security"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DISABLE_CLOUD: True,
            CONF_DISABLE_AP: True,
            CONF_DISABLE_BLE_RPC: True,
            "clear_timezone": True,
        },
    )
    assert result["type"] == "create_entry"
    assert entry.data[CONF_TIMEZONE] == ""


async def test_setup_sensors_and_diagnostics_redact_secrets(hass) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    adopted = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_adopted")
    assert adopted is not None
    assert hass.states.get(adopted).state == "0"

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["data"][CONF_WIFI_PASSWORD] == "***"
    assert diag["data"][CONF_WIFI_SSID] == "***"
    assert diag["data"][CONF_FLEET_PASSWORD] == "***"
    assert "example-wifi-pass" not in str(diag)
    assert "example-fleet-pass" not in str(diag)


async def test_provisioning_answers_bluetooth_flow_and_sets_scanner(hass, monkeypatch) -> None:
    options = dict(BEHAVIOUR)
    options[CONF_REQUIRE_ALLOWLIST] = False
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="example-site",
        title="Example site",
        data=dict(USER),
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]

    class FakeShelly:
        domain = "shelly"
        entry_id = "shelly-entry"
        unique_id = "00000000000A"
        state = ConfigEntryState.LOADED
        title = "Shelly"

        def __init__(self) -> None:
            self.data = {CONF_HOST: "192.0.2.10", CONF_PORT: 80}
            self.options: dict = {}

    shelly = FakeShelly()

    def _update(entry, *, data=None, options=None, **_kwargs):
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)
        return entry

    monkeypatch.setattr(runtime, "shelly_entry_for", lambda _mac: shelly)
    monkeypatch.setattr(hass.config_entries, "async_update_entry", _update)

    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        async def call(self, method, params=None):
            self.calls.append((method, params))
            return {"restart_required": False}

        async def shutdown(self) -> None:
            return None

        @property
        def config(self):
            return {"input:0": {"id": 0, "type": "switch"}, "switch:0": {"id": 0, "in_mode": "follow"}}

        @property
        def shelly(self):
            return {
                "id": "shelly1-00000000000a",
                "gen": 2,
                "auth_en": False,
                "model": "SNSW-001X16EU",
                "ver": "1.0.0",
            }

    fake = FakeSession()

    async def _open(*_args, **_kwargs):
        return fake

    monkeypatch.setattr("custom_components.shelly_bulk.runtime.async_open_rpc", _open)

    flows = [
        {
            "flow_id": "flow-1",
            "handler": "shelly",
            "step_id": "bluetooth_confirm",
            "context": {"source": "bluetooth", "unique_id": "00000000000A"},
        }
    ]
    submitted: list[dict | None] = []

    async def _configure(flow_id, user_input=None):
        submitted.append(user_input)
        step = flows[0]["step_id"] if flows else None
        if step == "bluetooth_confirm":
            flows[0]["step_id"] = "wifi_scan"
            return {"type": "form", "step_id": "wifi_scan", "flow_id": flow_id}
        if step == "wifi_scan":
            flows[0]["step_id"] = "provision_done"
            return {"type": "progress", "step_id": "do_provision", "flow_id": flow_id}
        flows.clear()
        return {"type": "create_entry", "flow_id": flow_id, "title": "Shelly"}

    hass.config_entries.flow.async_configure = _configure
    hass.config_entries.flow.async_progress = lambda include_uninitialized=False: list(flows)
    hass.config_entries.flow.async_abort = lambda flow_id: None
    runtime.provisioner.active = True

    await runtime.provisioner.drive("flow-1", "00000000000A")

    assert {"ssid": "example-ssid", "password": "example-wifi-pass"} in submitted
    assert not any(
        isinstance(item, dict) and item.get("password") == "example-fleet-pass" for item in submitted
    )
    assert shelly.options[CONF_BLE_SCANNER_MODE] == "active"
    assert shelly.data[CONF_USERNAME] == "admin"
    assert shelly.data[CONF_PASSWORD] == "example-fleet-pass"
    assert any(method == "Shelly.SetAuth" for method, _params in fake.calls)
    assert runtime.adopted == 1
    assert runtime.results[-1]["status"] == "ok"
    assert "example-fleet-pass" not in str(runtime.results)


async def test_credentials_step_is_not_given_the_fleet_password(hass, monkeypatch) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    opened = AsyncMock()
    monkeypatch.setattr("custom_components.shelly_bulk.runtime.async_open_rpc", opened)

    flows = [
        {
            "flow_id": "flow-auth",
            "handler": "shelly",
            "step_id": "credentials",
            "context": {"source": "bluetooth", "unique_id": "00000000000B"},
        }
    ]
    aborted: list[str] = []

    async def _configure(flow_id, user_input=None):
        return {"type": "form", "step_id": "credentials", "flow_id": flow_id}

    hass.config_entries.flow.async_configure = _configure
    hass.config_entries.flow.async_progress = lambda include_uninitialized=False: list(flows)
    hass.config_entries.flow.async_abort = lambda flow_id: aborted.append(flow_id)

    await runtime.provisioner.drive("flow-auth", "00000000000B")
    assert aborted == ["flow-auth"]
    assert runtime.results[-1]["status"] == "skipped_auth"
    opened.assert_not_called()


async def test_import_and_export_round_trip(hass) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    folder = Path(hass.config.path("shelly_bulk_reports"))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "devices.csv").write_text(
        "mac,name,room\n00:00:00:00:00:02,Example lamp,Example room\n",
        encoding="utf-8",
    )
    imported = await hass.services.async_call(
        DOMAIN,
        "import_allowlist",
        {"filename": "shelly_bulk_reports/devices.csv"},
        blocking=True,
        return_response=True,
    )
    assert imported["count"] == 1

    exported = await hass.services.async_call(
        DOMAIN,
        "export_report",
        {"format": "json"},
        blocking=True,
        return_response=True,
    )
    assert Path(exported["json"]).is_file()
    text = Path(exported["json"]).read_text(encoding="utf-8")
    assert "00:00:00:00:00:02" in text
    assert "example-wifi-pass" not in text


async def test_provisioning_switch(hass) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    from homeassistant.helpers import entity_registry as er

    switch_id = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_provisioning")
    assert switch_id is not None
    await hass.services.async_call(DOMAIN, "start_provisioning", {"provisioning_minutes": 5}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(switch_id).state == "on"
    await hass.services.async_call(DOMAIN, "stop_provisioning", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(switch_id).state == "off"
