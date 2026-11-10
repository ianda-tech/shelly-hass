# Changelog

## 0.1.1

- Renamed the integration from Shelly Fleet to Shelly Bulk. The domain is `shelly_bulk`. The repository name is still shelly-hass. Nothing had been released, so there is no config migration.

## 0.1.0

First release of Shelly Bulk, a HACS custom integration that adopts factory-new Shelly Gen2, Gen3, and Gen4 devices through Home Assistant's own Bluetooth provisioning flow.

- Config flow and options flow for Wi-Fi, a shared device password, timezone, and channel profiles. No site values are shipped.
- Provisioning mode switch and services, with a timeout, concurrency limit, and retries.
- Optional CSV allowlist imported from the Home Assistant config directory.
- After each adoption, the core Shelly Bluetooth scanner mode is set so later devices can be heard further away.
- Profile over Gen2+ RPC: cloud, access point, Bluetooth RPC, device name, timezone, input type and mode (including detached), output power-on state and timers, dimmer fade rate and transition.
- Stable firmware update when enabled.
- Diagnostic sensors, a redacted diagnostics payload, and a CSV/JSON report under the config directory.
- Optional workshop script in `tools/shelly_ble_provision.py`. It has not been run on hardware.
