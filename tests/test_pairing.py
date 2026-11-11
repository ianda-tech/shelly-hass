"""Every switch in_mode / initial_state combination stays valid."""

from __future__ import annotations

import pytest

from custom_components.shelly_bulk.pairing import (
    InvalidDeviceValue,
    resolved_pair,
    valid_initial_states,
)

SWITCH_MODES = ("follow", "flip", "momentary", "detached", "activate", "cycle")
SWITCH_STATES = ("off", "on", "restore_last", "match_input")
LABELS = ("Off", "On", "Restore last", "Match input", "Toggle", "toggle")


def _assert_switch_pair(mode: str, initial: str) -> None:
    assert initial in valid_initial_states("switch", mode)
    assert initial in {"off", "on", "restore_last", "match_input"}
    if mode == "follow":
        assert initial == "match_input"
    if initial == "match_input":
        assert mode in {"follow", "flip"}


def test_every_switch_combination_is_sent_as_a_valid_pair() -> None:
    for current_mode in SWITCH_MODES:
        for current_initial in SWITCH_STATES:
            for new_mode in SWITCH_MODES + (None,):
                for new_initial in SWITCH_STATES + LABELS + (None,):
                    if new_mode is None and new_initial is None:
                        continue
                    if new_initial in {"Toggle", "toggle"}:
                        with pytest.raises(InvalidDeviceValue):
                            resolved_pair(
                                "switch",
                                current_mode,
                                current_initial,
                                new_mode=new_mode,
                                new_initial=new_initial,
                            )
                        continue
                    mode, initial, _note = resolved_pair(
                        "switch",
                        current_mode,
                        current_initial,
                        new_mode=new_mode,
                        new_initial=new_initial,
                    )
                    _assert_switch_pair(mode, initial)


def test_follow_forces_match_input_and_leaving_follow_uses_restore_last() -> None:
    mode, initial, note = resolved_pair("switch", "detached", "off", new_mode="follow")
    assert (mode, initial) == ("follow", "match_input")
    assert note

    mode, initial, note = resolved_pair("switch", "follow", "match_input", new_mode="detached")
    assert (mode, initial) == ("detached", "restore_last")
    assert "restore_last" in (note or "")


def test_labels_are_not_sent() -> None:
    mode, initial, _note = resolved_pair("switch", "detached", "off", new_initial="Restore last")
    assert initial == "restore_last"
    mode, initial, _note = resolved_pair("switch", "follow", "match_input", new_mode="Flip")
    assert mode == "flip"


def test_light_keeps_toggle_and_drops_match_input() -> None:
    mode, initial, _note = resolved_pair("light", "follow", "off", new_initial="toggle")
    assert (mode, initial) == ("follow", "toggle")
    _mode, initial, note = resolved_pair("light", "follow", "off", new_initial="match_input")
    assert initial == "restore_last"
    assert note
