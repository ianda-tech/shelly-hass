# Changelog

## 0.2.4

- Power-on state and input behaviour are sent together in one `Switch.SetConfig`. `follow` sets `match_input`. Leaving `follow` while power-on is `match_input` sets `restore_last`. A switch is not offered `toggle` or display labels. The selects refresh after a rejected change so the UI shows the value the device kept.

## 0.2.3

- Configure → Edit a device reads the live settings from an adopted Shelly and writes back only the fields that model reports. The Home Assistant name and area, and the devices.csv row, are updated. Each field that the device does not keep is shown as an error.
- After that form, the same channel settings can be copied to other devices. The list is labelled with the model. Names and rooms are not copied.
- Each adopted Shelly has an input mode select, a power-on state select, and an auto-off delay number, enabled by default. Dimmers also have fade rate and transition numbers. The value shown is the one read back from the device. The existing advanced switches stay disabled until enabled.

## 0.2.2

- `config/shelly_bulk/devices.csv` is created on setup and on load when it is missing. The new file is a header plus comments, with no real devices. An existing file is never overwritten. A header-only import is an empty list. Import defaults to that path. Reload device list, and a change to the file's modification time, merge the CSV without wiping names you already stored. Configure → Add device appends one MAC.
- Find my Shelly scans Bluetooth advertisements from every Home Assistant scanner and proxy, appends new MACs (blank name and room, model hint set), and posts a notification with MAC, model, signal, and which scanner heard the device.
- Auto-adopt nearby new Shellies defaults to on in setup and on the hub switch. Factory-new devices with no login and an open setup window are adopted even when they are not on the list, then written to the CSV with a placeholder name. Only provision the allowlist overrides auto-adopt while it is on. A neighbour's factory-new Shelly in range can be adopted when that override is off.
- Identify toggles the first output for about 2 seconds. It is disabled by default on relays, plugs, and unknown models.
- A push to main publishes a GitHub release named `v` plus the manifest version, using this changelog section, when that tag does not already exist. HACS lists versions from those releases.

## 0.2.1

- Timezone is optional. The config flow pre-fills Home Assistant's own zone (`Settings > System > General`) as a suggestion, read at runtime rather than shipped. Clear the field and no `location.tz` is sent. A filled value must be an IANA `Region/City` name, for example Australia/Melbourne. In options, leave the box blank to keep the stored zone, or tick Clear timezone to remove it.
- Device login password is labelled as the `admin` password for the local web page and API. A blank value leaves devices open. Saving a new password in Configure only stores it. Secure devices and Apply profile set it only on devices that have no login. A device that already has a password is not changed, and Home Assistant keeps the password already stored for that Shelly.

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
