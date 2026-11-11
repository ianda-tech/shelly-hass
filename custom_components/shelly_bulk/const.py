"""Constants for the Shelly Bulk integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "shelly_bulk"
SHELLY_DOMAIN: Final = "shelly"
MANUFACTURER: Final = "Innovate and Automate"
VERSION: Final = "0.2.7"

# Home Assistant's Shelly flow uses these step ids (core dev, November 2026).
STEP_BLUETOOTH_CONFIRM: Final = "bluetooth_confirm"
STEP_WIFI_SCAN: Final = "wifi_scan"
STEP_WIFI_SCAN_FAILED: Final = "wifi_scan_failed"
STEP_DO_PROVISION: Final = "do_provision"
STEP_PROVISION_DONE: Final = "provision_done"
STEP_PROVISION_FAILED: Final = "provision_failed"
STEP_CREDENTIALS: Final = "credentials"
SOURCE_BLUETOOTH: Final = "bluetooth"

# Core disables the AP and BLE RPC itself after a successful BLE provision.
# ble_scanner_mode is the core Shelly options key that arms the advertisement proxy.
CONF_BLE_SCANNER_MODE: Final = "ble_scanner_mode"
BLE_SCANNER_ACTIVE: Final = "active"
BLE_SCANNER_MODES: Final = ("active", "auto", "passive", "disabled")

CONF_SITE_NAME: Final = "site_name"
CONF_WIFI_SSID: Final = "wifi_ssid"
CONF_WIFI_PASSWORD: Final = "wifi_password"
CONF_FLEET_PASSWORD: Final = "fleet_password"
CONF_TIMEZONE: Final = "timezone"

CONF_DISABLE_CLOUD: Final = "disable_cloud"
CONF_DISABLE_AP: Final = "disable_ap"
CONF_DISABLE_BLE_RPC: Final = "disable_ble_rpc"
CONF_UPDATE_FIRMWARE: Final = "update_firmware"
CONF_REQUIRE_ALLOWLIST: Final = "require_allowlist"
CONF_AUTO_ADOPT: Final = "auto_adopt"
CONF_CONCURRENCY: Final = "concurrency"
CONF_RETRIES: Final = "retries"
CONF_PROVISIONING_MINUTES: Final = "provisioning_minutes"

CONF_APPLY_INPUT_PROFILE: Final = "apply_input_profile"
CONF_INPUT_TYPE: Final = "input_type"
CONF_INPUT_MODE: Final = "input_mode"
CONF_INPUT_INVERT: Final = "input_invert"

CONF_APPLY_OUTPUT_PROFILE: Final = "apply_output_profile"
CONF_INITIAL_STATE: Final = "initial_state"
CONF_AUTO_ON: Final = "auto_on"
CONF_AUTO_ON_DELAY: Final = "auto_on_delay"
CONF_AUTO_OFF: Final = "auto_off"
CONF_AUTO_OFF_DELAY: Final = "auto_off_delay"

CONF_APPLY_DIMMER_PROFILE: Final = "apply_dimmer_profile"
CONF_BUTTON_FADE_RATE: Final = "button_fade_rate"
CONF_TRANSITION_DURATION: Final = "transition_duration"
CONF_TRANSITION_UP: Final = "transition_up"
CONF_TRANSITION_DOWN: Final = "transition_down"
CONF_MIN_BRIGHTNESS: Final = "min_brightness"
CONF_MAX_BRIGHTNESS: Final = "max_brightness"
CONF_NIGHT_MODE: Final = "night_mode"
CONF_NIGHT_BRIGHTNESS: Final = "night_brightness"
CONF_NIGHT_START: Final = "night_start"
CONF_NIGHT_END: Final = "night_end"
CONF_POWER_ON_BRIGHTNESS: Final = "power_on_brightness"
CONF_BUTTON_DIMMING: Final = "button_dimming"

UNCHANGED: Final = "unchanged"

ALLTERCO_MFID: Final = 0x0BA9
FLAG_AUTH_ENABLED: Final = 1 << 1
FLAG_RPC_OVER_BLE: Final = 1 << 2

DEVICE_LIST_RELATIVE: Final = "shelly_bulk/devices.csv"
OPTIONS_MENU: Final = (
    "wifi",
    "security",
    "secure",
    "inputs",
    "outputs",
    "dimmers",
    "provisioning",
    "allowlist",
    "add_device",
    "edit_device",
    "bulk_change",
)

POLL_INTERVAL_SECONDS: Final = 3.0
PROVISION_WAIT_SECONDS: Final = 90.0
ENTRY_WAIT_SECONDS: Final = 45.0
CONNECT_ATTEMPTS: Final = 5

STORAGE_VERSION: Final = 1
MAX_STORED_RESULTS: Final = 200

SWITCH_INITIAL_STATES: Final = frozenset({"off", "on", "restore_last", "match_input"})
LIGHT_INITIAL_STATES: Final = frozenset({"off", "on", "restore_last", "toggle"})
SWITCH_IN_MODES: Final = frozenset(
    {"follow", "flip", "momentary", "detached", "activate", "cycle"}
)
LIGHT_IN_MODES: Final = frozenset(
    {"follow", "flip", "activate", "detached", "dim", "dual_dim"}
)
DIMMER_COMPONENTS: Final = frozenset({"light", "rgb", "rgbw", "cct"})
OUTPUT_COMPONENTS: Final = frozenset({"switch", "light", "rgb", "rgbw", "cct"})
COMPONENT_NAMESPACES: Final = {
    "input": "Input",
    "switch": "Switch",
    "light": "Light",
    "rgb": "RGB",
    "rgbw": "RGBW",
    "cct": "CCT",
}

# Verified config keys that mean "brightness applied on power-on" if already
# present on the device. None of these is sent unless GetConfig already has it.
POWER_ON_BRIGHTNESS_KEYS: Final = (
    "power_on_brightness",
    "initial_brightness",
    "brightness",
)
RAMP_UP_KEYS: Final = ("transition_duration_up", "ramp_up")
RAMP_DOWN_KEYS: Final = ("transition_duration_down", "ramp_down")

SERVICE_APPLY_PROFILE: Final = "apply_profile"
SERVICE_SET_INPUT_MODE: Final = "set_input_mode"
SERVICE_SET_DIMMER_FADE: Final = "set_dimmer_fade"
SERVICE_START_PROVISIONING: Final = "start_provisioning"
SERVICE_STOP_PROVISIONING: Final = "stop_provisioning"
SERVICE_EXPORT_REPORT: Final = "export_report"
SERVICE_IMPORT_ALLOWLIST: Final = "import_allowlist"
SERVICE_SECURE_DEVICES: Final = "secure_devices"
SERVICE_AUDIT_SECURITY: Final = "audit_security"
SERVICE_SET_ADVANCED: Final = "set_advanced"
SERVICE_BULK_SET: Final = "bulk_set"

SERVICES: Final = (
    SERVICE_APPLY_PROFILE,
    SERVICE_SET_INPUT_MODE,
    SERVICE_SET_DIMMER_FADE,
    SERVICE_START_PROVISIONING,
    SERVICE_STOP_PROVISIONING,
    SERVICE_EXPORT_REPORT,
    SERVICE_IMPORT_ALLOWLIST,
    SERVICE_SECURE_DEVICES,
    SERVICE_AUDIT_SECURITY,
    SERVICE_SET_ADVANCED,
    SERVICE_BULK_SET,
)
