# Changelog

## 0.2.0

- Secure profile, in the options flow and the `secure_devices` service. It sets or rotates digest auth, and can turn off cloud, the access point, Bluetooth RPC, MQTT, the outbound websocket, and debug/UDP logging. Bluetooth stays enabled for the scanner. Web UI discovery can be turned off. Firmware updates stay manual because Gen2+ has no documented auto-update switch.
- After a password change, the core Shelly config entry is updated and Shelly Bulk opens the device again with the new password.
- `audit_security` and the Security audit sensor report auth, cloud, access point, Bluetooth RPC, and firmware for each device. Passwords are not included.
- Advanced config switches and selects, disabled until enabled, plus the `set_advanced` service. Each change is read back. Models without the component are skipped.

## 0.1.2

- Service calls that take a Shelly device now use a device selector. Home Assistant no longer accepts a device filter on a service target, which was failing hassfest.
- Brand icon and logo ship in the integration so HACS does not require a separate brands-repository entry.
- Manifest categories are plugs and switches, and lighting.

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
