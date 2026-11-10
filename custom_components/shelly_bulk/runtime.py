"""Runtime state for one Shelly Bulk config entry."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.storage import Store

from .allowlist import parse_allowlist_csv, resolve_config_path
from .const import (
    CONF_BLE_SCANNER_MODE,
    CONF_DISABLE_AP,
    CONF_DISABLE_BLE_RPC,
    CONF_DISABLE_CLOUD,
    CONF_FLEET_PASSWORD,
    CONF_PROVISIONING_MINUTES,
    CONF_REQUIRE_ALLOWLIST,
    CONF_SITE_NAME,
    CONF_TIMEZONE,
    CONF_UPDATE_FIRMWARE,
    CONF_WIFI_PASSWORD,
    CONF_WIFI_SSID,
    CONNECT_ATTEMPTS,
    DOMAIN,
    MAX_STORED_RESULTS,
    SHELLY_DOMAIN,
    STORAGE_VERSION,
    VERSION,
)
from .models import AllowDevice, Allowlist, ChannelSettings
from .advanced import read_setting, scanner_mode_valid, write_setting
from .profile import build_set_auth, plan_config_calls, security_from_entry
from .provision import Provisioner
from .security import (
    apply_secure_profile,
    evaluate_security,
    read_security_state,
    secure_profile_from,
)
from .redact import SecretFilter, redact
from .rpc import AuthRequiredError, async_execute_calls, async_open_rpc
from .util import display_mac, normalize_mac

_LOGGER = logging.getLogger(__name__)


class FleetRuntime:
    """Holds the allowlist, adoption stats, and the provisioning loop."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.allowlist = Allowlist()
        self.adopted = 0
        self.failed = 0
        self.last_error = ""
        self.results: list[dict[str, Any]] = []
        self.last_audit: list[dict[str, Any]] = []
        self.provisioner = Provisioner(self)
        self._listeners: list[Any] = []
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._extra_secrets: set[str] = set()
        self._log_filter = SecretFilter(self.secrets)
        _LOGGER.addFilter(self._log_filter)

    @property
    def site_name(self) -> str:
        return str(self.entry.data.get(CONF_SITE_NAME) or "Shelly Bulk")

    @property
    def require_allowlist(self) -> bool:
        return bool(self.entry.options.get(CONF_REQUIRE_ALLOWLIST, True))

    @property
    def pending(self) -> int:
        return self.provisioner.pending

    @property
    def provisioning_active(self) -> bool:
        return self.provisioner.active

    def secrets(self) -> list[str]:
        data = self.entry.data
        values = [
            str(data.get(CONF_WIFI_PASSWORD) or ""),
            str(data.get(CONF_WIFI_SSID) or ""),
            str(data.get(CONF_FLEET_PASSWORD) or ""),
            *self._extra_secrets,
        ]
        return [value for value in values if value]

    def redact(self, text: str) -> str:
        return redact(text, self.secrets())

    def add_listener(self, update) -> Any:
        self._listeners.append(update)

        def _remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    def notify(self) -> None:
        for update in list(self._listeners):
            update()

    def set_last_error(self, message: str) -> None:
        self.last_error = self.redact(message)[:255]
        self.notify()
        self._store.async_delay_save(self._store_data, 1)

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.allowlist = Allowlist.from_dict(stored.get("allowlist"))
        self.adopted = int(stored.get("adopted") or 0)
        self.failed = int(stored.get("failed") or 0)
        self.last_error = str(stored.get("last_error") or "")
        self.results = list(stored.get("results") or [])

    async def async_close(self) -> None:
        await self.provisioner.stop("unloaded")
        _LOGGER.removeFilter(self._log_filter)
        await self._store.async_save(self._store_data())

    def _store_data(self) -> dict[str, Any]:
        return {
            "allowlist": self.allowlist.to_dict(),
            "adopted": self.adopted,
            "failed": self.failed,
            "last_error": self.last_error,
            "results": self.results[-MAX_STORED_RESULTS:],
        }

    def record(self, mac: str, status: str, error: str = "", **extra: Any) -> None:
        """Append a per-device result. Passwords are never stored."""
        safe_error = self.redact(error)
        row = {
            "mac": display_mac(mac) if _is_mac(mac) else mac,
            "status": status,
            "error": safe_error,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        row.update({key: value for key, value in extra.items() if key not in {"password", "ssid", "ha1"}})
        self.results.append(row)
        self.results = self.results[-MAX_STORED_RESULTS:]
        if status == "ok":
            self.adopted += 1
            async_delete_issue(self.hass, DOMAIN, f"ble_window_{_mac_key(mac)}")
        elif status == "failed":
            self.failed += 1
            self.last_error = safe_error[:255]
        elif status == "skipped_auth":
            self.last_error = safe_error[:255]
        self.notify()
        self._store.async_delay_save(self._store_data, 1)
        _LOGGER.info("Shelly %s: %s %s", row["mac"], status, safe_error)

    def shelly_entry_for(self, mac: str) -> ConfigEntry | None:
        try:
            plain = normalize_mac(mac)
        except ValueError:
            return None
        for entry in self.hass.config_entries.async_entries(SHELLY_DOMAIN):
            if entry.unique_id and _mac_key(entry.unique_id) == plain:
                return entry
        dev_reg = dr.async_get(self.hass)
        for device in dev_reg.devices.values():
            for domain, value in device.connections:
                if domain == dr.CONNECTION_NETWORK_MAC and _mac_key(value) == plain:
                    for entry_id in device.config_entries:
                        entry = self.hass.config_entries.async_get_entry(entry_id)
                        if entry and entry.domain == SHELLY_DOMAIN:
                            return entry
        return None

    def flag_locked(self, mac: str, local_name: str = "") -> None:
        shown = display_mac(mac)
        self.set_last_error(
            f"{shown} is advertising without Bluetooth RPC. Power-cycle it to reopen the setup window."
        )
        async_create_issue(
            self.hass,
            DOMAIN,
            f"ble_window_{_mac_key(mac)}",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="ble_window_closed",
            translation_placeholders={"mac": shown, "name": local_name or shown},
        )

    async def start_provisioning(self, minutes: float | None = None) -> None:
        if minutes is None:
            minutes = float(self.entry.options.get(CONF_PROVISIONING_MINUTES, 30) or 30)
        await self.provisioner.start(minutes)

    async def stop_provisioning(self) -> None:
        await self.provisioner.stop("stopped")

    async def async_import_allowlist(self, filename: str, replace: bool = True) -> int:
        path = resolve_config_path(self.hass.config.path(), filename)
        if not path.is_file():
            raise ServiceValidationError(f"No CSV at {filename} inside the config directory")
        text = await self.hass.async_add_executor_job(path.read_text, "utf-8-sig")
        parsed, errors = parse_allowlist_csv(text)
        if errors and not parsed.devices:
            raise ServiceValidationError("; ".join(errors[:5]))
        if replace:
            self.allowlist = parsed
        else:
            self.allowlist.devices.update(parsed.devices)
        self._store.async_delay_save(self._store_data, 0.1)
        self.notify()
        if errors:
            self.set_last_error("Allowlist imported with row errors: " + "; ".join(errors[:5]))
        _LOGGER.info("Imported %s allowlist devices from the config directory", len(parsed.devices))
        return len(self.allowlist.devices)

    async def async_export_report(self, report_format: str = "both") -> dict[str, str]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder = Path(self.hass.config.path("shelly_bulk"))
        slug = "".join(char if char.isalnum() or char in "-_" else "-" for char in self.site_name.lower())
        slug = slug.strip("-") or "site"
        rows = self._report_rows()
        paths: dict[str, str] = {}

        def _write(path: Path, payload: str) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")

        if report_format in {"json", "both"}:
            json_path = folder / f"report-{slug}-{stamp}.json"
            await self.hass.async_add_executor_job(
                _write, json_path, json.dumps(rows, indent=2)
            )
            paths["json"] = str(json_path)
        if report_format in {"csv", "both"}:
            csv_path = folder / f"report-{slug}-{stamp}.csv"
            buffer = io.StringIO()
            fieldnames = ["mac", "name", "room", "status", "model", "firmware", "host", "error", "notes", "at"]
            writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                flat = dict(row)
                if isinstance(flat.get("notes"), list):
                    flat["notes"] = " | ".join(str(note) for note in flat["notes"])
                writer.writerow(flat)
            await self.hass.async_add_executor_job(_write, csv_path, buffer.getvalue())
            paths["csv"] = str(csv_path)
        return paths

    def _report_rows(self) -> list[dict[str, Any]]:
        seen = {_mac_key(str(row.get("mac", ""))) for row in self.results}
        rows = [dict(row) for row in self.results]
        for mac, device in self.allowlist.devices.items():
            if mac in seen:
                continue
            rows.append(
                {
                    "mac": display_mac(mac),
                    "name": device.name,
                    "room": device.room,
                    "status": "not_seen",
                    "error": "No adoption result yet",
                    "at": "",
                }
            )
        return rows

    async def finish_adopted_device(self, mac: str) -> None:
        entry = await self.provisioner.wait_for_entry(mac)
        if entry is None:
            self.record(
                mac,
                "failed",
                "Home Assistant did not create a Shelly entry. The 15-minute setup window "
                "may have closed; power-cycle the device and try again.",
            )
            self.flag_locked(mac)
            return
        await self._wait_settled(entry)
        await self._customise(entry, mac, provisioning=True)

    async def apply_profile(
        self,
        *,
        device_ids: set[str] | None = None,
        area_ids: set[str] | None = None,
        mac: str | None = None,
        all_shelly: bool = False,
        model_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        entries = self._select_shelly_entries(
            device_ids=device_ids or set(),
            area_ids=area_ids or set(),
            mac=mac,
            all_shelly=all_shelly,
            model_contains=model_contains,
        )
        if not entries:
            raise ServiceValidationError(
                "No core Shelly devices matched. Add them first, or pass a MAC, device, area, or all_shelly."
            )
        outcomes = []
        for entry in entries:
            identity = entry.unique_id or entry.entry_id
            await self._customise(entry, identity, provisioning=False)
            outcomes.append(self.results[-1] if self.results else {"mac": identity, "status": "unknown"})
        return outcomes

    async def set_input_mode(
        self,
        *,
        device_ids: set[str],
        area_ids: set[str],
        mac: str | None,
        input_id: int,
        input_type: str | None,
        input_mode: str | None,
        invert: bool | None,
    ) -> None:
        settings = ChannelSettings(
            input_type=input_type or None,
            input_mode=input_mode or None,
            invert=invert,
        )
        if settings.is_empty():
            raise ServiceValidationError("Set an input type, mode, or invert value")
        await self._apply_channel_override(
            device_ids=device_ids, area_ids=area_ids, mac=mac, index=input_id, settings=settings
        )

    async def set_dimmer_fade(
        self,
        *,
        device_ids: set[str],
        area_ids: set[str],
        mac: str | None,
        channel: int,
        fade_rate: int | None,
        transition: float | None,
        transition_up: float | None,
        transition_down: float | None,
    ) -> None:
        settings = ChannelSettings(
            fade_rate=fade_rate,
            transition=transition,
            transition_up=transition_up,
            transition_down=transition_down,
        )
        if settings.is_empty():
            raise ServiceValidationError("Set a fade rate or a transition time")
        await self._apply_channel_override(
            device_ids=device_ids, area_ids=area_ids, mac=mac, index=channel, settings=settings
        )

    async def _apply_channel_override(
        self,
        *,
        device_ids: set[str],
        area_ids: set[str],
        mac: str | None,
        index: int,
        settings: ChannelSettings,
    ) -> None:
        entries = self._select_shelly_entries(
            device_ids=device_ids, area_ids=area_ids, mac=mac, all_shelly=False, model_contains=None
        )
        if not entries:
            raise ServiceValidationError("No matching Shelly device")
        for entry in entries:
            allow = AllowDevice(mac=_mac_key(entry.unique_id or ""))
            allow.by_channel[index] = settings
            await self._customise(
                entry,
                entry.unique_id or entry.entry_id,
                provisioning=False,
                allow=allow,
                include_security=False,
                use_profile=False,
            )

    def _select_shelly_entries(
        self,
        *,
        device_ids: set[str],
        area_ids: set[str],
        mac: str | None,
        all_shelly: bool,
        model_contains: str | None,
    ) -> list[ConfigEntry]:
        found: dict[str, ConfigEntry] = {}
        if mac:
            entry = self.shelly_entry_for(mac)
            if entry:
                found[entry.entry_id] = entry
        dev_reg = dr.async_get(self.hass)
        wanted = set(device_ids)
        for area_id in area_ids:
            for device in dr.async_entries_for_area(dev_reg, area_id):
                wanted.add(device.id)
        for device_id in wanted:
            device = dev_reg.async_get(device_id)
            if device is None:
                continue
            for entry_id in device.config_entries:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == SHELLY_DOMAIN:
                    found[entry.entry_id] = entry
        if all_shelly or (not found and model_contains):
            for entry in self.hass.config_entries.async_entries(SHELLY_DOMAIN):
                found[entry.entry_id] = entry
        entries = list(found.values())
        if model_contains:
            needle = model_contains.lower()
            entries = [
                entry
                for entry in entries
                if needle in str(entry.data.get("model", "")).lower()
                or needle in (entry.title or "").lower()
            ]
        return entries

    async def _customise(
        self,
        entry: ConfigEntry,
        mac: str,
        *,
        provisioning: bool,
        allow: AllowDevice | None = None,
        include_security: bool = True,
        use_profile: bool = True,
    ) -> None:
        host = entry.data.get(CONF_HOST)
        if not host:
            self.record(mac, "failed", "The Shelly entry has no host")
            return
        if provisioning:
            # Arm the advertisement proxy before the slower profile calls, so the
            # next bench batch can be heard while this device is still being customised.
            self._enable_scanner_and_credentials(entry, None)
        port = int(entry.data.get(CONF_PORT) or 80)
        verify_ssl = bool(entry.data.get(CONF_VERIFY_SSL, False))
        username = entry.data.get(CONF_USERNAME) or None
        password = entry.data.get(CONF_PASSWORD) or None
        if provisioning:
            username = None
            password = None
        listed = allow if allow is not None else self.allowlist.get(mac)
        try:
            plain = normalize_mac(mac)
        except ValueError:
            plain = mac
        if listed is None and plain:
            listed = self.allowlist.get(plain)

        session = None
        notes: list[str] = []
        try:
            session = await self._connect_with_retries(host, port, username, password, verify_ssl)
        except AuthRequiredError:
            if provisioning:
                self.record(
                    mac,
                    "skipped_auth",
                    "Authentication is already enabled. The device was not changed.",
                )
                return
            self.record(mac, "failed", "Authentication failed with the password stored on the Shelly entry")
            return
        except Exception as err:  # noqa: BLE001
            self.record(mac, "failed", f"Could not connect: {err}")
            return

        try:
            shelly = dict(session.shelly)
            if int(shelly.get("gen") or 0) == 1:
                self.record(mac, "failed", "Gen1 devices are not supported", model=shelly.get("model", ""))
                return
            if shelly.get("auth_en") and provisioning:
                self.record(mac, "skipped_auth", "Authentication is already enabled. The device was not changed.")
                return
            if shelly.get("auth_en") and not provisioning:
                notes.append("Authentication is already enabled. The password was left unchanged.")

            device_name = listed.name if listed and listed.name else ""
            security = security_from_entry(self.entry.data, self.entry.options, device_name) if include_security else None
            options = dict(self.entry.options) if use_profile else {}
            calls, plan_notes = plan_config_calls(
                security=security,
                options=options,
                config=dict(session.config),
                device=listed,
            )
            notes.extend(plan_notes)
            restart = await async_execute_calls(session, calls, notes, self.redact)
            if restart:
                await session.call("Shelly.Reboot", {"delay_ms": 1500})
                notes.append("Reboot requested by the device")
                await session.shutdown()
                session = None
                await asyncio.sleep(4)
                session = await self._connect_with_retries(host, port, username, password, verify_ssl)
                shelly = dict(session.shelly)

            firmware = str(shelly.get("ver") or "")
            if self.entry.options.get(CONF_UPDATE_FIRMWARE) and include_security:
                firmware = await self._maybe_update(session, notes) or firmware

            auth_set = False
            fleet_password = str(self.entry.data.get(CONF_FLEET_PASSWORD) or "")
            if fleet_password and not shelly.get("auth_en") and include_security:
                device_id = str(shelly.get("id") or "")
                if not device_id:
                    notes.append("Shelly.SetAuth skipped: device id missing")
                else:
                    params = build_set_auth(device_id, fleet_password)
                    self._extra_secrets.add(params["ha1"])
                    await session.call("Shelly.SetAuth", params)
                    auth_set = True
                    notes.append("Device authentication enabled")

            await session.shutdown()
            session = None
            self._enable_scanner_and_credentials(entry, fleet_password if auth_set else None)
            area_note = await self._assign_name_area(
                entry,
                device_name,
                listed.room if listed else "",
            )
            if area_note:
                notes.append(area_note)
            self.record(
                mac,
                "ok",
                "",
                name=device_name,
                room=listed.room if listed else "",
                model=str(shelly.get("model") or entry.data.get("model") or ""),
                firmware=firmware,
                host=str(host),
                notes=notes,
            )
        except Exception as err:  # noqa: BLE001
            self.record(mac, "failed", str(err), notes=notes)
        finally:
            if session is not None:
                try:
                    await session.shutdown()
                except Exception:  # noqa: BLE001
                    pass

    async def _connect_with_retries(self, host, port, username, password, verify_ssl):
        last: Exception | None = None
        for _ in range(CONNECT_ATTEMPTS):
            try:
                return await async_open_rpc(
                    self.hass, str(host), int(port), username, password, verify_ssl
                )
            except AuthRequiredError:
                raise
            except Exception as err:  # noqa: BLE001
                last = err
                await asyncio.sleep(3)
        assert last is not None
        raise last

    async def _maybe_update(self, session, notes: list[str]) -> str | None:
        try:
            available = await session.call("Shelly.CheckForUpdate") or {}
        except Exception as err:  # noqa: BLE001
            notes.append(f"Firmware check failed: {self.redact(str(err))}")
            return None
        stable = available.get("stable") or {}
        if not stable.get("version"):
            notes.append("No stable firmware update is advertised")
            return None
        try:
            await session.call("Shelly.Update", {"stage": "stable"})
            notes.append(f"Stable firmware update started ({stable.get('version')})")
        except Exception as err:  # noqa: BLE001
            notes.append(f"Firmware update failed: {self.redact(str(err))}")
        return None

    def _enable_scanner_and_credentials(self, entry: ConfigEntry, new_password: str | None) -> None:
        mode = str(self.entry.options.get(CONF_BLE_SCANNER_MODE) or "active")
        options = dict(entry.options)
        options[CONF_BLE_SCANNER_MODE] = mode
        data = dict(entry.data)
        if new_password:
            data[CONF_USERNAME] = "admin"
            data[CONF_PASSWORD] = new_password
        self.hass.config_entries.async_update_entry(entry, data=data, options=options)

    async def _assign_name_area(self, entry: ConfigEntry, name: str, room: str) -> str:
        if not name and not room:
            return ""
        dev_reg = dr.async_get(self.hass)
        primary = None
        for _ in range(20):
            devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
            primary = next((device for device in devices if device.via_device_id is None), None)
            if primary is None and devices:
                primary = devices[0]
            if primary is not None:
                break
            await asyncio.sleep(0.5)
        if primary is None:
            return "Shelly device is not in the device registry yet"
        kwargs: dict[str, Any] = {}
        if name:
            kwargs["name_by_user"] = name
        if room:
            area_reg = ar.async_get(self.hass)
            area = area_reg.async_get_area_by_name(room)
            if area is None:
                area = area_reg.async_create(room)
            kwargs["area_id"] = area.id
        dev_reg.async_update_device(primary.id, **kwargs)
        return f"Home Assistant name/area updated ({room})" if room or name else ""

    async def secure_devices(self, **selectors: Any) -> list[dict[str, Any]]:
        """Apply the secure profile and read each checklist item back."""
        overrides = {key: selectors[key] for key in selectors if key in {
            "rotate_password",
            "disable_cloud",
            "disable_ap",
            "disable_ble_rpc",
            "disable_mqtt",
            "disable_ws",
            "disable_debug",
            "firmware_manual",
            "restrict_web_ui",
        }}
        profile = secure_profile_from(self.entry.options, overrides)
        password = str(self.entry.data.get(CONF_FLEET_PASSWORD) or "")
        if profile.rotate_password and not password:
            raise ServiceValidationError(
                "Set the device password in the Shelly Bulk options before securing devices"
            )
        entries = self._select_shelly_entries(
            device_ids=selectors.get("device_ids") or set(),
            area_ids=selectors.get("area_ids") or set(),
            mac=selectors.get("mac"),
            all_shelly=bool(selectors.get("all_shelly")),
            model_contains=selectors.get("model_contains"),
        )
        if not entries:
            raise ServiceValidationError("No core Shelly devices matched")
        reports = []
        for entry in entries:
            reports.append(await self._secure_one(entry, profile, password))
        self.last_audit = reports
        self.notify()
        return reports

    async def audit_devices(self, **selectors: Any) -> list[dict[str, Any]]:
        """Read security state without changing devices."""
        profile = secure_profile_from(self.entry.options, None)
        entries = self._select_shelly_entries(
            device_ids=selectors.get("device_ids") or set(),
            area_ids=selectors.get("area_ids") or set(),
            mac=selectors.get("mac"),
            all_shelly=bool(selectors.get("all_shelly")) or not any(
                (selectors.get("device_ids"), selectors.get("area_ids"), selectors.get("mac"))
            ),
            model_contains=selectors.get("model_contains"),
        )
        if not entries:
            raise ServiceValidationError("No core Shelly devices matched")
        reports = []
        for entry in entries:
            reports.append(await self._audit_one(entry, profile))
        self.last_audit = reports
        self.notify()
        return reports

    async def set_advanced(self, settings: dict[str, Any], **selectors: Any) -> list[dict[str, Any]]:
        """Apply advanced settings and return the read-back for each device."""
        if not settings:
            raise ServiceValidationError("Choose at least one advanced setting")
        entries = self._select_shelly_entries(
            device_ids=selectors.get("device_ids") or set(),
            area_ids=selectors.get("area_ids") or set(),
            mac=selectors.get("mac"),
            all_shelly=bool(selectors.get("all_shelly")),
            model_contains=selectors.get("model_contains"),
        )
        if not entries:
            raise ServiceValidationError("No core Shelly devices matched")
        channel = int(selectors.get("channel") or 0)
        reports = []
        for entry in entries:
            reports.append(await self._advanced_one(entry, settings, channel))
        return reports

    async def read_device_setting(self, entry: ConfigEntry, key: str, channel: int = 0) -> Any:
        if key == "scanner_mode":
            return str(entry.options.get(CONF_BLE_SCANNER_MODE) or "disabled")
        session = await self._open_shelly(entry)
        try:
            return await read_setting(session, key, channel=channel)
        finally:
            await session.shutdown()

    async def write_device_setting(self, entry: ConfigEntry, key: str, value: Any, channel: int = 0) -> Any:
        if key == "scanner_mode":
            mode = str(value)
            if not scanner_mode_valid(mode):
                raise ServiceValidationError(f"Scanner mode must be one of {', '.join(BLE_SCANNER_MODES)}")
            options = dict(entry.options)
            options[CONF_BLE_SCANNER_MODE] = mode
            self.hass.config_entries.async_update_entry(entry, options=options)
            updated = self.hass.config_entries.async_get_entry(entry.entry_id) or entry
            return str(updated.options.get(CONF_BLE_SCANNER_MODE) or mode)
        session = await self._open_shelly(entry)
        try:
            read_back, note = await write_setting(session, key, value, channel=channel)
        finally:
            await session.shutdown()
        if note:
            raise ServiceValidationError(note)
        return read_back

    async def _open_shelly(self, entry: ConfigEntry):
        host = entry.data.get(CONF_HOST)
        if not host:
            raise ServiceValidationError("The Shelly entry has no host")
        username = entry.data.get(CONF_USERNAME) or None
        password = entry.data.get(CONF_PASSWORD) or None
        if username and not password:
            username = None
        return await self._connect_with_retries(
            host,
            int(entry.data.get(CONF_PORT) or 80),
            username,
            password,
            bool(entry.data.get(CONF_VERIFY_SSL, False)),
        )

    async def _secure_one(self, entry: ConfigEntry, profile, password: str) -> dict[str, Any]:
        mac = entry.unique_id or entry.entry_id
        notes: list[str] = []
        session = None
        try:
            session = await self._open_shelly(entry)
            if int((session.shelly or {}).get("gen") or 0) == 1:
                return self._audit_row(mac, {"ok": False, "issues": ["Gen1 devices are not supported"]}, notes)
            auth_set = await apply_secure_profile(session, profile, password, notes, self.redact)
            if auth_set:
                params = build_set_auth(str(session.shelly.get("id") or "device"), password)
                self._extra_secrets.add(password)
                self._extra_secrets.add(params["ha1"])
            await session.shutdown()
            session = None
            reconnected = True
            if auth_set:
                self._store_shelly_password(entry, password)
                try:
                    session = await self._connect_with_retries(
                        entry.data.get(CONF_HOST),
                        int(entry.data.get(CONF_PORT) or 80),
                        "admin",
                        password,
                        bool(entry.data.get(CONF_VERIFY_SSL, False)),
                    )
                except Exception as err:  # noqa: BLE001
                    reconnected = False
                    notes.append(f"Reconnect failed: {self.redact(str(err))}")
            if session is None and reconnected:
                session = await self._open_shelly(entry)
            state = await read_security_state(session, notes, self.redact) if session is not None else {"shelly": {}}
            report = evaluate_security(state, profile, reconnected)
            report["mac"] = display_mac(mac) if _is_mac(str(mac)) else str(mac)
            report["notes"] = notes
            self.record(
                mac,
                "secured" if report["ok"] else "not_secure",
                "; ".join(report["issues"]),
                notes=notes,
            )
            return report
        except Exception as err:  # noqa: BLE001
            message = self.redact(str(err))
            self.record(mac, "failed", message, notes=notes)
            return self._audit_row(mac, {"ok": False, "issues": [message], "reconnected": False}, notes)
        finally:
            if session is not None:
                await session.shutdown()

    async def _audit_one(self, entry: ConfigEntry, profile) -> dict[str, Any]:
        mac = entry.unique_id or entry.entry_id
        notes: list[str] = []
        session = None
        try:
            session = await self._open_shelly(entry)
            state = await read_security_state(session, notes, self.redact)
            report = evaluate_security(state, profile, True)
            report["mac"] = display_mac(mac) if _is_mac(str(mac)) else str(mac)
            report["notes"] = notes
            return report
        except Exception as err:  # noqa: BLE001
            return self._audit_row(mac, {"ok": False, "issues": [self.redact(str(err))], "reconnected": False}, notes)
        finally:
            if session is not None:
                await session.shutdown()

    async def _advanced_one(self, entry: ConfigEntry, settings: dict[str, Any], channel: int) -> dict[str, Any]:
        mac = entry.unique_id or entry.entry_id
        read_back: dict[str, Any] = {}
        notes: list[str] = []
        for key, value in settings.items():
            if value is None:
                continue
            try:
                read_back[key] = await self.write_device_setting(entry, key, value, channel)
            except Exception as err:  # noqa: BLE001
                notes.append(f"{key}: {self.redact(str(err))}")
                read_back[key] = None
        return {
            "mac": display_mac(mac) if _is_mac(str(mac)) else str(mac),
            "read_back": read_back,
            "notes": notes,
            "ok": not notes,
        }

    def _store_shelly_password(self, entry: ConfigEntry, password: str) -> None:
        data = dict(entry.data)
        data[CONF_USERNAME] = "admin"
        data[CONF_PASSWORD] = password
        self.hass.config_entries.async_update_entry(entry, data=data)

    def _audit_row(self, mac: str, report: dict[str, Any], notes: list[str]) -> dict[str, Any]:
        report.setdefault("issues", [])
        report["mac"] = display_mac(mac) if _is_mac(str(mac)) else str(mac)
        report["notes"] = notes
        report.setdefault("ok", False)
        return report

    async def _wait_settled(self, entry: ConfigEntry) -> None:
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            if entry.state in {ConfigEntryState.LOADED, ConfigEntryState.SETUP_ERROR}:
                return
            await asyncio.sleep(0.5)


def _mac_key(value: str) -> str:
    try:
        return normalize_mac(value)
    except ValueError:
        return value.replace(":", "").upper()


def _is_mac(value: str) -> bool:
    try:
        normalize_mac(value)
    except ValueError:
        return False
    return True


def integration_version() -> str:
    return VERSION
