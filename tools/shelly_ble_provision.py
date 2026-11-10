#!/usr/bin/env python3
"""Optional workshop tool for pre-staging Shelly devices without the integration.

UNTESTED ON REAL HARDWARE. Prefer the Shelly Fleet integration when Home
Assistant can hear the devices. This script is for a bench laptop or Pi that
is not on the site instance.

Commands
  scan        Passive BLE scan. Never connects.
  provision   Push Wi-Fi and optional settings over BLE RPC.
  ha-ble      Answer Home Assistant's own Shelly Bluetooth flows (HA >= 2025.12).
  ha-add      Add devices that are already on Wi-Fi, by IP.

Secrets come from the environment or a hidden prompt, never from argv:
  SHELLY_WIFI_SSID, SHELLY_WIFI_PASS, SHELLY_ADMIN_PASS, HA_TOKEN, SHELLY_TZ

There is no default timezone and no bundled device list. Pass --csv yourself.
A CSV needs a header row: mac,name,room

Current Home Assistant disables the device access point and Bluetooth RPC
itself after ha-ble provisioning. This script's confirm step therefore sends
an empty form. Re-enable Bluetooth RPC afterwards if you still need it.

Requires Python 3.11+. Provisioning uses aioshelly when it is installed
(pip install aioshelly bleak). The built-in GATT client is a fallback and is
the untested path.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import hashlib
import json
import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RPC_SERVICE_UUID = "5f6d4f53-5f52-5043-5f53-56435f49445f"
DATA_UUID = "5f6d4f53-5f52-5043-5f64-6174615f5f5f"
TX_CTL_UUID = "5f6d4f53-5f52-5043-5f74-785f63746c5f"
RX_CTL_UUID = "5f6d4f53-5f52-5043-5f72-785f63746c5f"
ALLTERCO_MFID = 0x0BA9
FLAG_AUTH_ENABLED = 1 << 1
FLAG_RPC_OVER_BLE = 1 << 2


def norm_mac(mac: str) -> str:
    compact = "".join(char for char in mac.upper() if char in "0123456789ABCDEF")
    if len(compact) != 12:
        raise ValueError(f"bad MAC: {mac!r}")
    return compact


def secret(env: str, prompt: str, required: bool = True) -> str | None:
    value = os.environ.get(env)
    if value:
        return value
    if not sys.stdin.isatty():
        if required:
            sys.exit(f"{env} is not set and there is no TTY to prompt")
        return None
    value = getpass.getpass(f"{prompt} ({env}): ")
    if required and not value:
        sys.exit(f"{env} is required")
    return value or None


def parse_mfr(manufacturer_data: dict[int, bytes]) -> dict[str, Any] | None:
    data = manufacturer_data.get(ALLTERCO_MFID)
    if not data:
        return None
    parsed: dict[str, Any] = {}
    index = 0
    while index < len(data):
        block = data[index]
        index += 1
        if block == 0x01 and index + 2 <= len(data):
            parsed["flags"] = int.from_bytes(data[index : index + 2], "little")
            index += 2
        elif block == 0x0A and index + 6 <= len(data):
            parsed["mac"] = "".join(f"{byte:02X}" for byte in reversed(data[index : index + 6]))
            index += 6
        elif block == 0x0B and index + 2 <= len(data):
            parsed["model_id"] = int.from_bytes(data[index : index + 2], "little")
            index += 2
        else:
            break
    return parsed or None


def load_csv(path: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            row = {key.strip().lower(): (value or "").strip() for key, value in raw.items() if key}
            if row.get("mac"):
                rows[norm_mac(row["mac"])] = row
    return rows


def build_plan(args: argparse.Namespace, row: dict[str, str], ssid: str, admin: bool) -> list[tuple[str, dict | None]]:
    """RPC plan for --dry-run. Passwords are masked."""
    plan: list[tuple[str, dict | None]] = [("Shelly.GetDeviceInfo", None)]
    sys_config: dict[str, Any] = {}
    if row.get("name"):
        sys_config["device"] = {"name": row["name"]}
    if getattr(args, "tz", ""):
        sys_config["location"] = {"tz": args.tz}
    if sys_config:
        plan.append(("Sys.SetConfig", {"config": sys_config}))
    if args.disable_cloud:
        plan.append(("Cloud.SetConfig", {"config": {"enable": False}}))
    wifi: dict[str, Any] = {"sta": {"ssid": ssid, "pass": "***", "enable": True}}
    if args.disable_ap:
        wifi["ap"] = {"enable": False}
    plan.append(("WiFi.SetConfig", {"config": wifi}))
    plan.append(("WiFi.GetStatus", None))
    if admin:
        plan.append(("Shelly.SetAuth", {"user": "admin", "realm": "<device id>", "ha1": "***"}))
    elif args.disable_ble_rpc:
        plan.append(("BLE.SetConfig", {"config": {"enable": True, "rpc": {"enable": False}}}))
    return plan


class ShellyBleRpc:
    """Minimal GATT client. Untested. Prefer aioshelly when it imports."""

    def __init__(self, ble_device: Any) -> None:
        self.dev = ble_device
        self.client: Any = None
        self._id = 0

    async def __aenter__(self) -> ShellyBleRpc:
        from bleak import BleakClient

        try:
            from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

            self.client = await establish_connection(
                BleakClientWithServiceCache, self.dev, self.dev.address
            )
        except ImportError:
            self.client = BleakClient(self.dev, timeout=20)
            await self.client.connect()
        if not self.client.services.get_service(RPC_SERVICE_UUID):
            await self.client.disconnect()
            raise RuntimeError("Shelly RPC service not found. The setup window may be closed.")
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def call(self, method: str, params: dict | None = None, timeout: float = 15) -> Any:
        self._id += 1
        request: dict[str, Any] = {"id": self._id, "src": "shelly-fleet", "method": method}
        if params is not None:
            request["params"] = params
        raw = json.dumps(request, separators=(",", ":")).encode()
        client = self.client
        await asyncio.wait_for(
            client.write_gatt_char(TX_CTL_UUID, struct.pack(">I", len(raw)), response=True), timeout
        )
        await asyncio.wait_for(client.write_gatt_char(DATA_UUID, raw, response=True), timeout)
        length = 0
        for _ in range(int(timeout / 0.1)):
            block = await client.read_gatt_char(RX_CTL_UUID)
            if len(block) >= 4 and (length := struct.unpack(">I", bytes(block[:4]))[0]):
                break
            await asyncio.sleep(0.1)
        if not length:
            raise TimeoutError(f"{method}: no response")
        buffer = bytearray()
        while len(buffer) < length:
            chunk = await client.read_gatt_char(DATA_UUID)
            if not chunk:
                break
            buffer.extend(chunk)
        response = json.loads(bytes(buffer))
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        return response.get("result")


@dataclass
class Seen:
    ble_device: Any
    name: str
    rssi: int
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def mac(self) -> str | None:
        return self.info.get("mac")

    def flag(self, bit: int) -> bool:
        return bool(self.info.get("flags", 0) & bit)


async def ble_scan(seconds: float, min_rssi: int) -> dict[str, Seen]:
    from bleak import BleakScanner

    found: dict[str, Seen] = {}

    def _callback(device: Any, adv: Any) -> None:
        info = parse_mfr(adv.manufacturer_data or {})
        name = adv.local_name or device.name or ""
        if not info and not name.lower().startswith("shelly"):
            return
        if adv.rssi is not None and adv.rssi < min_rssi:
            return
        key = (info or {}).get("mac") or device.address
        found[key] = Seen(device, name, adv.rssi or -999, info or {})

    async with BleakScanner(detection_callback=_callback):
        await asyncio.sleep(seconds)
    return found


async def cmd_scan(args: argparse.Namespace) -> None:
    found = await ble_scan(args.seconds, args.min_rssi)
    wanted = load_csv(args.csv) if args.csv else {}
    rows = []
    for seen in sorted(found.values(), key=lambda item: -item.rssi):
        mac = seen.mac or ""
        rows.append(
            {
                "mac": mac,
                "ble_addr": seen.ble_device.address,
                "local_name": seen.name,
                "rssi": seen.rssi,
                "rpc_over_ble": seen.flag(FLAG_RPC_OVER_BLE),
                "auth_enabled": seen.flag(FLAG_AUTH_ENABLED),
                "in_csv": (mac in wanted) if wanted else "",
                "csv_name": wanted.get(mac, {}).get("name", ""),
            }
        )
    print(f"{len(rows)} Shelly advertisements. rpc_over_ble means the setup window is open.")
    if wanted:
        missing = sorted(set(wanted) - {row["mac"] for row in rows})
        print(f"CSV devices not heard: {len(missing)}")
    if args.out and rows:
        with open(args.out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


async def _provision_aioshelly(seen: Seen, row: dict[str, str], args, ssid: str, wifi_password: str, admin: str | None) -> dict[str, Any]:
    from aioshelly.common import ConnectionOptions
    from aioshelly.rpc_device import RpcDevice

    report: dict[str, Any] = {
        "mac": seen.mac,
        "name": row.get("name", ""),
        "room": row.get("room", ""),
        "status": "fail",
        "ip": "",
        "error": "",
    }
    device = await RpcDevice.create(None, None, ConnectionOptions(ble_device=seen.ble_device))
    try:
        await device.initialize()
        info = device.shelly
        report.update(model=info.get("model"), fw=info.get("ver"), gen=info.get("gen"))
        if info.get("auth_en"):
            raise RuntimeError("auth already enabled; skipped")
        if info.get("provision") in {"complete", "locked"}:
            raise RuntimeError(f"provision={info.get('provision')}: power-cycle the device")
        sys_config: dict[str, Any] = {}
        if row.get("name"):
            sys_config["device"] = {"name": row["name"]}
        if args.tz:
            sys_config["location"] = {"tz": args.tz}
        if sys_config:
            await device.call_rpc("Sys.SetConfig", {"config": sys_config})
        if args.disable_cloud:
            await device.call_rpc("Cloud.SetConfig", {"config": {"enable": False}})
        await device.wifi_setconfig(sta_ssid=ssid, sta_password=wifi_password, sta_enable=True, ap_enable=False if args.disable_ap else None)
        deadline = asyncio.get_running_loop().time() + args.wifi_timeout
        while asyncio.get_running_loop().time() < deadline:
            status = await device.call_rpc("WiFi.GetStatus")
            if status and status.get("status") == "got ip" and status.get("sta_ip"):
                report["ip"] = status["sta_ip"]
                break
            await asyncio.sleep(2)
        if not report["ip"]:
            raise RuntimeError("no IP. Check the SSID, 2.4 GHz, and DHCP")
        if admin:
            device_id = info["id"]
            digest = hashlib.sha256(f"admin:{device_id}:{admin}".encode()).hexdigest()
            await device.call_rpc("Shelly.SetAuth", {"user": "admin", "realm": device_id, "ha1": digest})
        elif args.disable_ble_rpc:
            await device.ble_setconfig(enable=True, enable_rpc=False)
        report["status"] = "ok"
    except Exception as err:  # noqa: BLE001
        report["error"] = str(err)[:300]
    finally:
        await device.shutdown()
    return report


async def cmd_provision(args: argparse.Namespace) -> None:
    wanted = load_csv(args.csv)
    ssid = os.environ.get("SHELLY_WIFI_SSID", "<SSID>") if args.dry_run else secret("SHELLY_WIFI_SSID", "Wi-Fi SSID")
    if args.dry_run:
        print("Dry run. No Bluetooth connections.")
        for mac, row in wanted.items():
            print(mac, row.get("name", ""))
            for method, params in build_plan(args, row, ssid or "<SSID>", args.set_auth):
                print("  ", method, json.dumps(params) if params else "")
        return
    assert ssid is not None
    wifi_password = secret("SHELLY_WIFI_PASS", "Wi-Fi password")
    admin = secret("SHELLY_ADMIN_PASS", "Shelly admin password", required=False) if args.set_auth else None
    found = await ble_scan(args.seconds, args.min_rssi)
    todo = [(seen, wanted[seen.mac]) for seen in found.values() if seen.mac in wanted and seen.flag(FLAG_RPC_OVER_BLE)]
    print(f"{len(todo)} devices in the CSV have Bluetooth RPC open")
    if not args.yes and input(f"Provision {len(todo)} devices onto the configured SSID? Type YES: ") != "YES":
        sys.exit("aborted")
    semaphore = asyncio.Semaphore(args.concurrency)

    async def _one(seen: Seen, row: dict[str, str]) -> dict[str, Any]:
        async with semaphore:
            try:
                return await _provision_aioshelly(seen, row, args, ssid, wifi_password or "", admin)
            except ImportError:
                print("aioshelly is not installed; the fallback GATT client is untested", file=sys.stderr)
                return {"mac": seen.mac, "status": "fail", "error": "aioshelly is not installed"}

    reports = list(await asyncio.gather(*(_one(seen, row) for seen, row in todo)))
    heard = {seen.mac for seen in found.values()}
    for mac, row in wanted.items():
        if mac not in heard:
            reports.append({"mac": mac, "name": row.get("name", ""), "status": "not_heard", "error": "no advertisement"})
    path = Path(args.report)
    keys = sorted({key for row in reports for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(reports)
    print(f"Report written to {path}")


class HA:
    def __init__(self, url: str, token: str, verify_ssl: bool = True) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.verify = verify_ssl
        self.ws: Any = None
        self.sess: Any = None
        self._id = 0

    async def __aenter__(self) -> HA:
        import aiohttp

        self.sess = aiohttp.ClientSession(headers={"Authorization": f"Bearer {self.token}"})
        ws_url = self.url.replace("http", "ws", 1) + "/api/websocket"
        self.ws = await self.sess.ws_connect(ws_url, ssl=None if self.verify else False)
        await self.ws.receive_json()
        await self.ws.send_json({"type": "auth", "access_token": self.token})
        if (await self.ws.receive_json()).get("type") != "auth_ok":
            raise SystemExit("Home Assistant authentication failed")
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.ws.close()
        await self.sess.close()

    async def wsc(self, message_type: str, **kwargs: Any) -> Any:
        self._id += 1
        await self.ws.send_json({"id": self._id, "type": message_type, **kwargs})
        while True:
            message = await self.ws.receive_json()
            if message.get("id") == self._id and message.get("type") == "result":
                if not message.get("success"):
                    raise RuntimeError(f"{message_type}: {message.get('error')}")
                return message.get("result")

    async def post(self, path: str, body: dict) -> dict:
        async with self.sess.post(self.url + path, json=body, ssl=None if self.verify else False) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"POST {path} -> {response.status}")
            return json.loads(text)


async def cmd_ha_ble(args: argparse.Namespace) -> None:
    """Answer Shelly Bluetooth flows. Home Assistant does the GATT work."""
    token = secret("HA_TOKEN", "Home Assistant token")
    ssid = secret("SHELLY_WIFI_SSID", "Wi-Fi SSID")
    wifi_password = None if args.dry_run else secret("SHELLY_WIFI_PASS", "Wi-Fi password")
    wanted = load_csv(args.csv) if args.csv else {}
    assert token and ssid
    async with HA(args.ha_url, token, not args.insecure) as ha:
        flows = await ha.wsc("config_entries/flow/progress")
        pending = [
            flow
            for flow in flows
            if flow.get("handler") == "shelly" and (flow.get("context") or {}).get("source") == "bluetooth"
        ]
        if wanted:
            pending = [
                flow
                for flow in pending
                if norm_mac(str((flow.get("context") or {}).get("unique_id") or "000000000000")) in wanted
            ]
        print(f"{len(pending)} Shelly Bluetooth flows")
        if args.dry_run or not pending:
            return
        for flow in pending:
            flow_id = flow["flow_id"]
            unique_id = str((flow.get("context") or {}).get("unique_id") or "")
            try:
                result = await ha.post(f"/api/config/config_entries/flow/{flow_id}", {})
                if result.get("step_id") == "wifi_scan":
                    result = await ha.post(
                        f"/api/config/config_entries/flow/{flow_id}",
                        {"ssid": ssid, "password": wifi_password},
                    )
                print(unique_id, result.get("type"), result.get("step_id", ""))
            except Exception as err:  # noqa: BLE001
                print(unique_id, "ERROR", err)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="cmd", required=True)

    scan = commands.add_parser("scan")
    scan.add_argument("--seconds", type=float, default=15)
    scan.add_argument("--min-rssi", type=int, default=-90)
    scan.add_argument("--csv")
    scan.add_argument("--out")

    provision = commands.add_parser("provision")
    provision.add_argument("--csv", required=True)
    provision.add_argument("--seconds", type=float, default=15)
    provision.add_argument("--min-rssi", type=int, default=-85)
    provision.add_argument("--concurrency", type=int, default=3)
    provision.add_argument("--wifi-timeout", type=float, default=40)
    provision.add_argument("--tz", default=os.environ.get("SHELLY_TZ", ""))
    provision.add_argument("--disable-cloud", action="store_true")
    provision.add_argument("--disable-ap", action="store_true")
    provision.add_argument("--disable-ble-rpc", action="store_true")
    provision.add_argument("--set-auth", action="store_true")
    provision.add_argument("--report", default="provision_report.csv")
    provision.add_argument("--dry-run", action="store_true")
    provision.add_argument("--yes", action="store_true")

    ha_ble = commands.add_parser("ha-ble")
    ha_ble.add_argument("--ha-url", required=True)
    ha_ble.add_argument("--csv")
    ha_ble.add_argument("--insecure", action="store_true")
    ha_ble.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    handler = {"scan": cmd_scan, "provision": cmd_provision, "ha-ble": cmd_ha_ble}[args.cmd]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
