"""Config and options flow for Shelly Fleet.

Site values are collected here and stored on the config entry. Nothing in the
package is a default SSID, password, timezone, or device list.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    BLE_SCANNER_MODES,
    CONF_APPLY_DIMMER_PROFILE,
    CONF_APPLY_INPUT_PROFILE,
    CONF_APPLY_OUTPUT_PROFILE,
    CONF_AUTO_OFF,
    CONF_AUTO_OFF_DELAY,
    CONF_AUTO_ON,
    CONF_AUTO_ON_DELAY,
    CONF_BLE_SCANNER_MODE,
    CONF_BUTTON_DIMMING,
    CONF_BUTTON_FADE_RATE,
    CONF_CONCURRENCY,
    CONF_DISABLE_AP,
    CONF_DISABLE_BLE_RPC,
    CONF_DISABLE_CLOUD,
    CONF_FLEET_PASSWORD,
    CONF_INITIAL_STATE,
    CONF_INPUT_INVERT,
    CONF_INPUT_MODE,
    CONF_INPUT_TYPE,
    CONF_MAX_BRIGHTNESS,
    CONF_MIN_BRIGHTNESS,
    CONF_NIGHT_BRIGHTNESS,
    CONF_NIGHT_END,
    CONF_NIGHT_MODE,
    CONF_NIGHT_START,
    CONF_POWER_ON_BRIGHTNESS,
    CONF_PROVISIONING_MINUTES,
    CONF_REQUIRE_ALLOWLIST,
    CONF_RETRIES,
    CONF_SITE_NAME,
    CONF_TIMEZONE,
    CONF_TRANSITION_DOWN,
    CONF_TRANSITION_DURATION,
    CONF_TRANSITION_UP,
    CONF_UPDATE_FIRMWARE,
    CONF_WIFI_PASSWORD,
    CONF_WIFI_SSID,
    DOMAIN,
    UNCHANGED,
)
from .util import as_int, slugify, valid_hhmm

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _choice(options: list[tuple[str, str]]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[{"value": value, "label": label} for value, label in options],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _number(minimum: float, maximum: float, step: float = 1) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX)
    )


_BEHAVIOUR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DISABLE_CLOUD, default=True): BooleanSelector(),
        vol.Required(CONF_DISABLE_AP, default=True): BooleanSelector(),
        vol.Required(CONF_DISABLE_BLE_RPC, default=True): BooleanSelector(),
        vol.Required(CONF_UPDATE_FIRMWARE, default=False): BooleanSelector(),
        vol.Required(CONF_REQUIRE_ALLOWLIST, default=True): BooleanSelector(),
        vol.Required(CONF_BLE_SCANNER_MODE, default="active"): _choice(
            [
                ("active", "Active"),
                ("auto", "Auto"),
                ("passive", "Passive"),
                ("disabled", "Disabled"),
            ]
        ),
        vol.Required(CONF_CONCURRENCY, default=2): _number(1, 5),
        vol.Required(CONF_RETRIES, default=1): _number(0, 3),
        vol.Required(CONF_PROVISIONING_MINUTES, default=30): _number(5, 180),
    }
)


def _behaviour_options(user_input: dict[str, Any]) -> dict[str, Any]:
    mode = user_input[CONF_BLE_SCANNER_MODE]
    if mode not in BLE_SCANNER_MODES:
        mode = "active"
    return {
        CONF_DISABLE_CLOUD: bool(user_input[CONF_DISABLE_CLOUD]),
        CONF_DISABLE_AP: bool(user_input[CONF_DISABLE_AP]),
        CONF_DISABLE_BLE_RPC: bool(user_input[CONF_DISABLE_BLE_RPC]),
        CONF_UPDATE_FIRMWARE: bool(user_input[CONF_UPDATE_FIRMWARE]),
        CONF_REQUIRE_ALLOWLIST: bool(user_input[CONF_REQUIRE_ALLOWLIST]),
        CONF_BLE_SCANNER_MODE: mode,
        CONF_CONCURRENCY: int(user_input[CONF_CONCURRENCY]),
        CONF_RETRIES: int(user_input[CONF_RETRIES]),
        CONF_PROVISIONING_MINUTES: int(user_input[CONF_PROVISIONING_MINUTES]),
    }


class ShellyFleetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collect site Wi-Fi, the fleet password, and generic behaviour."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._user: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            timezone = str(user_input.get(CONF_TIMEZONE) or "").strip()
            if not _valid_timezone(timezone):
                errors[CONF_TIMEZONE] = "invalid_timezone"
            else:
                user_input[CONF_TIMEZONE] = timezone
                await self.async_set_unique_id(slugify(str(user_input[CONF_SITE_NAME])))
                self._abort_if_unique_id_configured()
                self._user = user_input
                return await self.async_step_behaviour()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_NAME): TextSelector(),
                    vol.Required(CONF_WIFI_SSID): TextSelector(),
                    vol.Required(CONF_WIFI_PASSWORD): _PASSWORD,
                    vol.Optional(CONF_FLEET_PASSWORD, default=""): _PASSWORD,
                    vol.Required(CONF_TIMEZONE): TextSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "ha_timezone": self.hass.config.time_zone or "unset",
            },
        )

    async def async_step_behaviour(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=str(self._user[CONF_SITE_NAME]),
                data={
                    CONF_SITE_NAME: str(self._user[CONF_SITE_NAME]).strip(),
                    CONF_WIFI_SSID: str(self._user[CONF_WIFI_SSID]),
                    CONF_WIFI_PASSWORD: str(self._user[CONF_WIFI_PASSWORD]),
                    CONF_FLEET_PASSWORD: str(self._user.get(CONF_FLEET_PASSWORD) or ""),
                    CONF_TIMEZONE: str(self._user[CONF_TIMEZONE]),
                },
                options=_behaviour_options(user_input),
            )
        return self.async_show_form(step_id="behaviour", data_schema=_BEHAVIOUR_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ShellyFleetOptionsFlow:
        return ShellyFleetOptionsFlow()


class ShellyFleetOptionsFlow(OptionsFlow):
    """Edit Wi-Fi, security, profiles, and import an allowlist."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["wifi", "security", "inputs", "outputs", "dimmers", "provisioning", "allowlist"],
        )

    async def async_step_wifi(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            data = dict(self.config_entry.data)
            data[CONF_WIFI_SSID] = str(user_input[CONF_WIFI_SSID])
            if str(user_input.get(CONF_WIFI_PASSWORD) or ""):
                data[CONF_WIFI_PASSWORD] = str(user_input[CONF_WIFI_PASSWORD])
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="wifi",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_WIFI_SSID): TextSelector(),
                        vol.Optional(CONF_WIFI_PASSWORD, default=""): _PASSWORD,
                    }
                ),
                {CONF_WIFI_SSID: self.config_entry.data.get(CONF_WIFI_SSID, "")},
            ),
        )

    async def async_step_security(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(self.config_entry.data)
            options = dict(self.config_entry.options)
            timezone = str(user_input.get(CONF_TIMEZONE) or "").strip()
            if timezone:
                if not _valid_timezone(timezone):
                    errors[CONF_TIMEZONE] = "invalid_timezone"
                else:
                    data[CONF_TIMEZONE] = timezone
            if str(user_input.get(CONF_FLEET_PASSWORD) or ""):
                data[CONF_FLEET_PASSWORD] = str(user_input[CONF_FLEET_PASSWORD])
            if not errors:
                options[CONF_DISABLE_CLOUD] = bool(user_input[CONF_DISABLE_CLOUD])
                options[CONF_DISABLE_AP] = bool(user_input[CONF_DISABLE_AP])
                options[CONF_DISABLE_BLE_RPC] = bool(user_input[CONF_DISABLE_BLE_RPC])
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
                return self.async_create_entry(data=options)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="security",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_FLEET_PASSWORD, default=""): _PASSWORD,
                        vol.Optional(CONF_TIMEZONE, default=""): TextSelector(),
                        vol.Required(CONF_DISABLE_CLOUD, default=True): BooleanSelector(),
                        vol.Required(CONF_DISABLE_AP, default=True): BooleanSelector(),
                        vol.Required(CONF_DISABLE_BLE_RPC, default=True): BooleanSelector(),
                    }
                ),
                {
                    CONF_TIMEZONE: self.config_entry.data.get(CONF_TIMEZONE, ""),
                    CONF_DISABLE_CLOUD: options.get(CONF_DISABLE_CLOUD, True),
                    CONF_DISABLE_AP: options.get(CONF_DISABLE_AP, True),
                    CONF_DISABLE_BLE_RPC: options.get(CONF_DISABLE_BLE_RPC, True),
                },
            ),
            errors=errors,
        )

    async def async_step_inputs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_APPLY_INPUT_PROFILE] = bool(user_input[CONF_APPLY_INPUT_PROFILE])
            options[CONF_INPUT_TYPE] = user_input.get(CONF_INPUT_TYPE) or UNCHANGED
            options[CONF_INPUT_MODE] = user_input.get(CONF_INPUT_MODE) or UNCHANGED
            options[CONF_INPUT_INVERT] = user_input.get(CONF_INPUT_INVERT) or UNCHANGED
            return self.async_create_entry(data=options)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="inputs",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_APPLY_INPUT_PROFILE, default=False): BooleanSelector(),
                        vol.Required(CONF_INPUT_TYPE, default=UNCHANGED): _choice(
                            [
                                (UNCHANGED, "Don't change"),
                                ("switch", "Switch"),
                                ("button", "Button"),
                            ]
                        ),
                        vol.Required(CONF_INPUT_MODE, default=UNCHANGED): _choice(
                            [
                                (UNCHANGED, "Don't change"),
                                ("follow", "Follow"),
                                ("flip", "Toggle / flip"),
                                ("momentary", "Momentary"),
                                ("detached", "Detached"),
                                ("activate", "Activation"),
                                ("dim", "Dim"),
                                ("dual_dim", "Dual dim"),
                            ]
                        ),
                        vol.Required(CONF_INPUT_INVERT, default=UNCHANGED): _choice(
                            [
                                (UNCHANGED, "Don't change"),
                                ("yes", "Invert"),
                                ("no", "Do not invert"),
                            ]
                        ),
                    }
                ),
                {
                    CONF_APPLY_INPUT_PROFILE: options.get(CONF_APPLY_INPUT_PROFILE, False),
                    CONF_INPUT_TYPE: options.get(CONF_INPUT_TYPE, UNCHANGED),
                    CONF_INPUT_MODE: options.get(CONF_INPUT_MODE, UNCHANGED),
                    CONF_INPUT_INVERT: options.get(CONF_INPUT_INVERT, UNCHANGED),
                },
            ),
        )

    async def async_step_outputs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_APPLY_OUTPUT_PROFILE] = bool(user_input[CONF_APPLY_OUTPUT_PROFILE])
            options[CONF_INITIAL_STATE] = user_input.get(CONF_INITIAL_STATE) or UNCHANGED
            options[CONF_AUTO_ON] = bool(user_input.get(CONF_AUTO_ON))
            options[CONF_AUTO_OFF] = bool(user_input.get(CONF_AUTO_OFF))
            _store_optional_number(options, user_input, CONF_AUTO_ON_DELAY)
            _store_optional_number(options, user_input, CONF_AUTO_OFF_DELAY)
            return self.async_create_entry(data=options)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="outputs",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_APPLY_OUTPUT_PROFILE, default=bool(options.get(CONF_APPLY_OUTPUT_PROFILE, False))
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_INITIAL_STATE, default=options.get(CONF_INITIAL_STATE, UNCHANGED)
                    ): _choice(
                        [
                            (UNCHANGED, "Don't change"),
                            ("off", "Off"),
                            ("on", "On"),
                            ("restore_last", "Restore last"),
                            ("match_input", "Match input"),
                            ("toggle", "Toggle"),
                        ]
                    ),
                    vol.Required(CONF_AUTO_ON, default=bool(options.get(CONF_AUTO_ON, False))): BooleanSelector(),
                    vol.Optional(CONF_AUTO_ON_DELAY): _number(0, 86400),
                    vol.Required(CONF_AUTO_OFF, default=bool(options.get(CONF_AUTO_OFF, False))): BooleanSelector(),
                    vol.Optional(CONF_AUTO_OFF_DELAY): _number(0, 86400),
                }
            ),
        )

    async def async_step_dimmers(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            low = user_input.get(CONF_MIN_BRIGHTNESS)
            high = user_input.get(CONF_MAX_BRIGHTNESS)
            if (low in (None, "")) ^ (high in (None, "")):
                errors["base"] = "invalid_brightness"
            elif low not in (None, "") and high not in (None, "") and int(low) >= int(high):
                errors["base"] = "invalid_brightness"
            night = user_input.get(CONF_NIGHT_MODE)
            if night == "on" and not (
                valid_hhmm(str(user_input.get(CONF_NIGHT_START) or ""))
                and valid_hhmm(str(user_input.get(CONF_NIGHT_END) or ""))
            ):
                errors["base"] = "invalid_night"
            if not errors:
                options = dict(self.config_entry.options)
                options[CONF_APPLY_DIMMER_PROFILE] = bool(user_input[CONF_APPLY_DIMMER_PROFILE])
                options[CONF_NIGHT_MODE] = night or UNCHANGED
                options[CONF_BUTTON_DIMMING] = user_input.get(CONF_BUTTON_DIMMING) or UNCHANGED
                options[CONF_NIGHT_START] = str(user_input.get(CONF_NIGHT_START) or "")
                options[CONF_NIGHT_END] = str(user_input.get(CONF_NIGHT_END) or "")
                for key in (
                    CONF_BUTTON_FADE_RATE,
                    CONF_TRANSITION_DURATION,
                    CONF_TRANSITION_UP,
                    CONF_TRANSITION_DOWN,
                    CONF_MIN_BRIGHTNESS,
                    CONF_MAX_BRIGHTNESS,
                    CONF_NIGHT_BRIGHTNESS,
                    CONF_POWER_ON_BRIGHTNESS,
                ):
                    _store_optional_number(options, user_input, key)
                return self.async_create_entry(data=options)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="dimmers",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_APPLY_DIMMER_PROFILE, default=bool(options.get(CONF_APPLY_DIMMER_PROFILE, False))
                    ): BooleanSelector(),
                    vol.Optional(CONF_BUTTON_FADE_RATE): _number(1, 5),
                    vol.Optional(CONF_TRANSITION_DURATION): _number(0, 10800, 0.5),
                    vol.Optional(CONF_TRANSITION_UP): _number(0, 10800, 0.5),
                    vol.Optional(CONF_TRANSITION_DOWN): _number(0, 10800, 0.5),
                    vol.Optional(CONF_MIN_BRIGHTNESS): _number(0, 100),
                    vol.Optional(CONF_MAX_BRIGHTNESS): _number(0, 100),
                    vol.Required(CONF_NIGHT_MODE, default=options.get(CONF_NIGHT_MODE, UNCHANGED)): _choice(
                        [(UNCHANGED, "Don't change"), ("on", "On"), ("off", "Off")]
                    ),
                    vol.Optional(CONF_NIGHT_BRIGHTNESS): _number(1, 100),
                    vol.Optional(CONF_NIGHT_START, default=options.get(CONF_NIGHT_START, "")): TextSelector(),
                    vol.Optional(CONF_NIGHT_END, default=options.get(CONF_NIGHT_END, "")): TextSelector(),
                    vol.Optional(CONF_POWER_ON_BRIGHTNESS): _number(0, 100),
                    vol.Required(
                        CONF_BUTTON_DIMMING, default=options.get(CONF_BUTTON_DIMMING, UNCHANGED)
                    ): _choice(
                        [
                            (UNCHANGED, "Don't change"),
                            ("dim", "Single button dim"),
                            ("dual_dim", "Dual button dim"),
                        ]
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_provisioning(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = self.config_entry.options
        if user_input is not None:
            updated = dict(options)
            updated[CONF_UPDATE_FIRMWARE] = bool(user_input[CONF_UPDATE_FIRMWARE])
            updated[CONF_REQUIRE_ALLOWLIST] = bool(user_input[CONF_REQUIRE_ALLOWLIST])
            mode = user_input[CONF_BLE_SCANNER_MODE]
            updated[CONF_BLE_SCANNER_MODE] = mode if mode in BLE_SCANNER_MODES else "active"
            updated[CONF_CONCURRENCY] = int(user_input[CONF_CONCURRENCY])
            updated[CONF_RETRIES] = int(user_input[CONF_RETRIES])
            updated[CONF_PROVISIONING_MINUTES] = int(user_input[CONF_PROVISIONING_MINUTES])
            return self.async_create_entry(data=updated)
        return self.async_show_form(
            step_id="provisioning",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_FIRMWARE, default=bool(options.get(CONF_UPDATE_FIRMWARE, False))
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_REQUIRE_ALLOWLIST, default=bool(options.get(CONF_REQUIRE_ALLOWLIST, True))
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_BLE_SCANNER_MODE, default=options.get(CONF_BLE_SCANNER_MODE, "active")
                    ): _choice(
                        [
                            ("active", "Active"),
                            ("auto", "Auto"),
                            ("passive", "Passive"),
                            ("disabled", "Disabled"),
                        ]
                    ),
                    vol.Required(CONF_CONCURRENCY, default=int(options.get(CONF_CONCURRENCY, 2))): _number(1, 5),
                    vol.Required(CONF_RETRIES, default=int(options.get(CONF_RETRIES, 1))): _number(0, 3),
                    vol.Required(
                        CONF_PROVISIONING_MINUTES, default=int(options.get(CONF_PROVISIONING_MINUTES, 30))
                    ): _number(5, 180),
                }
            ),
        )

    async def async_step_allowlist(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
            if runtime is None:
                return self.async_abort(reason="not_loaded")
            try:
                count = await runtime.async_import_allowlist(
                    str(user_input["filename"]),
                    replace=bool(user_input.get("replace", True)),
                )
            except ServiceValidationError as err:
                message = str(err)
                errors["base"] = "not_found" if "No CSV" in message else "invalid_csv"
            except ValueError as err:
                errors["base"] = "outside_config" if str(err) == "outside_config" else "invalid_csv"
            else:
                return self.async_abort(
                    reason="allowlist_imported",
                    description_placeholders={"count": str(count)},
                )
        return self.async_show_form(
            step_id="allowlist",
            data_schema=vol.Schema(
                {
                    vol.Required("filename"): TextSelector(),
                    vol.Required("replace", default=True): BooleanSelector(),
                }
            ),
            errors=errors,
        )


def _valid_timezone(value: str) -> bool:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _store_optional_number(options: dict[str, Any], user_input: dict[str, Any], key: str) -> None:
    if key not in user_input or user_input[key] in ("", None):
        options.pop(key, None)
        return
    try:
        whole = as_int(user_input[key])
    except ValueError:
        options[key] = float(user_input[key])
        return
    options[key] = whole

