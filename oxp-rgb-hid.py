#!/usr/bin/env python3
"""
Experimental RGB control for the OneXPlayer Super X vendor HID interface.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_VENDOR_ID = 0x1A2C
DEFAULT_PRODUCT_ID = 0xB001
DEFAULT_INTERFACE = 0
PACKET_SIZE = 64
BRIGHTNESS_LEVELS = {
    "off": [0x07, 0xFF, 0xFD, 0x00, 0x05, 0x01],
    "1": [0x07, 0xFF, 0xFD, 0x01, 0x05, 0x01],
    "2": [0x07, 0xFF, 0xFD, 0x01, 0x05, 0x03],
    "3": [0x07, 0xFF, 0xFD, 0x01, 0x05, 0x04],
}
SAFE_PRESET_IDS = set(range(0x00, 0x17))
CAPTURED_PRESET_IDS = {0x0D, 0x03, 0x0B, 0x05, 0x07, 0x09, 0x0C, 0x02, 0x08}


def parse_int(value: str) -> int:
    return int(value, 0)


def read_attr(path: Path, name: str) -> str | None:
    attr = path / name
    if not attr.exists():
        return None
    return attr.read_text(encoding="utf-8").strip()


def find_hidraw_path(vendor_id: int, product_id: int, interface: int) -> Path:
    for hidraw in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        device = (hidraw / "device").resolve()
        usb_interface = device.parent
        usb_device = usb_interface.parent
        if read_attr(usb_device, "idVendor") != f"{vendor_id:04x}":
            continue
        if read_attr(usb_device, "idProduct") != f"{product_id:04x}":
            continue
        if read_attr(usb_interface, "bInterfaceNumber") != f"{interface:02x}":
            continue
        return Path("/dev") / hidraw.name
    raise RuntimeError(
        f"hidraw device not found for vendor=0x{vendor_id:04x} "
        f"product=0x{product_id:04x} interface={interface}"
    )


def pad_packet(prefix: list[int]) -> list[int]:
    if len(prefix) > PACKET_SIZE:
        raise ValueError(f"packet too long: {len(prefix)}")
    return prefix + [0] * (PACKET_SIZE - len(prefix))


def build_static_packet(red: int, green: int, blue: int) -> list[int]:
    for value in (red, green, blue):
        if value < 0 or value > 255:
            raise ValueError("RGB values must be in range 0-255")
    payload = [0x07, 0xFF, 0xFE]
    payload.extend([red, green, blue] * 20)
    payload.append(0x00)
    return payload


def build_mode_packet(mode: str) -> list[int]:
    if mode == "static":
        return pad_packet([0x07, 0xFF, 0xFD, 0x00, 0x05, 0x04])
    if mode == "enable":
        return pad_packet([0x07, 0xFF, 0x05, 0x00])
    if mode == "rainbow":
        return pad_packet([0x07, 0xFF, 0xFD, 0x01, 0x05, 0x04])
    if mode == "alt-static":
        return pad_packet([0x07, 0xFF, 0xFD, 0x01, 0x05, 0x04])
    raise ValueError(f"unsupported mode: {mode}")


def build_level_packet(level: str) -> list[int]:
    try:
        return pad_packet(BRIGHTNESS_LEVELS[level])
    except KeyError as exc:
        raise ValueError(f"unsupported level: {level}") from exc


def build_preset_packet(preset_id: int) -> list[int]:
    if preset_id not in SAFE_PRESET_IDS:
        raise ValueError(
            f"unsupported preset id 0x{preset_id:02x}; "
            f"safe range: 0x00..0x16; "
            f"captured ids: {', '.join(f'0x{value:02x}' for value in sorted(CAPTURED_PRESET_IDS))}"
        )
    return pad_packet([0x07, 0xFF, preset_id, 0x00, 0x00])


def build_parser():
    parser = argparse.ArgumentParser(description="Experimental OneXPlayer Super X RGB HID helper")
    parser.add_argument("--vendor-id", type=parse_int, default=DEFAULT_VENDOR_ID)
    parser.add_argument("--product-id", type=parse_int, default=DEFAULT_PRODUCT_ID)
    parser.add_argument("--interface", type=int, default=DEFAULT_INTERFACE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")

    subparsers = parser.add_subparsers(dest="cmd", required=True)

    static = subparsers.add_parser("static", help="Send a static RGB color packet")
    static.add_argument("--dry-run", action="store_true")
    static.add_argument("--json", action="store_true")
    static.add_argument("red", type=int)
    static.add_argument("green", type=int)
    static.add_argument("blue", type=int)

    mode = subparsers.add_parser("mode", help="Send a captured mode packet")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("mode", choices=["static", "enable", "rainbow", "alt-static"])

    level = subparsers.add_parser("level", help="Send a captured brightness/on-off packet")
    level.add_argument("--dry-run", action="store_true")
    level.add_argument("--json", action="store_true")
    level.add_argument("level", choices=["off", "1", "2", "3"])

    preset = subparsers.add_parser("preset", help="Send a captured preset-id packet")
    preset.add_argument("--dry-run", action="store_true")
    preset.add_argument("--json", action="store_true")
    preset.add_argument("preset_id", type=parse_int)

    return parser


def main():
    args = build_parser().parse_args()
    if args.cmd == "static":
        packet = build_static_packet(args.red, args.green, args.blue)
        action = {"cmd": "static", "rgb": [args.red, args.green, args.blue]}
    elif args.cmd == "mode":
        packet = build_mode_packet(args.mode)
        action = {"cmd": "mode", "mode": args.mode}
    elif args.cmd == "level":
        packet = build_level_packet(args.level)
        action = {"cmd": "level", "level": args.level}
    elif args.cmd == "preset":
        packet = build_preset_packet(args.preset_id)
        action = {"cmd": "preset", "preset_id": args.preset_id}
    else:
        raise RuntimeError(f"unsupported command: {args.cmd}")

    result = {
        **action,
        "interface": args.interface,
        "packet": packet,
    }
    if args.dry_run:
        result["status"] = "dry-run"
        print(json.dumps(result, indent=2) if args.json else result)
        return

    hidraw_path = find_hidraw_path(args.vendor_id, args.product_id, args.interface)
    with hidraw_path.open("r+b", buffering=0) as device:
        written = device.write(bytes(packet))
    result["status"] = "ok"
    result["written"] = written
    result["path"] = str(hidraw_path)

    print(json.dumps(result, indent=2) if args.json else result)


if __name__ == "__main__":
    main()
