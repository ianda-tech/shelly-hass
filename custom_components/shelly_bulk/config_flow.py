"""Config and options flow for Shelly Bulk.

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

from .device_settings import CHANNEL_KEYS, channel_updates
from .device_type import CONSUMPTION_LABELS, CONSUMPTION_TYPES
from .groups import confirmation_text, fields_for, model_options, room_options, select_cards, ticked_updates
from .pairing import valid_initial_states
from .security import SECURE_OPTION_DEFAULTS
from .const import (
    UNCHANGED,
    BLE_SCANNER_MODES,
    CONF_APPLY_DIMMER_PROFILE,
    CONF_APPLY_INPUT_PROFILE,
    CONF_APPLY_OUTPUT_PROFILE,
    CONF_AUTO_ADOPT,
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
    DEVICE_LIST_RELATIVE,
    DOMAIN,
    OPTIONS_MENU,
    UNCHANGED,
)
from .util import as_int, normalize_mac, slugify, valid_hhmm

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
        vol.Required(CONF_AUTO_ADOPT, default=True): BooleanSelector(),
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
        CONF_AUTO_ADOPT: bool(user_input.get(CONF_AUTO_ADOPT, True)),
        CONF_REQUIRE_ALLOWLIST: bool(user_input[CONF_REQUIRE_ALLOWLIST]),
        CONF_BLE_SCANNER_MODE: mode,
        CONF_CONCURRENCY: int(user_input[CONF_CONCURRENCY]),
        CONF_RETRIES: int(user_input[CONF_RETRIES]),
        CONF_PROVISIONING_MINUTES: int(user_input[CONF_PROVISIONING_MINUTES]),
    }


class ShellyBulkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collect site Wi-Fi, the device password, and generic behaviour."""

    VERSION = 1
    MINOR_VERSION = 3

    def __init__(self) -> None:
        self._user: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            timezone = str(user_input.get(CONF_TIMEZONE) or "").strip()
            if timezone and not _valid_timezone(timezone):
                errors[CONF_TIMEZONE] = "invalid_timezone"
            else:
                user_input[CONF_TIMEZONE] = timezone
                await self.async_set_unique_id(slugify(str(user_input[CONF_SITE_NAME])))
                self._abort_if_unique_id_configured()
                self._user = user_input
                return await self.async_step_behaviour()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_SITE_NAME): TextSelector(),
                        vol.Required(CONF_WIFI_SSID): TextSelector(),
                        vol.Required(CONF_WIFI_PASSWORD): _PASSWORD,
                        vol.Optional(CONF_FLEET_PASSWORD, default=""): _PASSWORD,
                        vol.Optional(CONF_TIMEZONE): TextSelector(),
                    }
                ),
                {CONF_TIMEZONE: self.hass.config.time_zone or ""},
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
    def async_get_options_flow(config_entry: ConfigEntry) -> ShellyBulkOptionsFlow:
        return ShellyBulkOptionsFlow()


class ShellyBulkOptionsFlow(OptionsFlow):
    """Edit Wi-Fi, security, profiles, and import an allowlist."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=list(OPTIONS_MENU),
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
            elif user_input.get("clear_timezone"):
                data[CONF_TIMEZONE] = ""
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
                        vol.Required("clear_timezone", default=False): BooleanSelector(),
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
            updated[CONF_AUTO_ADOPT] = bool(user_input[CONF_AUTO_ADOPT])
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
                        CONF_AUTO_ADOPT, default=bool(options.get(CONF_AUTO_ADOPT, True))
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

    async def async_step_secure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Store the secure-profile checklist. The password field updates entry data."""
        if user_input is not None:
            data = dict(self.config_entry.data)
            if str(user_input.get(CONF_FLEET_PASSWORD) or ""):
                data[CONF_FLEET_PASSWORD] = str(user_input[CONF_FLEET_PASSWORD])
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            options = dict(self.config_entry.options)
            for key in SECURE_OPTION_DEFAULTS:
                options[key] = bool(user_input.get(key, SECURE_OPTION_DEFAULTS[key]))
            return self.async_create_entry(data=options)
        options = self.config_entry.options
        schema: dict[Any, Any] = {
            vol.Optional(CONF_FLEET_PASSWORD, default=""): _PASSWORD,
        }
        for key, default in SECURE_OPTION_DEFAULTS.items():
            schema[vol.Required(key, default=bool(options.get(key, default)))] = BooleanSelector()
        return self.async_show_form(step_id="secure", data_schema=vol.Schema(schema))

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
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("filename", default=DEVICE_LIST_RELATIVE): TextSelector(),
                        vol.Required("replace", default=True): BooleanSelector(),
                    }
                ),
                {"filename": DEVICE_LIST_RELATIVE},
            ),
            errors=errors,
        )

    async def async_step_add_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Append one MAC to the device list without rewriting existing rows."""
        errors: dict[str, str] = {}
        if user_input is not None:
            runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
            if runtime is None:
                return self.async_abort(reason="not_loaded")
            try:
                mac = normalize_mac(str(user_input.get("mac") or ""))
            except ValueError:
                errors["mac"] = "invalid_mac"
            else:
                added = await runtime.add_listed_device(
                    mac, str(user_input.get("name") or ""), str(user_input.get("room") or "")
                )
                if not added:
                    errors["mac"] = "already_listed"
                else:
                    return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema(
                {
                    vol.Required("mac"): TextSelector(),
                    vol.Optional("name", default=""): TextSelector(),
                    vol.Optional("room", default=""): TextSelector(),
                }
            ),
            errors=errors,
        )

    def _fleet(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_edit_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose an adopted Shelly, then load its live settings."""
        runtime = self._fleet()
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        choices = runtime.adopted_device_choices()
        if not choices:
            return self.async_abort(reason="no_devices")
        errors: dict[str, str] = {}
        if user_input is not None:
            self._edit_id = str(user_input["device"])
            try:
                live = await runtime.read_device_form(self._edit_id)
            except Exception:  # noqa: BLE001
                errors["base"] = "not_reachable"
            else:
                picked = next(item for item in choices if item["id"] == self._edit_id)
                self._edit_supported = live.supported
                self._edit_values = dict(live.values)
                self._edit_values["room"] = picked["room"]
                return await self.async_step_edit_fields()
        return self.async_show_form(
            step_id="edit_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): SelectSelector(
                        SelectSelectorConfig(
                            options=[{"value": item["id"], "label": item["label"]} for item in choices],
                            mode=SelectSelectorMode.DROPDOWN,
                            sort=True,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_edit_fields(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the fields this model supports, pre-filled from the device."""
        runtime = self._fleet()
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        errors: dict[str, str] = {}
        details = "none"
        allowed = set(self._edit_supported) | {"room"}
        if user_input is not None:
            values = {key: user_input[key] for key in user_input if key in allowed}
            try:
                field_errors = await runtime.save_device_form(self._edit_id, values)
            except Exception:  # noqa: BLE001
                errors["base"] = "not_reachable"
            else:
                self._edit_values.update(values)
                if field_errors:
                    errors = field_errors
                    details = ", ".join(sorted(field_errors))
                else:
                    self._saved_channel = channel_updates(values)
                    self._bulk_purpose = "copy"
                    self._bulk_updates = dict(self._saved_channel)
                    return await self.async_step_copy_settings()
        return self.async_show_form(
            step_id="edit_fields",
            data_schema=self.add_suggested_values_to_schema(
                _edit_schema(self._edit_supported, self._edit_values),
                self._edit_values,
            ),
            errors=errors,
            description_placeholders={"details": details},
        )

    async def async_step_copy_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose a group to receive the settings just saved. Runs in the background."""
        self._bulk_purpose = "copy"
        self._bulk_updates = dict(getattr(self, "_saved_channel", {}) or {})
        return await self._group_step("copy_settings", user_input, include_none=True)

    async def async_step_device_type(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose devices, then a consumption type and an optional profile."""
        self._bulk_purpose = "device_type"
        return await self._group_step("device_type", user_input, include_none=False)

    async def async_step_device_type_form(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        runtime = self._fleet()
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        if not hasattr(self, "_device_type_profiles"):
            summary = await runtime.describe_device_types([card.entry_id for card in self._bulk_chosen])
            self._device_type_profiles = list(summary.get("profiles") or [])
        profiles = self._device_type_profiles
        errors: dict[str, str] = {}
        if user_input is not None:
            consumption = str(user_input.get("consumption_type") or UNCHANGED)
            profile = str(user_input.get("profile") or UNCHANGED)
            confirm = bool(user_input.get("confirm_profile_reboot"))
            if profile != UNCHANGED and not confirm:
                errors["confirm_profile_reboot"] = "confirm_profile"
            elif consumption == UNCHANGED and profile == UNCHANGED:
                return self.async_abort(reason="nothing_selected")
            else:
                runtime.start_device_type(
                    [card.entry_id for card in self._bulk_chosen],
                    consumption=None if consumption == UNCHANGED else consumption,
                    profile=None if profile == UNCHANGED else profile,
                    confirm_reboot=confirm,
                )
                return self.async_abort(
                    reason="device_type_started",
                    description_placeholders={"count": str(len(self._bulk_chosen))},
                )
        consumption_options = [(UNCHANGED, "Leave unchanged")]
        consumption_options.extend((name, CONSUMPTION_LABELS.get(name, name)) for name in CONSUMPTION_TYPES)
        profile_options = [(UNCHANGED, "Leave unchanged")]
        profile_options.extend((name, name) for name in profiles)
        return self.async_show_form(
            step_id="device_type_form",
            data_schema=vol.Schema(
                {
                    vol.Required("consumption_type", default=UNCHANGED): _choice(consumption_options),
                    vol.Required("profile", default=UNCHANGED): _choice(profile_options),
                    vol.Required("confirm_profile_reboot", default=False): BooleanSelector(),
                }
            ),
            errors=errors,
            description_placeholders={"count": str(len(self._bulk_chosen))},
        )

    async def async_step_bulk_change(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Start a bulk change. The device work happens after the form closes."""
        self._bulk_purpose = "bulk"
        return await self._group_step("bulk_change", user_input, include_none=False)

    async def _group_step(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        *,
        include_none: bool,
    ) -> ConfigFlowResult:
        runtime = self._fleet()
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        self._bulk_cards = runtime.device_cards()
        if not self._bulk_cards and not include_none:
            return self.async_abort(reason="no_devices")
        options = [("all", "All Shellies"), ("model", "By model"), ("room", "By room"), ("unnamed", "Only unnamed devices"), ("individual", "Pick individually")]
        if include_none:
            options.insert(0, ("none", "Don't copy"))
        if user_input is not None:
            kind = str(user_input["group"])
            if kind == "none":
                return self.async_abort(reason="device_saved")
            self._bulk_kind = kind
            if kind in {"all", "unnamed"}:
                return await self._open_bulk_confirm()
            return await self.async_step_bulk_filter()
        default = "none" if include_none else "all"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required("group", default=default): _choice(options)}),
        )

    async def async_step_bulk_filter(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        runtime = self._fleet()
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        kind = self._bulk_kind
        cards = self._bulk_cards
        errors: dict[str, str] = {}
        if user_input is not None:
            if kind == "model":
                self._bulk_model = str(user_input.get("model") or "")
            elif kind == "room":
                self._bulk_room = str(user_input.get("room") or "")
            else:
                self._bulk_ids = {str(item) for item in (user_input.get("devices") or [])}
            return await self._open_bulk_confirm()
        if kind == "model":
            options = model_options(cards)
            if not options:
                return self.async_abort(reason="no_devices")
            schema = vol.Schema({vol.Required("model"): _choice([(item["value"], item["label"]) for item in options])})
        elif kind == "room":
            options = room_options(cards)
            schema = vol.Schema({vol.Required("room"): _choice([(item["value"], item["label"]) for item in options])})
        else:
            schema = vol.Schema(
                {
                    vol.Required("devices"): SelectSelector(
                        SelectSelectorConfig(
                            options=[{"value": card.entry_id, "label": card.label} for card in cards],
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                            sort=True,
                        )
                    )
                }
            )
        return self.async_show_form(step_id="bulk_filter", data_schema=schema, errors=errors)

    async def _open_bulk_confirm(self) -> ConfigFlowResult:
        chosen = select_cards(
            self._bulk_cards,
            self._bulk_kind,
            model=getattr(self, "_bulk_model", ""),
            room=getattr(self, "_bulk_room", ""),
            entry_ids=getattr(self, "_bulk_ids", set()),
            exclude_id=getattr(self, "_edit_id", "") if self._bulk_purpose == "copy" else "",
        )
        self._bulk_chosen = chosen
        if not chosen:
            return self.async_abort(reason="no_devices")
        if self._bulk_purpose == "device_type":
            return await self.async_step_device_type_form()
        return await self.async_step_bulk_confirm()

    async def async_step_bulk_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        summary = confirmation_text(self._bulk_chosen)
        if user_input is not None:
            if self._bulk_purpose == "copy":
                return self._start_bulk(self._bulk_updates)
            self._bulk_fields = fields_for(self._bulk_chosen)
            return await self.async_step_bulk_fields()
        return self.async_show_form(
            step_id="bulk_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"summary": summary},
        )

    async def async_step_bulk_fields(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        fields = self._bulk_fields
        if user_input is not None:
            updates = ticked_updates(user_input, fields)
            if not updates:
                return self.async_abort(reason="nothing_selected")
            return self._start_bulk(updates)
        schema: dict[Any, Any] = {}
        for key in fields:
            schema[vol.Required(f"change_{key}", default=False)] = BooleanSelector()
            dimmers_only = bool(self._bulk_chosen) and all(card.dimmer for card in self._bulk_chosen)
            schema.update(_bulk_value_field(key, dimmers_only=dimmers_only))
        return self.async_show_form(step_id="bulk_fields", data_schema=vol.Schema(schema))

    def _start_bulk(self, updates: dict[str, Any]) -> ConfigFlowResult:
        runtime = self._fleet()
        count = 0
        if runtime is not None:
            count = runtime.start_bulk_apply([card.entry_id for card in self._bulk_chosen], updates)
        return self.async_abort(reason="bulk_started", description_placeholders={"count": str(count)})


_EDIT_NUMBERS = {
    "auto_on_delay": (0, 86400, 0.5),
    "auto_off_delay": (0, 86400, 0.5),
    "fade_rate": (1, 5, 1),
    "transition_duration": (0, 10800, 0.5),
    "transition_up": (0, 10800, 0.5),
    "transition_down": (0, 10800, 0.5),
    "min_brightness": (0, 100, 1),
    "max_brightness": (0, 100, 1),
    "night_brightness": (1, 100, 1),
}
_EDIT_CHOICES = {
    "input_type": [("switch", "Switch"), ("button", "Button")],
    "input_mode": [
        ("follow", "Follow"),
        ("flip", "Toggle / flip"),
        ("momentary", "Momentary"),
        ("detached", "Detached"),
        ("activate", "Activation"),
        ("dim", "Dim"),
        ("dual_dim", "Dual dim"),
    ],
    "initial_state": [
        ("off", "Off"),
        ("on", "On"),
        ("restore_last", "Restore last"),
        ("match_input", "Match input"),
        ("toggle", "Toggle"),
    ],
}


def _edit_schema(supported: tuple[str, ...] | list[str], values: dict[str, Any]) -> vol.Schema:
    """Build a form that contains only the fields this device returned."""
    shown = [key for key in ("name", "room", *CHANNEL_KEYS) if key == "room" or key in supported]
    schema: dict[Any, Any] = {}
    for key in shown:
        current = values.get(key)
        if key in {"invert", "auto_on", "auto_off", "night_mode"}:
            schema[vol.Required(key, default=bool(current))] = BooleanSelector()
        elif key in _EDIT_NUMBERS:
            low, high, step = _EDIT_NUMBERS[key]
            default = current if current not in (None, "") else low
            schema[vol.Required(key, default=default)] = _number(low, high, step)
        elif key in _EDIT_CHOICES:
            options = list(_EDIT_CHOICES[key])
            if key == "initial_state":
                mode = str(values.get("input_mode") or "")
                kind = "light" if mode in {"dim", "dual_dim"} or current == "toggle" else "switch"
                allowed = set(valid_initial_states(kind, mode))
                options = [item for item in options if item[0] in allowed]
                if not options:
                    options = [("restore_last", "Restore last")]
            known = {item[0] for item in options}
            if current and str(current) not in known and key != "initial_state":
                options.append((str(current), str(current)))
            schema[vol.Required(key, default=str(current if current in known else options[0][0]))] = _choice(options)
        else:
            schema[vol.Optional(key, default=str(current or ""))] = TextSelector()
    return vol.Schema(schema)


def _bulk_value_field(key: str, *, dimmers_only: bool = False) -> dict[Any, Any]:
    """The value control next to a 'change this' toggle. It is ignored unless the toggle is on."""
    if key in {"invert", "auto_on", "auto_off", "night_mode"}:
        return {vol.Required(key, default=False): BooleanSelector()}
    if key in _EDIT_NUMBERS:
        low, high, step = _EDIT_NUMBERS[key]
        return {vol.Optional(key, default=low): _number(low, high, step)}
    if key == "initial_state":
        options = [("off", "Off"), ("on", "On"), ("restore_last", "Restore last")]
        options.append(("toggle", "Toggle") if dimmers_only else ("match_input", "Match input"))
        return {vol.Required(key, default="restore_last"): _choice(options)}
    if key in _EDIT_CHOICES:
        return {vol.Required(key, default=_EDIT_CHOICES[key][0][0]): _choice(list(_EDIT_CHOICES[key]))}
    return {vol.Optional(key, default=""): TextSelector()}


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

