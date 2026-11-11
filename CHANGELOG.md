# Changelog

## 0.3.2

- Setup no longer waits for each Shelly to answer. Switch, number, select, and sensor controls start unavailable and share one read per device. That read runs in the background, at most a few devices at a time, and an offline device cannot hold the others or startup. Settings refresh about once a minute.

## 0.3.1

- When Bluetooth setup has closed, **Scan for hotspots** lists Shelly setup access points the Supervisor can see, with signal. **Provision via hotspot** joins one access point on wlan0, sends the site Wi-Fi to `192.168.33.1`, and always puts wlan0 back. A batch runs one device at a time. Dry run reports the plan and does not join. This needs Home Assistant OS or Supervised and a Wi-Fi adapter. end0 must stay the connected primary interface with the default route. end0 is never changed.

## 0.3.0

- Upgrade removes the extra devices left behind when companion devices were introduced. Before 0.2.6 those devices used `("shelly", <Shelly unique id or entry id>)` and had no name of their own, so Home Assistant showed the site name. The device that remains is `("shelly_bulk", "companion_<Shelly entry id>")`. Entities keep their entity id, a name you set, and a disabled state you set. A core Shelly device is not removed. A leftover device can also be deleted from the device page.
- The integration is shown as Shelly Installer. The domain stays `shelly_bulk`, and existing entity ids are unchanged.
- Each switch channel has a consumption type select (switch, light, fan, socket, and the other values Shelly stores). It is written only when the value differs, and it does not reboot the device. Home Assistant shows the channel as a light when the type is light.
- The site default output type is light. Adoption and profile apply set every switch channel to that default unless you have chosen a different type for that channel. Configure → Device type can set already-added Shellies, including ones that were in Home Assistant first, to the site default in one step. The core Shelly entry is reloaded afterwards so the light entities appear. The device is not rebooted.
- Add device asks for an output type on each channel, pre-filled with the site default, and a profile. The profile is applied before the name when the device lists it, and the device restarts once. Auto-adopt and Find my Shelly use one batch output type. The choice is stored on the device, including optional `output_type`, `output_type_2`, and `profile` columns in `devices.csv`, and is treated as a user override afterwards.
- Configure → Device type can set that consumption type for a group, and can change the device profile (switch or cover, or whatever Shelly.ListProfiles returns) only after you tick the reboot box. Profiles run one device at a time. The device reboots itself. The core Shelly entry is reloaded afterwards. No other action reboots a device.

## 0.2.9

- Per-device controls add again on Home Assistant 2026.11. The companion device is registered with `via_device_id` before its entities are added, and the MAC is stored with the current device-registry calls. The old `via_device` argument made Home Assistant refuse the entity.
- **Retry failed** clears the failed list and tries those devices again the next time they advertise. The same action is `shelly_bulk.retry_failed`. A failed result mentions a power-cycle only when that device is advertising without Bluetooth RPC.

## 0.2.8

- Shelly Bulk no longer reboots a device. `BLE.SetConfig`, `WiFi.SetConfig`, `Cloud.SetConfig`, `MQTT.SetConfig`, and `Sys.SetConfig` are sent only when the device value is different, including during adoption and the secure profile. Enabling the Home Assistant controls does not push those settings on startup or on a refresh.
- A config-entry write that does not change data or options does not reload the entry, and a reload cannot start another reload. Network refreshes no longer fan out into another read of every select.

## 0.2.7

- Startup no longer stops when the core Shelly device already has the MAC connection. The Shelly Bulk device for that Shelly does not register the MAC connection. It keeps the MAC in its name and in the MAC sensor, and it links to the core Shelly device. A device-registry error is logged and does not stop setup.
- Turning on controls that an older version had disabled runs once, during migration, before setup. Later restarts do not do it again, so enabling them does not keep reloading the integration. A control you disabled stays off.

## 0.2.6

- Every Shelly Bulk control on a Shelly device is enabled: the advanced switches and selects, Identify, input behaviour, power-on state, auto-off delay, and the MAC and IP sensors. Identify still does nothing until it is pressed. On upgrade, controls this integration had disabled are turned back on. Controls you disabled stay off.
- The Shelly Bulk device for each Shelly is named after that Shelly and its address, for example the Home Assistant name plus the MAC and IP, or the model plus the last four characters of the MAC and the IP. The hub title is not used. The name updates when the IP changes, unless you renamed that device yourself. New entity ids use that name. Existing entity ids are left as they are.

## 0.2.5

- Configure → Bulk change settings picks devices by group: all, one model, one room (including no room), unnamed devices, or a short individual list. A confirmation says how many devices will change and lists each MAC and IP. Only ticked settings are sent, in the background, five at a time, with a timeout and a read-back. Progress is a notification and a report row per device.
- Copy settings to other devices uses the same group selector and also runs in the background.
- Labels use the Home Assistant name, or the model plus the last four characters of the MAC, plus the room and IP. The default Shelly hostname is not shown.
- Each core Shelly has MAC address and IP address sensors. The MAC is stored on the device, and Visit opens `http://<ip>`. The IP is read from the device when it answers and falls back to the host stored by core Shelly. `shelly_bulk.bulk_set` is the service form of the same change.

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
