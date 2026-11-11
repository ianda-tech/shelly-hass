"""Keep Switch in_mode and initial_state a combination the device will accept.

Shelly rejects the pair unless both fields are sent together. `follow` requires
`match_input`. `match_input` is only valid with `follow` or `flip`. A switch
never accepts the dimmer value `toggle`. Display labels are translated to those
device values before any RPC.
"""

from __future__ import annotations

SWITCH_INITIAL = ("off", "on", "restore_last", "match_input")
LIGHT_INITIAL = ("off", "on", "restore_last", "toggle")
MATCH_INPUT_MODES = frozenset({"follow", "flip"})

_CANONICAL = {
    "off": "off",
    "on": "on",
    "restore last": "restore_last",
    "restore_last": "restore_last",
    "match input": "match_input",
    "match_input": "match_input",
    "toggle": "toggle",
    "follow": "follow",
    "flip": "flip",
    "toggle / flip": "flip",
    "momentary": "momentary",
    "detached": "detached",
    "activate": "activate",
    "activation": "activate",
    "dim": "dim",
    "dual dim": "dual_dim",
    "dual_dim": "dual_dim",
    "cycle": "cycle",
    "switch": "switch",
    "button": "button",
}


class InvalidDeviceValue(ValueError):
    """A value that is not a Shelly RPC token and cannot be sent."""


def canonical_token(value: object) -> str | None:
    """Return the device token for a value or a display label. Unknown text is None."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", " ")
    text = " ".join(text.split())
    return _CANONICAL.get(text)


def require_token(value: object, *, what: str) -> str:
    token = canonical_token(value)
    if token is None:
        raise InvalidDeviceValue(
            f"{what} must be a device value such as off, on, restore_last, or match_input, not {value!r}."
        )
    return token


def is_switch(kind: str) -> bool:
    return kind == "switch"


def valid_initial_states(kind: str, in_mode: str | None) -> tuple[str, ...]:
    """Power-on values the device accepts for this output and input behaviour."""
    mode = canonical_token(in_mode) or ""
    if not is_switch(kind):
        return LIGHT_INITIAL
    if mode == "follow":
        return ("match_input",)
    if mode == "flip":
        return SWITCH_INITIAL
    return ("off", "on", "restore_last")


def resolved_pair(
    kind: str,
    current_mode: object,
    current_initial: object,
    *,
    new_mode: object = None,
    new_initial: object = None,
) -> tuple[str, str, str | None]:
    """Return ``(in_mode, initial_state, note)`` safe to send in one SetConfig.

    ``note`` explains an automatic adjustment. Illegal tokens raise
    ``InvalidDeviceValue`` and must not be sent.
    """
    mode_source = new_mode if new_mode is not None else current_mode
    mode = "detached" if mode_source is None else require_token(mode_source, what="Input behaviour")
    if new_initial is None and new_mode is None and current_initial is not None:
        initial = require_token(current_initial, what="Power-on state")
    elif new_initial is None:
        initial = canonical_token(current_initial) or "restore_last"
    else:
        initial = require_token(new_initial, what="Power-on state")

    note: str | None = None
    if not is_switch(kind):
        if initial == "match_input" or initial not in LIGHT_INITIAL:
            note = f"Power-on state {initial!r} is not valid on a {kind}. Using restore_last."
            initial = "restore_last"
        return mode, initial, note

    if initial == "toggle":
        raise InvalidDeviceValue(
            "Power-on state toggle is only for dimmers. A switch accepts off, on, restore_last, or match_input."
        )

    if new_mode is not None and mode == "follow":
        if initial != "match_input":
            note = "Follow requires power-on state match_input, so that is what will be set."
        initial = "match_input"
    elif new_mode is not None and initial == "match_input" and mode not in MATCH_INPUT_MODES:
        note = "match_input is only valid with follow or flip. Power-on state will be restore_last."
        initial = "restore_last"
    elif new_initial is not None and new_mode is None and initial not in valid_initial_states(kind, mode):
        if mode == "follow" and initial in {"off", "on", "restore_last"}:
            note = "Follow only allows match_input. Input behaviour will change to detached so this power-on state can be set."
            mode = "detached"
        else:
            note = f"Power-on state {initial!r} is not valid with input behaviour {mode}. Using restore_last."
            initial = "restore_last"

    allowed = valid_initial_states(kind, mode)
    if mode == "follow":
        initial = "match_input"
    elif initial not in allowed:
        initial = "restore_last" if "restore_last" in allowed else allowed[0]
        note = note or "Adjusted power-on state to a value this input behaviour accepts."
    return mode, initial, note
