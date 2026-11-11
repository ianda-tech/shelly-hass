"""Drive Home Assistant's own Shelly Bluetooth provisioning flows.

Core (verified against home-assistant/core dev in November 2026) creates one
flow per factory-new Gen2+ device whose advertisement has RPC-over-BLE set.
The confirm step takes an empty submission. The Wi-Fi step takes ``ssid`` and
``password`` together. Provisioning then shows progress while the device joins
the network. After success, core disables the open AP and BLE RPC itself.
This module only answers those steps. It does not open its own GATT session.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import UnknownFlow

from .ble import auth_enabled, parse_shelly_manufacturer_data, rpc_over_ble_enabled
from .discover import model_hint_from
from .const import (
    CONF_CONCURRENCY,
    CONF_RETRIES,
    CONF_WIFI_PASSWORD,
    CONF_WIFI_SSID,
    DOMAIN,
    ENTRY_WAIT_SECONDS,
    POLL_INTERVAL_SECONDS,
    PROVISION_WAIT_SECONDS,
    SHELLY_DOMAIN,
    SOURCE_BLUETOOTH,
    STEP_BLUETOOTH_CONFIRM,
    STEP_CREDENTIALS,
    STEP_DO_PROVISION,
    STEP_PROVISION_DONE,
    STEP_PROVISION_FAILED,
    STEP_WIFI_SCAN,
    STEP_WIFI_SCAN_FAILED,
)
from .util import display_mac, normalize_mac

_LOGGER = logging.getLogger(__name__)

_PROGRESS_STEPS = {STEP_DO_PROVISION, STEP_PROVISION_DONE}
_RETRY_STEPS = {STEP_PROVISION_FAILED, STEP_WIFI_SCAN_FAILED}
POWER_CYCLE_HINT = (
    "The device is advertising without Bluetooth RPC. "
    "Power-cycle it to reopen the setup window."
)


class Provisioner:
    """Adopt discovered Shelly flows while provisioning mode is armed."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.active = False
        self.deadline: float | None = None
        self._continuous = False
        self._hints: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._sem = asyncio.Semaphore(2)
        self._inflight: set[str] = set()
        self._done: set[str] = set()
        self._flows_tried: set[str] = set()
        self._flow_mac: dict[str, str] = {}
        self._auth_macs: set[str] = set()
        self._warned: set[str] = set()
        self._rpc_off: set[str] = set()
        self._unsub = None

    @property
    def hass(self) -> HomeAssistant:
        return self.runtime.hass

    @property
    def pending(self) -> int:
        return len(self._inflight)

    def _now(self) -> float:
        return time.monotonic()

    @property
    def timed_running(self) -> bool:
        """True only during the timed provisioning window, not auto-adopt."""
        return bool(self.active and self.deadline is not None and self._now() < self.deadline)

    def _session_open(self) -> bool:
        timed = self.deadline is not None and self._now() < self.deadline
        return bool(self._continuous or timed)

    async def start(self, minutes: float | None = None, *, continuous: bool = False) -> None:
        """Arm adoption. ``minutes`` is the timed window. ``continuous`` is auto-adopt."""
        self.active = True
        if continuous:
            self._continuous = True
        if minutes is not None:
            self.deadline = self._now() + float(minutes) * 60
        concurrency = int(self.runtime.entry.options.get(CONF_CONCURRENCY, 2) or 2)
        self._sem = asyncio.Semaphore(max(1, min(concurrency, 5)))
        self._register_bluetooth()
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_background_task(
                self._run(), name="shelly_bulk_provision"
            )
        self.runtime.notify()
        _LOGGER.info(
            "Provisioning %s (allowlist %s)",
            "auto-adopt" if continuous and minutes is None else f"on for {minutes} minutes",
            "required" if self.runtime.require_allowlist else "optional",
        )

    async def stop(self, reason: str = "stopped") -> None:
        """Disarm adoption and cancel in-flight waits."""
        self.active = False
        self._continuous = False
        self.deadline = None
        self._unregister_bluetooth()
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._inflight.clear()
        self.runtime.notify()
        _LOGGER.info("Provisioning mode off (%s)", reason)

    async def stop_timed(self) -> None:
        """End the timed window. Auto-adopt keeps running when it is on."""
        self.deadline = None
        if self._continuous and self.active:
            self.runtime.notify()
            return
        await self.stop("stopped")

    async def stop_continuous(self) -> None:
        """Stop auto-adopt. A timed provisioning window keeps running."""
        self._continuous = False
        if self.timed_running:
            self.runtime.notify()
            return
        await self.stop("auto-adopt off")

    async def _run(self) -> None:
        try:
            while self.active and self._session_open():
                if self.deadline is not None and self._now() >= self.deadline:
                    self.deadline = None
                    self.runtime.notify()
                    if not self._continuous:
                        break
                await self.scan_once()
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            self.runtime.set_last_error(f"Provisioning stopped: {self.runtime.redact(str(err))}")
            _LOGGER.exception("Provisioning loop failed")
        finally:
            now = self._now()
            timed_out = (
                self.active
                and not self._continuous
                and self.deadline is not None
                and now >= self.deadline
            )
            self.active = False
            self._continuous = False
            self.deadline = None
            self._unregister_bluetooth()
            self.runtime.notify()
            if timed_out:
                _LOGGER.info("Provisioning mode reached its time limit")

    async def scan_once(self) -> None:
        """Pick up Shelly Bluetooth flows that are waiting for input."""
        if not self.active:
            return
        if self.runtime.require_allowlist and not self.runtime.allowlist.devices:
            self.runtime.set_last_error(
                "Provisioning is armed but the device list is empty. "
                "Edit shelly_bulk/devices.csv, or turn off "
                "'only provision the allowlist'. While that option is on, auto-adopt "
                "does not take devices that are not on the list."
            )
            return
        try:
            flows = self.hass.config_entries.flow.async_progress()
        except Exception as err:  # noqa: BLE001
            self.runtime.set_last_error(self.runtime.redact(str(err)))
            return
        for flow in flows:
            if flow.get("handler") != SHELLY_DOMAIN:
                continue
            context = flow.get("context") or {}
            if context.get("source") != SOURCE_BLUETOOTH:
                continue
            flow_id = flow.get("flow_id")
            unique_id = context.get("unique_id")
            if not flow_id or not unique_id or flow_id in self._flows_tried:
                continue
            try:
                mac = normalize_mac(str(unique_id))
            except ValueError:
                continue
            if mac in self._done or mac in self._inflight:
                continue
            if mac in self._auth_macs:
                self._done.add(mac)
                self.runtime.record(
                    mac,
                    "skipped_auth",
                    "Advertisement says authentication is already enabled. The device was not changed.",
                )
                continue
            if self.runtime.require_allowlist and mac not in self.runtime.allowlist:
                continue
            if self.runtime.shelly_entry_for(mac) is not None:
                self._done.add(mac)
                continue
            self._inflight.add(mac)
            self.runtime.notify()
            self.hass.async_create_task(self._guarded(flow_id, mac), eager_start=True)

    async def _guarded(self, flow_id: str, mac: str) -> None:
        try:
            async with self._sem:
                if self.active:
                    await self.drive(flow_id, mac)
        finally:
            self._inflight.discard(mac)
            self._flows_tried.add(flow_id)
            self._flow_mac[flow_id] = mac
            self.runtime.notify()

    async def drive(self, flow_id: str, mac: str) -> None:
        """Answer one Shelly Bluetooth flow, then hand the new entry to the runtime."""
        retries = int(self.runtime.entry.options.get(CONF_RETRIES, 1) or 0)
        attempts = 0
        max_attempts = retries + 1
        initial = self._step(flow_id) or STEP_BLUETOOTH_CONFIRM
        if initial == STEP_CREDENTIALS:
            await self._abort_auth(flow_id, mac)
            return
        pending: dict[str, Any] | None = self._input_for_step(initial)
        if pending is None:
            self.runtime.record(mac, "failed", f"Unhandled Shelly flow step {initial}")
            return
        last_step = None
        entered = False
        while attempts < max_attempts and pending is not None and self.active:
            entered = True
            try:
                result = await self.hass.config_entries.flow.async_configure(flow_id, pending)
            except UnknownFlow:
                break
            except Exception as err:  # noqa: BLE001
                self.runtime.record(mac, "failed", f"Config flow error: {self.runtime.redact(str(err))}")
                return
            result_type = str(result.get("type") or "")
            step = result.get("step_id")
            if result_type in {"create_entry", "abort"}:
                if result_type == "abort" and result.get("reason") not in (None, "already_configured"):
                    self.runtime.record(
                        mac,
                        "failed",
                        self._abort_message(str(result.get("reason") or "aborted")),
                    )
                    return
                break
            if step == STEP_CREDENTIALS:
                await self._abort_auth(flow_id, mac)
                return
            if result_type in {"progress", "progress_done"} or step in _PROGRESS_STEPS:
                progressed = await self._wait_until_step_changes(flow_id)
                if progressed is None:
                    break
                step = progressed.get("step_id")
                if step == "timeout":
                    self.runtime.record(
                        mac,
                        "failed",
                        "Timed out waiting for the device to join Wi-Fi. "
                        "Check that the SSID is 2.4 GHz, not WPA3-only, and that mDNS reaches Home Assistant.",
                    )
                    return
            if step == last_step and result_type == "form":
                attempts += 1
            last_step = step
            if step in _RETRY_STEPS:
                attempts += 1
            if step == STEP_CREDENTIALS:
                await self._abort_auth(flow_id, mac)
                return
            pending = self._input_for_step(step)
            if pending is None and step not in _PROGRESS_STEPS:
                self.runtime.record(mac, "failed", f"Unhandled Shelly flow step {step}")
                return
        else:
            if attempts >= max_attempts:
                self.runtime.record(
                    mac,
                    "failed",
                    "Provisioning failed after the configured retries.",
                )
                return
        if not entered:
            return
        if mac not in self.runtime.allowlist:
            try:
                await self.runtime.note_new_device(
                    mac, model_hint=self._hints.get(mac, ""), placeholder=True
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Could not record %s on the device list: %s", mac, err)
        await self.runtime.finish_adopted_device(mac)
        # A failed MAC can be tried again when a new discovery flow appears
        # (for example after a power cycle). A MAC that was adopted or skipped
        # because it already has a password is not touched again this session.
        last = self.runtime.results[-1] if self.runtime.results else {}
        if last.get("status") in {"ok", "skipped_auth"}:
            self._done.add(mac)

    def _input_for_step(self, step: str | None) -> dict[str, Any] | None:
        if step in {STEP_BLUETOOTH_CONFIRM, STEP_WIFI_SCAN_FAILED, STEP_PROVISION_FAILED, STEP_PROVISION_DONE}:
            return {}
        if step == STEP_WIFI_SCAN:
            data = self.runtime.entry.data
            return {
                "ssid": data[CONF_WIFI_SSID],
                "password": data[CONF_WIFI_PASSWORD],
            }
        if step in _PROGRESS_STEPS:
            return {}
        return None

    def _step(self, flow_id: str) -> str | None:
        for flow in self.hass.config_entries.flow.async_progress():
            if flow.get("flow_id") == flow_id:
                return flow.get("step_id")
        return None

    async def _wait_until_step_changes(self, flow_id: str) -> dict[str, str] | None:
        deadline = self._now() + PROVISION_WAIT_SECONDS
        while self._now() < deadline and self.active:
            step = self._step(flow_id)
            if step is None:
                return None
            if step != STEP_DO_PROVISION:
                return {"step_id": step}
            await asyncio.sleep(0.25)
        return {"step_id": "timeout"}

    async def _abort_auth(self, flow_id: str, mac: str) -> None:
        """Stop a flow that is asking for a password. Do not submit one."""
        await self._safe_abort(flow_id)
        self._done.add(mac)
        self.runtime.record(
            mac,
            "skipped_auth",
            "The device already asks for a password. The Shelly Installer device password was not sent.",
        )

    async def _safe_abort(self, flow_id: str) -> None:
        try:
            self.hass.config_entries.flow.async_abort(flow_id)
        except UnknownFlow:
            return
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not abort Shelly flow %s: %s", flow_id, self.runtime.redact(str(err)))

    def advertises_without_rpc(self, mac: str) -> bool:
        """Return True when this MAC has advertised with Bluetooth RPC off."""
        try:
            plain = normalize_mac(mac)
        except ValueError:
            return False
        return plain in self._rpc_off

    def failure_text(self, mac: str, message: str) -> str:
        """Add a power-cycle hint only when the device advertises without BLE RPC."""
        if not message or not self.advertises_without_rpc(mac):
            return message
        if "power-cycle" in message.lower():
            return message
        text = message.rstrip()
        joiner = " " if text.endswith(".") else ". "
        return f"{text}{joiner}{POWER_CYCLE_HINT}"

    def release_for_retry(self, macs: set[str]) -> None:
        """Forget failed MACs so the next advertisement can provision them again."""
        plain: set[str] = set()
        for mac in macs:
            try:
                plain.add(normalize_mac(mac))
            except ValueError:
                continue
        self._done -= plain
        self._warned -= plain
        self._inflight -= plain
        drop = {flow_id for flow_id, seen in self._flow_mac.items() if seen in plain}
        self._flows_tried -= drop
        for flow_id in drop:
            self._flow_mac.pop(flow_id, None)

    def note_advertisement(self, manufacturer_data: dict[int, bytes] | None, local_name: str = "") -> None:
        """Remember devices whose setup window is closed or that already have auth."""
        parsed = parse_shelly_manufacturer_data(manufacturer_data)
        if not parsed or "mac" not in parsed:
            return
        try:
            mac = normalize_mac(str(parsed["mac"]))
        except ValueError:
            return
        flags = int(parsed.get("flags") or 0)
        if auth_enabled(flags):
            self._auth_macs.add(mac)
        self._hints[mac] = model_hint_from(parsed.get("model_id"), local_name)
        if rpc_over_ble_enabled(flags):
            self._rpc_off.discard(mac)
        else:
            self._rpc_off.add(mac)
        if rpc_over_ble_enabled(flags) or mac in self._done:
            return
        if self.runtime.shelly_entry_for(mac) is not None:
            return
        if self.runtime.require_allowlist and mac not in self.runtime.allowlist:
            return
        if mac in self._warned:
            return
        self._warned.add(mac)
        self.runtime.flag_locked(mac, local_name)

    def _register_bluetooth(self) -> None:
        if self._unsub is not None:
            return
        try:
            from homeassistant.components import bluetooth
            from homeassistant.components.bluetooth import BluetoothScanningMode
        except ImportError:
            return
        if "bluetooth" not in self.hass.config.components:
            return

        @callback
        def _on_advert(service_info, _change) -> None:
            self.note_advertisement(
                getattr(service_info, "manufacturer_data", None),
                getattr(service_info, "name", "") or "",
            )
            if self.active:
                self.hass.async_create_task(self.scan_once(), eager_start=True)

        try:
            self._unsub = bluetooth.async_register_callback(
                self.hass,
                _on_advert,
                {"manufacturer_id": 0x0BA9},
                BluetoothScanningMode.PASSIVE,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Bluetooth advertisements will not be watched: %s", err)
            self._unsub = None

    def _unregister_bluetooth(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @staticmethod
    def _abort_message(reason: str) -> str:
        messages = {
            "ble_not_permitted": "The device refused Bluetooth setup.",
            "cannot_connect": (
                "Home Assistant could not open a Bluetooth connection. Shelly proxies "
                "only forward advertisements; the device still needs a connectable adapter "
                "or ESPHome proxy in range."
            ),
            "invalid_discovery_info": "Bluetooth RPC is not available.",
        }
        return messages.get(reason, f"Shelly discovery aborted ({reason}).")

    async def wait_for_entry(self, mac: str):
        """Poll for the core Shelly entry created by a finished flow."""
        deadline = self._now() + ENTRY_WAIT_SECONDS
        while self._now() < deadline:
            entry = self.runtime.shelly_entry_for(mac)
            if entry is not None:
                return entry
            await asyncio.sleep(0.5)
        return None
