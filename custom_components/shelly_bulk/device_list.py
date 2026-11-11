"""Create and append the user-owned device list under the config directory.

The file is created when missing and is never overwritten. Comment lines are
examples only. File I/O belongs in the executor; these functions are synchronous.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .allowlist import parse_allowlist_csv, without_csv_comments
from .const import DEVICE_LIST_RELATIVE
from .util import display_mac, normalize_mac

COLUMNS = (
    "mac",
    "name",
    "room",
    "model_hint",
    "input",
    "initial_state",
    "fade_rate",
    "transition",
)

# Comments are skipped by the parser. After that skip, a new file is a header
# and nothing else, so the first import is an empty list.
DEVICE_LIST_TEMPLATE = """# Shelly Installer device list. Created automatically. An existing file is never overwritten.
# Edit names and rooms with the File editor, Samba, or the Studio Code Server add-on, then press Reload device list.
# Lines starting with # are ignored. A header with no devices is an empty list, not an error.
# Columns: mac,name,room,model_hint,input,initial_state,fade_rate,transition
# Example only. This is not a real device. Delete the leading # to use the row:
# 00:00:00:00:00:01,Example light,Example room,,detached,restore_last,2,1.5
""" + ",".join(COLUMNS) + "\n"


def ensure_device_list(path: Path) -> bool:
    """Create the CSV if it is missing. Return True when this call created it."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError:
        return False
    with handle:
        handle.write(DEVICE_LIST_TEMPLATE)
    return True


def _cell(value: str) -> str:
    text = str(value or "")
    if any(char in text for char in ",\"\n"):
        return '"' + text.replace('"', '""') + '"'
    return text


def append_device_rows(path: Path, rows: list[dict[str, str]]) -> list[str]:
    """Append MACs that are not already in the file. Existing lines are not rewritten."""
    ensure_device_list(path)
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    parsed, _errors = parse_allowlist_csv(text)
    existing = set(parsed.devices)
    lines: list[str] = []
    added: list[str] = []
    for row in rows:
        mac = normalize_mac(row["mac"])
        if mac in existing:
            continue
        existing.add(mac)
        lines.append(
            ",".join(
                _cell(value)
                for value in (
                    display_mac(mac),
                    row.get("name") or "",
                    row.get("room") or "",
                    row.get("model_hint") or "",
                    row.get("input") or "",
                    row.get("initial_state") or "",
                    row.get("fade_rate") or "",
                    row.get("transition") or "",
                )
            )
        )
        added.append(mac)
    if not lines:
        return []
    prefix = "" if text.endswith("\n") or not text else "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + "\n".join(lines) + "\n")
    return added


def update_device_row(path: Path, mac: str, changes: dict[str, str]) -> bool:
    """Update one data row. Comment lines and other rows are kept. Returns False if the MAC is absent."""
    ensure_device_list(path)
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    comments = [line for line in text.splitlines() if line.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO(without_csv_comments(text)))
    fieldnames = list(reader.fieldnames or COLUMNS)
    for key in changes:
        if key not in fieldnames:
            fieldnames.append(key)
    target = normalize_mac(mac)
    rows: list[dict[str, str]] = []
    found = False
    for raw in reader:
        row = {name: (raw.get(name) or "") for name in fieldnames}
        try:
            matches = normalize_mac(row.get("mac") or "") == target
        except ValueError:
            matches = False
        if matches:
            found = True
            row["mac"] = display_mac(target)
            for key, value in changes.items():
                row[key] = "" if value is None else str(value)
        rows.append(row)
    if not found:
        return False
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    body = buffer.getvalue()
    prefix = ("\n".join(comments) + "\n") if comments else ""
    path.write_text(prefix + body, encoding="utf-8")
    return True


def placeholder_name(model_hint: str, mac: str) -> str:
    """Name used when auto-adopt adds a device the user has not named yet."""
    hint = (model_hint or "Shelly").strip() or "Shelly"
    return f"{hint} {normalize_mac(mac)[-4:]}"


__all__ = [
    "DEVICE_LIST_RELATIVE",
    "DEVICE_LIST_TEMPLATE",
    "append_device_rows",
    "ensure_device_list",
    "placeholder_name",
]
