"""Live device settings: only fields the device reports, then read back."""

from __future__ import annotations

from pathlib import Path

from custom_components.shelly_bulk.device_list import update_device_row
from custom_components.shelly_bulk.device_settings import (
    apply_live_settings,
    channel_updates,
    read_live_settings,
)


class FakeDevice:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.sys = {"device": {"name": "Hall light"}}
        self.calls: list[tuple[str, object]] = []

    async def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "Sys.GetConfig":
            return self.sys
        if method == "Sys.SetConfig":
            self.sys["device"].update((params or {})["config"]["device"])
            return {}
        if method == "Input.GetConfig":
            return self.config["input:0"]
        if method == "Input.SetConfig":
            self.config["input:0"].update((params or {})["config"])
            return {}
        if method.endswith(".GetConfig"):
            return self.config["switch:0"] if "switch:0" in self.config else self.config["light:0"]
        if method.endswith(".SetConfig"):
            target = "switch:0" if "switch:0" in self.config else "light:0"
            self.config[target].update((params or {})["config"])
            return {}
        return {}


def _relay() -> FakeDevice:
    return FakeDevice(
        {
            "input:0": {"id": 0, "type": "switch", "invert": False},
            "switch:0": {
                "id": 0,
                "in_mode": "follow",
                "initial_state": "off",
                "auto_on": False,
                "auto_on_delay": 0,
                "auto_off": False,
                "auto_off_delay": 30,
            },
        }
    )


async def test_relay_form_hides_dimmer_fields() -> None:
    live = await read_live_settings(_relay())
    assert "name" in live.supported
    assert "input_mode" in live.supported
    assert "auto_off_delay" in live.supported
    assert "fade_rate" not in live.supported
    assert "night_mode" not in live.supported
    assert "min_brightness" not in live.supported
    assert live.values["input_mode"] == "follow"
    assert live.values["name"] == "Hall light"


async def test_dimmer_form_includes_fade_and_night_mode() -> None:
    device = FakeDevice(
        {
            "light:0": {
                "id": 0,
                "in_mode": "dim",
                "initial_state": "on",
                "button_fade_rate": 2,
                "transition_duration": 1.5,
                "range_map": [10, 90],
                "night_mode": {"enable": False, "brightness": 20, "active_between": ["22:00", "06:00"]},
            }
        }
    )
    live = await read_live_settings(device)
    assert "fade_rate" in live.supported
    assert live.values["fade_rate"] == 2
    assert "min_brightness" in live.supported
    assert live.values["max_brightness"] == 90
    assert live.values["night_start"] == "22:00"


async def test_save_reads_back_and_reports_a_rejected_field() -> None:
    device = _relay()
    errors = await apply_live_settings(device, {"input_mode": "detached", "name": "Porch"})
    assert errors == {}
    assert device.config["switch:0"]["in_mode"] == "detached"
    assert device.sys["device"]["name"] == "Porch"

    def _ignore_mode(method, params=None):
        if method == "Switch.SetConfig":
            return {}
        return None

    device.call = _stuck(device)  # type: ignore[method-assign]
    errors = await apply_live_settings(device, {"input_mode": "follow"})
    assert errors == {"input_mode": "not_applied"}
    assert device.config["switch:0"]["in_mode"] == "detached"


def _stuck(device: FakeDevice):
    original = device.call

    async def call(method, params=None):
        if method == "Switch.SetConfig":
            device.calls.append((method, params))
            return {}
        return await original(method, params)

    return call


def test_copy_keeps_the_name_on_the_original_device() -> None:
    copied = channel_updates({"name": "Porch", "room": "Hall", "input_mode": "detached", "fade_rate": 3})
    assert copied == {"input_mode": "detached", "fade_rate": 3}


def test_csv_row_update_keeps_the_other_device(tmp_path: Path) -> None:
    path = tmp_path / "devices.csv"
    path.write_text(
        "# keep me\nmac,name,room,input\n00:00:00:00:00:0A,Old,Hall,follow\n00:00:00:00:00:0B,Other,Kitchen,follow\n",
        encoding="utf-8",
    )
    assert update_device_row(path, "00000000000A", {"name": "Porch", "room": "Porch", "input": "detached"})
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# keep me")
    assert "Porch" in text
    assert "Other,Kitchen" in text
    assert "Old" not in text
    assert update_device_row(path, "00000000000C", {"name": "Missing"}) is False
