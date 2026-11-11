"""Pure tests for RPC planning, CSV parsing, and redaction."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from custom_components.shelly_bulk.allowlist import parse_allowlist_csv, resolve_config_path
from custom_components.shelly_bulk.ble import (
    auth_enabled,
    parse_shelly_manufacturer_data,
    rpc_over_ble_enabled,
)
from custom_components.shelly_bulk.const import VERSION
from custom_components.shelly_bulk.models import AllowDevice, ChannelSettings
from custom_components.shelly_bulk.profile import (
    build_set_auth,
    plan_config_calls,
    plan_security_calls,
    security_from_entry,
)
from custom_components.shelly_bulk.redact import SecretFilter, redact
from custom_components.shelly_bulk.util import normalize_mac

ROOT = Path(__file__).resolve().parents[1]


def test_english_translations_match_strings() -> None:
    package = ROOT / "custom_components" / "shelly_bulk"
    strings = json.loads((package / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((package / "translations" / "en.json").read_text(encoding="utf-8"))
    assert english == strings
    menu = strings["options"]["step"]["init"]["menu_options"]
    for option, label in menu.items():
        assert str(label).strip(), option


def test_manifest_version_matches_constant() -> None:
    manifest = (ROOT / "custom_components" / "shelly_bulk" / "manifest.json").read_text()
    assert f'"version": "{VERSION}"' in manifest


def test_repository_has_no_shipped_site_data() -> None:
    # IANA names such as Australia/Melbourne appear only as format examples.
    banned = ("Cheviot", "A0:85:E3")
    roots = [ROOT / "custom_components", ROOT / "tools", ROOT / ".github"]
    files = [path for root in roots for path in root.rglob("*") if path.is_file()]
    files.extend(
        path
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix in {".md", ".txt", ".toml", ".yml", ".yaml"}
    )
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in banned:
            assert needle not in text, f"{needle} found in {path}"


def test_normalize_and_parse_dummy_mac() -> None:
    assert normalize_mac("00:00:00:00:00:0a") == "00000000000A"


def test_manufacturer_flags() -> None:
    # flags 0x0005 = discoverable + RPC, MAC bytes reversed, model 1
    payload = bytes([0x01, 0x05, 0x00, 0x0A, 6, 5, 4, 3, 2, 1, 0x0B, 1, 0])
    parsed = parse_shelly_manufacturer_data({0x0BA9: payload})
    assert parsed is not None
    assert parsed["mac"] == "010203040506"
    assert rpc_over_ble_enabled(parsed["flags"])
    assert not auth_enabled(parsed["flags"])


def test_auth_flag() -> None:
    payload = bytes([0x01, 0x02, 0x00])
    parsed = parse_shelly_manufacturer_data({0x0BA9: payload})
    assert parsed is not None
    assert auth_enabled(parsed["flags"])
    assert not rpc_over_ble_enabled(parsed["flags"])


def test_allowlist_csv_and_path_guard(tmp_path: Path) -> None:
    text = "mac,name,room,input,channel\n00:00:00:00:00:01,Example light,Example room,detached,0\n"
    parsed, errors = parse_allowlist_csv(text)
    assert not errors
    device = parsed.get("000000000001")
    assert device is not None
    assert device.name == "Example light"
    assert device.by_channel[0].input_mode == "detached"
    inside = tmp_path / "shelly_bulk"
    inside.mkdir()
    target = resolve_config_path(str(tmp_path), "shelly_bulk/devices.csv")
    assert target.parent == inside.resolve()
    try:
        resolve_config_path(str(tmp_path), "../secret.csv")
    except ValueError as err:
        assert str(err) == "outside_config"
    else:
        raise AssertionError("path traversal was accepted")


def test_empty_timezone_omits_location() -> None:
    security = security_from_entry(
        {"timezone": ""},
        {"disable_cloud": True, "disable_ap": True, "disable_ble_rpc": True},
        "",
    )
    calls = plan_security_calls(security)
    assert all(call.method != "Sys.SetConfig" for call in calls)
    blob = str([call.params for call in calls])
    assert "location" not in blob


def test_plan_detached_switch_and_dimmer_notes() -> None:
    security = security_from_entry(
        {"timezone": "UTC"},
        {"disable_cloud": True, "disable_ap": True, "disable_ble_rpc": False},
        "Example light",
    )
    device = AllowDevice(mac="000000000001", name="Example light", room="Example room")
    device.by_channel[0] = ChannelSettings(input_type="button", input_mode="detached", invert=True)
    config = {
        "input:0": {"id": 0, "type": "switch"},
        "switch:0": {"id": 0, "in_mode": "follow"},
        "light:0": {"id": 0, "initial_state": "off"},
    }
    calls, notes = plan_config_calls(
        security=security,
        options={"apply_dimmer_profile": True, "power_on_brightness": 40, "transition_up": 2},
        config=config,
        device=device,
    )
    methods = [call.method for call in calls]
    assert "Sys.SetConfig" in methods
    assert "Cloud.SetConfig" in methods
    ble = next(call for call in calls if call.method == "BLE.SetConfig")
    assert ble.params["config"]["rpc"]["enable"] is True
    assert ble.params["config"]["enable"] is True
    switch = next(call for call in calls if call.method == "Switch.SetConfig")
    assert switch.params["config"]["in_mode"] == "detached"
    assert any("power-on brightness" in note for note in notes)
    assert any("separate ramp" in note for note in notes)


def test_set_auth_does_not_echo_password() -> None:
    params = build_set_auth("shellyplus1-000000000001", "example-fleet-pass")
    blob = str(params)
    assert "example-fleet-pass" not in blob
    assert params["user"] == "admin"
    assert len(params["ha1"]) == 64


def test_secret_filter_masks_logs(caplog: logging.LogCaptureFixture) -> None:
    logger = logging.getLogger("custom_components.shelly_bulk.test")
    logger.addFilter(SecretFilter(lambda: ["example-fleet-pass"]))
    logger.setLevel(logging.INFO)
    with caplog.at_level(logging.INFO):
        logger.info("password was example-fleet-pass")
    assert "example-fleet-pass" not in caplog.text
    assert "***" in caplog.text
    assert redact("ssid example-ssid", ["example-ssid"]) == "ssid ***"
