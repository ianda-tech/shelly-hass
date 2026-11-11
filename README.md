<p align="center">
  <img src="custom_components/shelly_bulk/brand/logo.png" alt="Shelly Bulk" width="256">
</p>

# Shelly Bulk

[![Latest release](https://img.shields.io/github/v/release/ianda-tech/shelly-hass?display_name=tag&sort=semver&label=Latest%20release&style=for-the-badge&color=2ea44f)](https://github.com/ianda-tech/shelly-hass/releases/latest)
[![Latest release](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fianda-tech%2Fshelly-hass%2Fmain%2Fcustom_components%2Fshelly_bulk%2Fmanifest.json&query=%24.version&prefix=v&label=Latest%20release&style=for-the-badge&color=2ea44f)](https://github.com/ianda-tech/shelly-hass/releases/latest)
[![released](https://img.shields.io/github/release-date/ianda-tech/shelly-hass?label=released&style=for-the-badge)](https://github.com/ianda-tech/shelly-hass/releases/latest)

**Current version: 0.2.6.** Bump this line in the same change as `version` in `custom_components/shelly_bulk/manifest.json`.

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/github/license/ianda-tech/shelly-hass)](LICENSE)
[![hassfest | validate | tests](https://img.shields.io/github/actions/workflow/status/ianda-tech/shelly-hass/ci.yml?branch=main&label=hassfest%20%7C%20validate%20%7C%20tests)](https://github.com/ianda-tech/shelly-hass/actions/workflows/ci.yml)
[![Home Assistant 2025.12+](https://img.shields.io/badge/home%20assistant-2025.12%2B-blue.svg)](https://github.com/ianda-tech/shelly-hass/blob/main/hacs.json)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ianda-tech&repository=shelly-hass&category=integration)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=shelly_bulk)

Shelly Bulk (`shelly_bulk`) is a [HACS](https://hacs.xyz/) custom integration for installers who commission a lot of factory-new Shelly devices into [Home Assistant](https://www.home-assistant.io/). It sits **beside** the built-in Shelly integration. It does not replace it, and it does not speak a private provisioning protocol when Home Assistant already can.

You enter every site value yourself, after install, on the Home Assistant instance that will own the devices: Wi-Fi name and password, the device login password, timezone, and the list of MAC addresses, names, and rooms. None of that is shipped in this repository.

## Install or update to the latest

The **Latest release** badges above go to the [latest GitHub release](https://github.com/ianda-tech/shelly-hass/releases/latest). The release badge reads the published tag. Until that tag exists, the second badge reads `version` from [`manifest.json` on main](https://github.com/ianda-tech/shelly-hass/blob/main/custom_components/shelly_bulk/manifest.json), so a version is still shown. The date badge is the release date.

### HACS

1. Use **Open HACS repository** above. It adds `ianda-tech/shelly-hass` as a custom integration repository.
2. Open **Shelly Bulk** in HACS. Use the three-dot menu, choose **Redownload**, and pick the newest version.
3. Restart Home Assistant.

Updates also appear under **Settings → Updates**.

### Manual

1. Download the **Source code** zip from the [latest release](https://github.com/ianda-tech/shelly-hass/releases/latest).
2. Copy `custom_components/shelly_bulk` into `/config/custom_components`, replacing the folder that is already there.
3. Restart Home Assistant.

The folder must contain `manifest.json`. Do not rename the domain.

### Which version is installed

**Settings → Devices & services → Shelly Bulk** shows the version on the integration card.

## What it does, and why

A new building full of Shelly Plus, Pro, Gen3, and Gen4 devices is awkward to add one Discovered card at a time. Each device will join Wi-Fi over Bluetooth, but only for a short window after it is powered, and only from a Bluetooth adapter that can actually connect.

Shelly Bulk watches the Bluetooth discovery flows that Home Assistant's own Shelly integration already creates (Home Assistant 2025.12 or newer). While provisioning mode is on, it answers those flows with the Wi-Fi credentials stored on its config entry, waits until the core integration has added the device, then turns that Shelly's Bluetooth scanner on. The next box, further down the bench or the corridor, can be heard by a device that was itself only just adopted. Coverage spreads with the install instead of depending on one dongle at the door.

```mermaid
flowchart LR
  batch[Power a batch of new Shellies]
  hear[Advertisements reach a connectable adapter]
  flow[Core Shelly opens a Bluetooth flow]
  submit[Shelly Bulk submits Wi-Fi]
  added[Core Shelly adds the device]
  scan[Shelly Bulk sets the Shelly scanner to active]
  next[Later devices are heard further away]
  batch --> hear --> flow --> submit --> added --> scan --> next
  next --> hear
```

The arrow back to "heard" is advertisement range, not a promise that a Shelly can finish setup for the next device on its own. Shelly's Bluetooth proxy forwards advertisements. It cannot open a GATT connection. The Wi-Fi step still needs a connectable radio in range of the device being adopted: the Home Assistant host adapter, or an ESPHome Bluetooth proxy in active mode. Shellies you have already adopted make those advertisements travel further, so a connectable proxy at the bench can see devices that would otherwise be out of earshot. If the only radio that hears a device is a Shelly scanner, core Shelly aborts that flow with "cannot connect" and Shelly Bulk records it.

## Supported devices

| In scope | Out of scope |
| --- | --- |
| Shelly Gen2 (Plus and Pro), Gen3, and Gen4 in Wi-Fi mode, with Bluetooth RPC still open | Gen1. There is no Bluetooth setup. Add those in core Shelly over the access point or by IP. |
| Dimmers that use the Light, RGB, RGBW, or CCT components, including Dimmer Gen3, Pro Dimmer, Plus Wall Dimmer, and RGBW where the RPC matches | Shelly BLU sensors (BTHome), Wave (Z-Wave), and Gen4 running in Zigbee mode |
| Pro models with Ethernet, after they are on the LAN: Shelly Bulk can still apply a profile over IP | Battery devices are in scope but the setup window is about 3 minutes, and you may have to wake them |

Profiles are sent with Gen2+ RPC (`Sys.SetConfig`, `WiFi.SetConfig`, `Cloud.SetConfig`, `BLE.SetConfig`, `Input.SetConfig`, `Switch.SetConfig`, `Light.SetConfig`, and the same shape for `RGB`, `RGBW`, and `CCT`, plus `Shelly.SetAuth`, `Shelly.CheckForUpdate`, and `Shelly.Update`). If a model rejects a field, that field is skipped and the rest of the profile still applies. The report says what was skipped.

## Requirements

- Home Assistant **2025.12 or newer**. Bluetooth Wi-Fi provisioning for Shelly landed in 2025.12. This integration was checked against the core Shelly flow on the November 2026 `dev` branch: the Bluetooth confirm step takes an empty form, Wi-Fi SSID and password are one step, and core then turns the access point and Bluetooth RPC off itself.
- The core **Shelly** integration and the **Bluetooth** integration. Shelly Bulk does not vendor its own copy of `aioshelly`; it uses the copy Home Assistant already installed for Shelly.
- A connectable Bluetooth adapter on the Home Assistant host, or one or more [ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy/) set to **active**, with a few free connection slots. Two proxies with about four slots each is a comfortable bench. More than about five connections on one radio gets unreliable, so Shelly Bulk's concurrency defaults to 2 and will not go above 5.
- An IoT SSID that is **2.4 GHz** and not WPA3-only. 5 GHz-only, band steering, captive portals, and client isolation break the join.
- DHCP space for the whole batch.
- mDNS (or a reflector) between the IoT VLAN and Home Assistant. After Wi-Fi provisioning, core Shelly waits for the device to announce itself. Without mDNS the flow falls back to an active lookup and often times out.
- Admin access to Home Assistant. Shelly Bulk writes the core Shelly config entry (scanner mode, and username `admin` plus the device login password after `Shelly.SetAuth`).

## Quick install

1. Install or update with the steps in [Install or update to the latest](#install-or-update-to-the-latest).
2. Restart Home Assistant if you have not already.
3. Use **Add integration** above. The domain is `shelly_bulk`. Enter the site values on that instance. Nothing in this repository is pre-filled.

A push to `main` publishes a release named `v` plus the version in `manifest.json`, when that tag does not already exist. The release notes are that version's section of `CHANGELOG.md`. HACS installs the files from the git tag.

The same buttons work only when you are on your own Home Assistant and My Home Assistant can reach it.

## Install manually

1. Copy the `custom_components/shelly_bulk` folder from this repository into your Home Assistant config directory, so the path is `config/custom_components/shelly_bulk`.
2. Restart Home Assistant.
3. Add the **Shelly Bulk** integration as above.

The folder must contain `manifest.json`. Do not rename the domain.

## First setup

Every value below is typed into **this** Home Assistant. The integration package does not contain an SSID, a password, a timezone, or a device list.

1. Start the config flow. Give the entry a site name. That name is only a label.
2. Enter the Wi-Fi SSID and password the new Shellies should join. They are stored in the config entry. Diagnostics and logs mask them.
3. Optionally enter one **device login password (admin)**. This is not the Wi-Fi password. See [Device login (auth)](#device-login-auth). Leave it blank and new devices stay open, with no login.
4. Timezone is optional. The box is pre-filled from this Home Assistant instance, the zone under **Settings → System → General**. It is not a value shipped with the integration. The format is an IANA tz database name, case-sensitive, `Region/City`. Examples: `Australia/Melbourne`, `Australia/Sydney`, `Europe/London`. Abbreviations such as `AEDT` and offsets such as `UTC+11` are rejected. The list is the TZ identifier column on [Wikipedia's tz database list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). It sets the device clock zone for on-device schedules and sunrise/sunset, which matters more when Shelly Cloud is off because the device will not auto-detect a zone. Leave it blank and adoption still works: no `location.tz` is sent. Change or clear it later under **Configure → Security and timezone**.
5. On the next step, choose the generic behaviour:
   - **Disable Shelly Cloud** and **disable the access point** default to on.
   - **Disable Bluetooth RPC** defaults to on, which matches what core Shelly already did. Turn it off if you still need Bluetooth RPC after setup. The scanner proxy does not need RPC.
   - **Auto-adopt nearby new Shellies** defaults to on. It adopts a factory-new Shelly (no login, setup window open) even when that MAC is not on the list.
   - **Only provision devices in the allowlist** defaults to on, and it overrides auto-adopt. While it is on, devices that are not on the list are left alone. Turn it off only if you want every factory-new Shelly in range. That includes a neighbour's new Shelly.
   - **Bluetooth scanner mode** defaults to **Active**, which is what you want while commissioning. **Auto** (on recent Home Assistant) uses less airtime later. **Passive** and **Disabled** are there when you are done.
   - Concurrency, retries, and how long provisioning mode stays armed.

You can change all of this later under **Configure** on the integration card: Wi-Fi, security, input profile, output profile, dimmer profile, provisioning, allowlist import, and add device. The hub device also has **Auto-adopt nearby new Shellies**, **Find my Shelly**, and **Reload device list**.

## Device login (auth)

One password, shared by the devices Shelly Bulk sets up. The username is always `admin`. It is the password for each Shelly's local web page and its local API. After Shelly Bulk sets it, `admin` and that password are written onto that device's core Shelly config entry, so Home Assistant stays connected.

Leave the field blank and devices stay open, with no login.

Saving a new password under **Configure → Security and timezone** or **Configure → Secure profile** only stores it on the Shelly Bulk entry. It does not re-key devices. Put the password in your password manager. Shelly Bulk cannot recover a lost password. Recovering the device means a factory reset.

The **Security audit** sensor stays `not_audited` until you run **Audit security** or **Secure devices**. After that, its attributes list each device. `auth_on: false` means that Shelly has no login.

| Scenario | What happens |
| --- | --- |
| New or factory device during adoption, password filled in | `Shelly.SetAuth` sets username `admin` and this password. Shelly Bulk saves both onto the core Shelly entry. |
| New or factory device, password left blank | The device stays open. No login is set. |
| Existing device with no password, and you run **Secure devices** or **Apply profile** | The stored password is applied, then saved onto that Shelly entry. Secure devices does this only when **Set the device login when a device has none** is on. |
| Existing device that already has a password | The device password is not changed. Home Assistant keeps using the password already stored on that Shelly entry. |
| You change the password in Configure | The new value is stored for the next device that still has no login. Devices that already have a password are not re-keyed. |
| The password is lost | Factory-reset the Shelly. Shelly Bulk will not guess, and it will not overwrite a device that already has a login. |

## Device list

On setup, and every time Shelly Bulk loads, it creates `config/shelly_bulk/devices.csv` if that file is missing. The new file is a header (`mac,name,room,model_hint,input,initial_state,fade_rate,transition`) plus comment lines. There is no real device data. An existing file is never overwritten. Lines that start with `#` are ignored, so a header with no devices imports as an empty list, not an error.

Edit it with the File editor, Samba, or the Studio Code Server add-on. **Reload device list** reads it again. Shelly Bulk also re-reads when the file's modification time changes. A blank name or room cell does not wipe a name you already stored. Rows that are missing from the file are not deleted on reload. **Configure → Import allowlist** and `shelly_bulk.import_allowlist` default to `shelly_bulk/devices.csv`. **Configure → Add device** appends one MAC, name, and room.

While "only provision the allowlist" is on, an empty list adopts nothing. The last-error sensor says so.

## Find my Shelly

**Find my Shelly** on the Shelly Bulk device asks every Home Assistant Bluetooth scanner and proxy for Shelly advertisements. A MAC that is not already added, and not already on the device list, is appended. The name and room are left blank and `model_hint` is filled in. Rows you have edited are not rewritten, and a MAC is not added twice. Devices that already have a login are skipped.

A persistent notification lists each new device: MAC, model, RSSI, and which scanner heard it.

When **Auto-adopt nearby new Shellies** is effectively on (the switch is on, and Only provision the allowlist is off), Find my Shelly also starts an adoption pass immediately. When auto-adopt is off, or the allowlist option overrides it, Find my Shelly only adds the rows.

A device that is advertising with Bluetooth RPC off raises the setup-window repair. Power-cycle it. Shelly Bulk does not guess a password.

## Auto-adopt nearby new Shellies

The switch is on the Shelly Bulk device and the same choice is in the setup form. It defaults to on.

When it is on and **Only provision the allowlist** is off, a factory-default Shelly (no login, setup window still open) is adopted with the full flow: Wi-Fi, security, device login password, timezone, and any channel profile you enabled. It does not have to be on the list. After adoption it is appended to `devices.csv` with a placeholder name (model plus the last 4 characters of the MAC) and a blank room. A notification asks you to rename it.

Devices that already have a login, and devices already added in Home Assistant, are not touched. Concurrency still limits how many run at once. A locked device (setup window closed) raises a repair instead of being retried.

**Only provision the allowlist overrides auto-adopt.** While that option is on, auto-adopt does not take a device that is not on the list. The switch stays on and its status says it is paused. Turn the allowlist option off and a neighbour's factory-new Shelly in Bluetooth range can be adopted.

## Identify

Each adopted Shelly gets an **Identify** button. Pressing it toggles the first output for about 2 seconds (`Switch.Set` with `toggle_after`, or the same shape on a light). The button is disabled by default on relays, plugs, and unknown models, because a toggle can energise a connected load. Light-like models (dimmer, bulb, RGB, strip) are enabled by default. Enable the button on the device page only when you are sure a short toggle is safe.

## Bulk add

Do this at the bench, or in the building with a connectable proxy that can still reach the device you are powering. Work in batches of about **20**. A batch that sits powered for a quarter of an hour locks itself.

### The setup window

Factory-new Gen2, Gen3, and Gen4 firmware (from about 1.7.5, and the tighter 2.x behaviour) accepts unauthenticated Bluetooth RPC only for a while after power-on or a reset:

- about **15 minutes** on mains devices (`provision: pending`)
- about **3 minutes** on battery devices
- about **5 minutes** more after the first IP address (`provision: confirmed`)
- then Bluetooth RPC and the open access point close (`provision: complete`)
- if the window ends before the device gets online, it goes **locked** until you power-cycle it

Shelly Bulk raises a repair and sets the last-error sensor when an allowlisted device is advertising with Bluetooth RPC off. Power-cycle that device. Do not keep retrying a locked unit.

### Walkthrough

1. Confirm the IoT SSID, DHCP, and mDNS **before** you energise a batch. A wrong password burns the window.
2. Put the connectable proxy or the Home Assistant Bluetooth adapter within a few metres of the batch. Metal back boxes and a pile of packed Shellies both hurt range.
3. Import the allowlist if you are using one. Names and rooms in that file are applied after each device joins.
4. Turn on **Provisioning mode** (the switch on the Shelly Bulk device, or the `start_provisioning` service). It turns itself off when the timeout you set is reached. It does not turn itself back on after a restart.
5. Power the batch. Each device that core Shelly discovers, that still has Bluetooth RPC open, and that is on the allowlist (or all of them, if you turned the allowlist requirement off) is answered automatically:
   - confirm the Bluetooth step
   - submit your SSID and password
   - wait while core Shelly provisions Wi-Fi and creates the device
   - set that Shelly's Bluetooth scanner to the mode you chose, so the next devices are heard further away
   - apply cloud, access point, Bluetooth RPC, timezone, name, and any channel profile you enabled
   - if you set a device login password, call `Shelly.SetAuth` (username `admin`) and write `admin` plus that password into the core Shelly entry so Home Assistant stays connected. A blank password leaves the device open
   - set the Home Assistant device name and area from the CSV
6. Watch **Devices adopted**, **Devices pending**, **Devices failed**, and **Last error**.
7. Export a report (below). Power-cycle anything that failed because the window closed, then run provisioning again. Devices already added are left alone. Devices that already have authentication are not sent a password and are not modified during adoption.
8. Move the next batch into range, including range of Shellies that are now scanning, and repeat.

Concurrency is how many of those flows run at once. Keep it inside the number of free connectable slots, not the number of Shellies in the building.

Firmware update, if you enabled it, starts `Shelly.Update` with `stage: stable` after the profile. It reboots the device and is the slow part. Leave it off while you are racing a 15-minute window, and turn it on for a later **Apply profile** pass.

## Profiles

Profiles are off until you opt in. Security choices from the config flow (cloud, access point, Bluetooth RPC, timezone, device login password, scanner mode) are applied on adoption because you set them there. The login password is applied only when the device has no login. Input, output, and dimmer sections are applied only when **Apply this profile** is on, or when a CSV row sets the same field for that device.

Open **Configure** and edit one section at a time.

### Security

- **Device login password (admin).** `Shelly.SetAuth` with username `admin`, realm set to the device id, and HA1 `SHA-256("admin:<device id>:<password>")`. The password is not logged. It is sent only when the device has no login. A device that already has a password is not changed, and Home Assistant keeps the password already stored on that Shelly entry. See [Device login (auth)](#device-login-auth).
- **Cloud.** `Cloud.SetConfig` with `enable: false` when disable-cloud is on. Unchecking it leaves the cloud setting as the device has it.
- **Access point.** Core Shelly turns the AP off after Bluetooth provisioning. Shelly Bulk sends your choice afterwards, so unchecking the box turns the AP back on.
- **Bluetooth RPC.** Same pattern. `BLE.SetConfig` keeps Bluetooth **enabled** (`enable: true`) so the scanner still works, and sets `rpc.enable` from your checkbox.
- **Name and timezone.** `Sys.SetConfig` `device.name` from the allowlist. `location.tz` is sent only when a timezone is stored. The format is an IANA name such as `Australia/Melbourne` (see the [TZ identifier list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)). An empty timezone omits `location.tz`, so the device clock zone is left as it is.
- **Scanner.** Core Shelly option `ble_scanner_mode`, set to active, auto, passive, or disabled.

### Inputs

Per input, Shelly Bulk can set:

| You choose | What is sent |
| --- | --- |
| Switch | `Input.SetConfig` `type: switch` |
| Button | `type: button` |
| Follow | output `in_mode: follow` |
| Toggle / flip | `in_mode: flip` |
| Momentary | `in_mode: momentary` on a switch. On a dimmer, momentary is not valid, so Shelly Bulk sends `dim` and notes that. |
| Detached | `in_mode: detached`. The physical input no longer drives the relay or the light output. |
| Activation | `in_mode: activate` |
| Invert | `Input.SetConfig` `invert: true` or `false` |

`match_input` is a switch power-on state. `toggle` is a dimmer power-on state. A value the component does not accept is skipped for that component.

### Outputs

On each `switch`, `light`, `rgb`, `rgbw`, or `cct` channel:

- `initial_state`: `off`, `on`, `restore_last`, and `match_input` (switches) or `toggle` (dimmers)
- `auto_on`, `auto_on_delay`, `auto_off`, `auto_off_delay`

### Dimmers

On light-like channels, when the dimmer profile is on:

- **Button fade rate** → `button_fade_rate`, 1 (slowest) to 5 (fastest). This is the rate while a button is held.
- **Transition duration** → `transition_duration`, seconds for a 0% to 100% ramp. This is the field the Shelly Light docs actually define.
- **Ramp up / ramp down.** Separate up and down times are **not** in the verified Light config. Shelly Bulk sends them only when that device's current config already has `transition_duration_up` / `transition_duration_down` or `ramp_up` / `ramp_down`. Otherwise it uses `transition_duration` and says so in the report.
- **Minimum and maximum brightness** → `range_map: [min, max]`. Both are required, and max must be greater than min.
- **Night mode** → `night_mode.enable`, `night_mode.brightness`, `night_mode.active_between` as `["HH:MM", "HH:MM"]`.
- **Power-on brightness.** There is no verified `power_on_brightness` field in the public Light config. Shelly Bulk sends `power_on_brightness`, `initial_brightness`, or `brightness` only when `GetConfig` already contains that key. Otherwise it records that the device has nowhere to put it.
- **Button dimming** → `in_mode` `dim` (one button: short press toggles, hold dims) or `dual_dim`.

`apply_profile` runs the same plan against Shellies that are already in Home Assistant. Target a device, an area, a MAC, a model substring, or every Shelly entry.

## Securing devices

The secure profile is a checklist, not a silent change. Set the device login password under **Configure → Security and timezone** or **Configure → Secure profile**. Typing a password there only stores it. It does not re-key devices. Leave the box blank to keep the stored password. Then run **Secure devices**, or call `shelly_bulk.secure_devices`. You can secure one device, an area, or every core Shelly.

Shelly Bulk applies the calls and reads each setting back. `Shelly.SetAuth` runs only for a device that has no login, and only when that checklist item is on. The username written to the device and to the core Shelly entry is `admin`. Devices that already have a password are left unchanged, and Home Assistant keeps the password already stored for them. The password and the HA1 digest are not written to logs, diagnostics, or the audit.

| Checklist item | RPC | Default |
| --- | --- | --- |
| Set the device login when a device has none | `Shelly.SetAuth` (username `admin`, realm = device id, HA1 = SHA-256 of `admin:id:password`). Skipped when the device already has a login | On |
| Disable Shelly Cloud | `Cloud.SetConfig` `enable: false` | On |
| Disable the Wi-Fi access point | `WiFi.SetConfig` `ap.enable: false` | On |
| Disable Bluetooth RPC, keep Bluetooth | `BLE.SetConfig` `enable: true`, `rpc.enable: false` | On |
| Disable MQTT | `MQTT.SetConfig` `enable: false` | Off. Skipped when the device has no MQTT component |
| Disable outbound websocket | `Ws.SetConfig` `enable: false` | Off |
| Disable debug and UDP logging | `Sys.SetConfig` `debug.*` off and `rpc_udp.listen_port: null` | On |
| Keep firmware updates manual | Does not call `Shelly.Update`. Gen2+ has no documented auto-update switch; cloud push stops when cloud is off | Off |
| Restrict the web UI | `Sys.SetConfig` `device.discoverable: false`. The page itself asks for the device login when a password is set | Off |

`audit_security` only reads. The **Security audit** sensor shows `passed/total` (or `not_audited` before the first audit). Each device row includes `auth_on`. `false` means that Shelly has no login. The other fields are cloud off, access point off, Bluetooth RPC off, and firmware version.

```yaml
action: shelly_bulk.secure_devices
data:
  mac: "00:00:00:00:00:01"
  disable_mqtt: true
  restrict_web_ui: true
```

```yaml
action: shelly_bulk.audit_security
data:
  all_shelly: true
```

## Change a device's settings later

**Configure → Edit a device** lists every Shelly already added by Home Assistant. Each row shows the name, room, model, and MAC. The next form is filled from that device over RPC, and it only includes settings the device's own config reports: name, room, input type and behaviour (switch, button, follow, flip, momentary, detached, activate, and dim modes when the device has them), invert, power-on state, auto-on and auto-off with their delays, and, on a dimmer, fade rate, transition, minimum and maximum brightness, and night mode.

Saving writes those values, reads them back, and marks any field the device did not keep. The Home Assistant device name and area are updated, and the same name, room, input, power-on state, fade rate, and transition are written into `shelly_bulk/devices.csv`.

The following screen can copy the channel settings onto other devices. Type a model name to filter the list. Leave it empty to stop after the one device. The name and room are not copied.

On a switch, **follow** only works with power-on state **match_input**. Changing input behaviour away from follow sets power-on to **restore_last**, and changing it to follow sets **match_input**. Those two fields are written in one call. The power-on list only shows values that are valid for the current input behaviour, and a switch is never sent `toggle` or a display label such as "Restore last".

**Configure → Bulk change settings** chooses devices by group: all of them, one model (the list shows how many), one room (including **No room**), only devices that still have the factory hostname, or a short individual pick. The confirmation says how many devices will change and lists each MAC and IP. Every setting starts as leave unchanged. Only ticked fields are sent, and dimmer fields are hidden unless the group includes a dimmer. The form closes straight away. Shelly Bulk updates about five devices at a time, gives each one a timeout, reads the value back, and posts progress to a notification and to the report.

Copy settings to other devices uses that same group selector and also runs in the background.

The switches, selects, Identify button, auto-off delay, and MAC and IP sensors that Shelly Bulk adds to each Shelly are enabled. Identify only runs when you press it. If an older install had turned those controls off itself, they are turned back on. A control you disabled stays off.

Each of those controls sits on a Shelly Bulk device named after the Shelly, not after the hub. When the Shelly has a name in Home Assistant, the device is that name, the MAC, and the IP. Otherwise it is the model, the last four characters of the MAC, and the IP. The name follows a new IP unless you have renamed the device. New entity ids use that name. Entity ids that already exist are not renamed.

Each core Shelly shows **MAC address** and **IP address** on its device page. The MAC is also under Device info, and **Visit** opens `http://` plus the IP. The IP sensor uses the address the device reports when it is reachable, and otherwise the host stored by the Shelly integration. Labels in Edit a device and in the bulk confirmation use the Home Assistant name, or the model plus the last four characters of the MAC, together with the room, MAC, and IP. The factory hostname is not used as the name.

On each adopted Shelly's device page, **Input behaviour**, **Power-on state**, and **Auto off delay** are enabled. A dimmer also has **Fade rate** and **Transition**. Changing one writes it to the device and shows the value the device read back, so the same controls work on a dashboard. The advanced switches (cloud, Bluetooth, MQTT, and the rest) stay disabled until you enable them.

## Advanced settings

Each core Shelly gets config switches and selects: Bluetooth, Bluetooth RPC, scanner mode, cloud, access point, MQTT, eco mode, status LED, debug logging, input behaviour, and power-on state. They are **disabled by default** so a large install does not poll every device. Enable the ones you want on the device page. Changing one reads the new value back from the device.

Scanner mode is the core Shelly option `ble_scanner_mode` (`active`, `auto`, `passive`, `disabled`). The others are Gen2+ RPC. A model without that component is left unchanged and the result says so.

`set_advanced` is the bulk form of the same settings, plus input type, auto-on and auto-off timers, dimmer fade rate, transition time, and the Shelly device name.

```yaml
action: shelly_bulk.set_advanced
data:
  mac: "00:00:00:00:00:01"
  channel: 0
  input_mode: detached
  power_on_state: restore_last
  auto_off: true
  auto_off_delay: 120
  fade_rate: 2
  cloud: false
  scanner_mode: active
```

## Services

Replace the sample MAC and the filename. Call these from **Developer tools → Actions**, an automation, or a script. `site` is only required when you have more than one Shelly Bulk entry.

### Start and stop provisioning

```yaml
action: shelly_bulk.start_provisioning
data:
  provisioning_minutes: 30
```

```yaml
action: shelly_bulk.stop_provisioning
```

The switch and these actions are the same mode. It stays off across restarts.

### Import the allowlist

```yaml
action: shelly_bulk.import_allowlist
data:
  filename: shelly_bulk/devices.csv
  replace: true
```

`filename` is relative to the Home Assistant config directory. `replace: false` merges by MAC.

### Apply the profile

```yaml
action: shelly_bulk.apply_profile
data:
  all_shelly: true
```

```yaml
action: shelly_bulk.apply_profile
data:
  device_id:
    - 0123456789abcdef0123456789abcdef
```

```yaml
action: shelly_bulk.apply_profile
data:
  mac: "00:00:00:00:00:01"
  model_contains: Dimmer
```

### One input

```yaml
action: shelly_bulk.set_input_mode
data:
  mac: "00:00:00:00:00:01"
  input_id: 0
  input_type: button
  input_mode: detached
  invert: false
```

### One dimmer channel

```yaml
action: shelly_bulk.set_dimmer_fade
data:
  mac: "00:00:00:00:00:01"
  channel: 0
  fade_rate: 2
  transition_duration: 1.5
```

`fade_rate` is 1–5. `transition_duration` is seconds.

### Export the report

```yaml
action: shelly_bulk.export_report
data:
  format: both
```

`format` is `csv`, `json`, or `both`. Files land in `config/shelly_bulk/`. They list MAC, name, room, status, model, firmware, host, error, and notes. They do not list the Wi-Fi password, the device password, or the HA1 digest. Allowlist rows that have not been seen yet are included as `not_seen`.

## CSV format

Dummy data only. Do not commit a real list.

```csv
mac,name,room,input,initial_state,fade_rate,transition
00:00:00:00:00:01,Example downlights,Example room,detached,restore_last,,
00:00:00:00:00:02,Example lamp,Example room,dim,restore_last,2,1.5
```

`mac` is required. `name` and `room` (or `area`) become the Home Assistant device name and area; the area is created if it does not exist. `model` / `model_hint` is stored and not sent.

Optional columns, applied to every channel on that row unless you set `channel` to a number:

`input` (shorthand: `switch`, `toggle`, `button`, `momentary`, `detached`, `activation`, `dim`, `dual_dim`), `input_type`, `input_mode`, `invert`, `initial_state`, `auto_on`, `auto_on_delay`, `auto_off`, `auto_off_delay`, `fade_rate`, `transition`, `transition_up`, `transition_down`, `min_brightness`, `max_brightness`, `night_mode`, `night_brightness`, `night_start`, `night_end`, `power_on_brightness`, `button_dimming`.

A second row with the same MAC and `channel` set overrides just that channel. Blank cells do not clear a shared profile; they mean "leave the profile value".

## Sensors and the repair

The Shelly Bulk device (one per config entry) exposes:

- **Devices adopted**
- **Devices pending** (flows running right now)
- **Devices failed**
- **Last error** (`none` when there has not been one)
- **Provisioning mode**

A device that is advertising with Bluetooth RPC off raises **Shelly setup window is closed**. Power-cycle it. The issue is removed if that MAC is later adopted.

## Troubleshooting

| What you see | What it usually means |
| --- | --- |
| Last error says the allowlist is empty | Provisioning is armed and "only the allowlist" is on, but you have not imported a CSV. |
| `flow aborted: ble_not_permitted` or the setup-window repair | The 15-minute (or 3-minute) window has closed, or Bluetooth writes are rejected. Power-cycle the device. |
| `cannot_connect` | Nothing that can open GATT heard the device. A Shelly scanner is not enough on its own. Move a connectable proxy closer. |
| Timed out waiting for Wi-Fi | Wrong SSID or password, 5 GHz or WPA3-only SSID, no DHCP, or mDNS not reaching Home Assistant. |
| `skipped_auth` | The device already has a password, or the advertisement says authentication is on. Shelly Bulk did not send credentials and did not change it. Factory-reset if you meant to adopt it. |
| Adopted, then core Shelly wants a reauth | The device login was set. Shelly Bulk writes `admin` and that password onto the Shelly entry after `Shelly.SetAuth`. If the device rebooted mid-write, enter that same password in the Shelly reauth form. |
| Dimmer fade "skipped" | That model has no `button_fade_rate` or `transition_duration`. The note in the report names the field. |
| Power-on brightness not sent | The component config has no brightness field Shelly Bulk is willing to guess. |
| Many identical devices, the wrong one joined | Use the allowlist. Shelly Bulk will not adopt a MAC that is not on it while that option is on. |
| Gen1 never appears | Expected. Gen1 has no Bluetooth RPC. |
| Provisioning mode turned off on its own | The timeout elapsed, or you reloaded the entry (changing options reloads it and stops the loop). |

Core Shelly flow step ids are part of Home Assistant, not this integration. If a future core release renames `bluetooth_confirm` or `wifi_scan`, adoption will record `Unhandled Shelly flow step ...` instead of guessing. Check the release notes and open an issue.

## FAQ

**Does this replace the Shelly integration?**
No. Devices are added by core Shelly. Shelly Bulk only answers the Bluetooth flow, then sets options and RPC on the device core already owns.

**Will adopted Shellies provision the next ones over Bluetooth?**
They help you *hear* the next ones. They do not connect to them. Keep a connectable adapter or ESPHome proxy in the chain.

**Can I adopt a device that already has a password?**
Not automatically. Shelly Bulk will not try the device login password against a locked device. Add it yourself in core Shelly. Apply profile and Secure devices still will not replace an existing device password. Home Assistant keeps using the password already stored on that Shelly entry.

**Does changing the device login password in Configure update devices that already have one?**
No. Configure only stores the new password on the Shelly Bulk entry. It is used the next time a device with no login is adopted, or when you run Secure devices or Apply profile against a device that still has no login.

**Where do the secrets live?**
On the Shelly Bulk config entry in Home Assistant's `.storage`, the same way other integrations store passwords. They are masked in diagnostics and in this integration's logs. Do not put them in the CSV. Do not commit a CSV.

**What if I have two sites?**
Add a second Shelly Bulk entry with a different site name. Pass `site:` to services when more than one entry exists.

**Is the workshop script the same thing?**
`tools/shelly_ble_provision.py` is an optional bench tool for a laptop that cannot see the Home Assistant instance. It is not tested on hardware. The integration is the supported path. The script reads secrets from the environment (`SHELLY_WIFI_SSID`, `SHELLY_WIFI_PASS`, `SHELLY_ADMIN_PASS`, `HA_TOKEN`, `SHELLY_TZ`) and has no default timezone.

## Security

- Wi-Fi and device passwords are config-entry data. They are not arguments to the workshop script, not fields in the report, and not written to diagnostics in the clear.
- A log filter masks those values, and the HA1 digest once it has been computed, if they ever appear in a log line or traceback from this integration.
- Devices with authentication already enabled are skipped during adoption. Shelly Bulk does not guess.
- Disabling cloud, the access point, and Bluetooth RPC is available because a commissioned device should not keep an open setup channel. Bluetooth itself stays on when you want the scanner.
- "Only provision the allowlist" defaults to on so a neighbour's new Shelly, or a device already in the building that you did not list, is not adopted just because provisioning mode is on.
- Provisioning mode is a switch with a timeout. It does not survive a restart.
- The allowlist import refuses paths outside the config directory.
- Use a dedicated IoT VLAN. This integration does not configure the network.
- The repository is public. Do not open a pull request that contains a real SSID, password, MAC, or site list.

## Contributing

Issues and pull requests go to [ianda-tech/shelly-hass](https://github.com/ianda-tech/shelly-hass). Code owners are `@ianda-tech`.

```bash
pip install -r requirements_test.txt
pytest
```

GitHub Actions runs hassfest, HACS validation, and pytest. Tests use Home Assistant's config-flow harness and a fake RPC session. They do not talk to hardware. If you change an RPC field, cite the Shelly component doc you checked (`https://shelly-api-docs.shelly.cloud/gen2/`) and say when a model refused it. Bump `manifest.json`, the **Current version** line at the top of this README, and add a `CHANGELOG.md` section with the same version. The release workflow on `main` turns that section into the GitHub release HACS lists.

Please don't add site defaults "to make the form easier". The config flow is supposed to be empty of SSID, password, and devices. Timezone may be suggested from the running Home Assistant instance. Examples such as `Australia/Melbourne` in the docs are format samples, not a default.

## Licence and credits

[MIT](LICENSE). Copyright 2026 Innovate and Automate.

Shelly Bulk is not a Shelly or Home Assistant product. It depends on:

- Home Assistant's Shelly integration, including Bluetooth Wi-Fi provisioning (core 2025.12 and later) and the `ble_scanner_mode` option
- [aioshelly](https://github.com/home-assistant-libs/aioshelly) for RPC over IP, and for the Bluetooth advertisement block layout
- Shelly's Gen2 RPC documentation at [shelly-api-docs.shelly.cloud](https://shelly-api-docs.shelly.cloud/gen2/)

## What is not proven on hardware

The flow step ids, RPC method names, and the fields listed above were checked against public core and Shelly docs. They have **not** been run against a pile of real Shellies. In particular, treat as unverified until you try a device:

- separate dimmer ramp-up and ramp-down fields (not in the public Light config; sent only if the device already has them)
- a dedicated power-on brightness key
- every `in_mode` on every model (cycle, dual_dim, and activate are model-dependent)
- how long a given firmware keeps Bluetooth RPC open after the first IP address
- Shelly scanner "active" as a way to extend GATT range (it does not)

If a call fails on a model, Shelly Bulk keeps going and writes the skipped field into the report. That report is the thing to bring back from the first real batch.
