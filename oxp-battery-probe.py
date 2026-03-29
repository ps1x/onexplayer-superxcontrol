#!/usr/bin/env python3
"""
Read confirmed battery-related fields from the OneXPlayer Super X EC memory region.

This helper is intentionally read-only. It does not write EC/WMI state.
"""

import argparse
import json
import mmap
import os
import sys
from pathlib import Path

EC_BASE = 0xFE800400
EC_SIZE = 0x100

FIELDS = (
    ("CHGR", 0x67, 2, "candidate charge-limit / charge-control field"),
    ("TBAT", 0x6A, 1, "battery temperature raw"),
    ("B1DC", 0x84, 2, "design capacity"),
    ("B1FV", 0x86, 2, "present voltage in mV"),
    ("B1FC", 0x88, 2, "full charge capacity"),
    ("B1ST", 0x8C, 1, "ACPI battery status bitmask"),
    ("B1CR", 0x8D, 2, "present charge/discharge rate"),
    ("B1RC", 0x8F, 2, "remaining capacity"),
    ("B1VT", 0x91, 2, "battery terminal voltage raw"),
    ("BPCN", 0x93, 1, "battery percentage"),
    ("CHLT", 0xA3, 1, "confirmed battery charge limit percent"),
    ("BPWM", 0xA4, 1, "confirmed bypass power mode value"),
    ("FCMN", 0xA5, 1, "confirmed force-charge-min threshold"),
    ("BALT", 0xEF, 1, "candidate bypass/battery-alternate mode"),
    ("PSMD", 0xFE, 1, "confirmed power supply mode enum"),
)

BATTERY_STATUS_FLAGS = {
    0x01: "discharging",
    0x02: "charging",
    0x04: "critical",
}

POWER_SUPPLY_MODE = {
    1: "OnlyBattery",
    2: "OnlyTypec100",
    3: "BatteryTypec100",
    4: "DCIn",
    5: "BatteryDCIn",
    8: "Typec65",
    9: "BatteryTypec65",
    500: "BatteryLow",
    501: "BatteryOverheat",
    1000: "Unknown",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read confirmed OneXPlayer Super X battery fields from EC system-memory region",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Include a full 0x100-byte hex dump of the EC battery region",
    )
    return parser.parse_args()


def read_bat0():
    battery = Path("/sys/class/power_supply/BAT0")
    if not battery.exists():
        return None

    values = {}
    for name in (
        "status",
        "capacity",
        "voltage_now",
        "energy_full",
        "energy_full_design",
        "energy_now",
        "power_now",
    ):
        path = battery / name
        if path.exists():
            values[name] = path.read_text(encoding="utf-8").strip()
    return values


def decode_battery_status(value):
    active = [name for bit, name in BATTERY_STATUS_FLAGS.items() if value & bit]
    return active or ["idle"]


def decode_power_supply_mode(value):
    name = POWER_SUPPLY_MODE.get(value)
    return [name] if name else ["unmapped"]


def read_region():
    page_size = os.sysconf("SC_PAGE_SIZE")
    page_base = EC_BASE & ~(page_size - 1)
    page_offset = EC_BASE - page_base

    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    try:
        region = mmap.mmap(
            fd,
            page_offset + EC_SIZE,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ,
            offset=page_base,
        )
        data = bytes(region[page_offset : page_offset + EC_SIZE])
    finally:
        os.close(fd)

    return data


def build_payload(include_dump: bool):
    raw = read_region()
    fields = []
    values = {}
    sysfs_bat0 = read_bat0()

    for name, offset, size, description in FIELDS:
        chunk = raw[offset : offset + size]
        value = int.from_bytes(chunk, "little")
        item = {
            "name": name,
            "offset": f"0x{offset:02X}",
            "address": f"0x{EC_BASE + offset:08X}",
            "size": size,
            "hex": chunk.hex(),
            "value": value,
            "description": description,
        }
        if name == "B1ST":
            item["decoded"] = decode_battery_status(value)
        elif name == "PSMD":
            item["decoded"] = decode_power_supply_mode(value)
        fields.append(item)
        values[name] = value

    payload = {
        "backend": {
            "type": "ec-system-memory",
            "path": "/dev/mem",
            "base": f"0x{EC_BASE:08X}",
            "size": f"0x{EC_SIZE:02X}",
            "write_support": False,
        },
        "sysfs_bat0": sysfs_bat0,
        "linux_battery_metrics": {
            "energy_full": (
                int(sysfs_bat0["energy_full"]) if sysfs_bat0 and sysfs_bat0.get("energy_full") else None
            ),
            "energy_full_design": (
                int(sysfs_bat0["energy_full_design"])
                if sysfs_bat0 and sysfs_bat0.get("energy_full_design")
                else None
            ),
            "health_percent": (
                round(
                    int(sysfs_bat0["energy_full"]) * 100.0 / int(sysfs_bat0["energy_full_design"]),
                    2,
                )
                if sysfs_bat0
                and sysfs_bat0.get("energy_full")
                and sysfs_bat0.get("energy_full_design")
                and int(sysfs_bat0["energy_full_design"]) > 0
                else None
            ),
        },
        "confirmed_matches": {
            "capacity_percent": {
                "ec_field": "BPCN",
                "ec_value": values["BPCN"],
                "sysfs_value": sysfs_bat0.get("capacity") if sysfs_bat0 else None,
            },
            "voltage_mv": {
                "ec_field": "B1FV",
                "ec_value": values["B1FV"],
                "sysfs_value": (
                    int(sysfs_bat0["voltage_now"]) // 1000
                    if sysfs_bat0 and sysfs_bat0.get("voltage_now")
                    else None
                ),
            },
            "status_bits": {
                "ec_field": "B1ST",
                "ec_value": values["B1ST"],
                "decoded": decode_battery_status(values["B1ST"]),
                "sysfs_value": sysfs_bat0.get("status") if sysfs_bat0 else None,
            },
            "power_supply_mode": {
                "ec_field": "PSMD",
                "ec_value": values["PSMD"],
                "decoded": decode_power_supply_mode(values["PSMD"]),
            },
        },
        "confirmed_control_fields": {
            "charge_limit_percent": {"field": "CHLT", "value": values["CHLT"]},
            "bypass_power_mode": {"field": "BPWM", "value": values["BPWM"]},
            "force_charge_min": {"field": "FCMN", "value": values["FCMN"]},
            "power_supply_mode": {
                "field": "PSMD",
                "value": values["PSMD"],
                "decoded": decode_power_supply_mode(values["PSMD"]),
            },
        },
        "candidate_control_fields": {
            "charge_limit_or_charge_control": {"field": "CHGR", "value": values["CHGR"]},
            "bypass_or_alt_mode": {"field": "BALT", "value": values["BALT"]},
        },
        "fields": fields,
    }

    if include_dump:
        payload["dump_hex"] = raw.hex()

    return payload


def print_text(payload):
    backend = payload["backend"]
    print(f"backend: {backend['type']} via {backend['path']} @ {backend['base']}")

    sysfs_bat0 = payload.get("sysfs_bat0") or {}
    if sysfs_bat0:
        print("sysfs BAT0:")
        for key, value in sysfs_bat0.items():
            print(f"  {key}: {value}")

    linux_metrics = payload.get("linux_battery_metrics") or {}
    if linux_metrics:
        print("linux battery metrics:")
        for key, value in linux_metrics.items():
            print(f"  {key}: {value}")

    print("confirmed matches:")
    for key, value in payload["confirmed_matches"].items():
        print(f"  {key}: {value}")

    print("confirmed control fields:")
    for key, value in payload["confirmed_control_fields"].items():
        print(f"  {key}: {value}")

    print("candidate control fields:")
    for key, value in payload["candidate_control_fields"].items():
        print(f"  {key}: {value}")

    print("fields:")
    for field in payload["fields"]:
        suffix = f", decoded={field['decoded']}" if "decoded" in field else ""
        print(
            f"  {field['name']} {field['offset']} {field['hex']} = {field['value']}"
            f" ({field['description']}{suffix})"
        )


def main():
    args = parse_args()
    try:
        payload = build_payload(args.dump)
    except PermissionError:
        print("Error: reading /dev/mem requires root", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)


if __name__ == "__main__":
    main()
