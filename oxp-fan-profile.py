#!/usr/bin/env python3
"""
Manage OXP fan profiles stored in /etc/oxp-fan-control.conf.
"""

import argparse
import configparser
import json
import os
import sys
import tempfile
from pathlib import Path

CONFIG_PATH = Path("/etc/oxp-fan-control.conf")
PROFILE_PREFIX = "profile "
PROFILE_ORDER = ["silent", "balanced", "watercool", "aggressive"]
STOCK_PROFILES = {
    "silent": {
        "target_temp": "72",
        "min_temp": "50",
        "max_temp": "82",
        "interval": "1",
        "kp": "4.0",
        "ki": "0.15",
        "kd": "4.0",
        "max_pwm_change": "5",
        "min_pwm": "40",
        "50": "0",
        "58": "45",
        "65": "90",
        "72": "140",
        "78": "200",
        "82": "255",
    },
    "balanced": {
        "target_temp": "78",
        "min_temp": "55",
        "max_temp": "88",
        "interval": "1",
        "kp": "4.0",
        "ki": "0.15",
        "kd": "4.0",
        "max_pwm_change": "5",
        "min_pwm": "40",
        "55": "0",
        "62": "50",
        "70": "100",
        "78": "150",
        "84": "210",
        "88": "255",
    },
    "watercool": {
        "target_temp": "85",
        "min_temp": "65",
        "max_temp": "95",
        "interval": "1",
        "kp": "4.0",
        "ki": "0.15",
        "kd": "4.0",
        "max_pwm_change": "5",
        "min_pwm": "40",
        "65": "0",
        "75": "60",
        "82": "100",
        "88": "150",
        "92": "200",
        "95": "255",
    },
    "aggressive": {
        "target_temp": "65",
        "min_temp": "50",
        "max_temp": "85",
        "interval": "1",
        "kp": "6.0",
        "ki": "0.2",
        "kd": "3.0",
        "max_pwm_change": "15",
        "min_pwm": "40",
        "50": "40",
        "55": "120",
        "60": "150",
        "65": "180",
        "70": "210",
        "75": "240",
        "80": "255",
    },
}


def load_config():
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH)
    return config


def profile_sections(config):
    return [section for section in config.sections() if section.startswith(PROFILE_PREFIX)]


def list_profiles(config):
    profiles = [section[len(PROFILE_PREFIX):] for section in profile_sections(config)]
    if not profiles and config.has_section("fan"):
        return ["legacy"]
    return profiles


def current_profile(config):
    profiles = list_profiles(config)
    if not profiles:
        raise RuntimeError("No fan profiles configured")
    selected = config.get("general", "active_profile", fallback=profiles[0]).strip()
    if selected in profiles:
        return selected
    return profiles[0]


def write_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=CONFIG_PATH.parent, encoding="utf-8") as handle:
        config.write(handle)
        temp_path = Path(handle.name)
    os.replace(temp_path, CONFIG_PATH)
    CONFIG_PATH.chmod(0o644)


def ensure_root():
    if os.geteuid() != 0:
        raise PermissionError("This command must run as root to modify /etc/oxp-fan-control.conf")


def make_stock_config(active_profile="balanced"):
    config = configparser.ConfigParser()
    config["general"] = {"active_profile": active_profile}
    for name in PROFILE_ORDER:
        config[f"{PROFILE_PREFIX}{name}"] = STOCK_PROFILES[name]
    return config


def merge_legacy_profile(config):
    if not config.has_section("fan"):
        raise RuntimeError("No legacy [fan] section found to migrate")

    migrated = make_stock_config(active_profile="legacy")
    legacy_values = {}
    for key, value in config.items("fan"):
        legacy_values[key] = value
    migrated[f"{PROFILE_PREFIX}legacy"] = legacy_values
    return migrated


def cmd_list(args):
    config = load_config()
    profiles = list_profiles(config)
    if args.json:
        print(json.dumps({"profiles": profiles}))
        return
    for profile in profiles:
        print(profile)


def cmd_current(args):
    config = load_config()
    current = current_profile(config)
    if args.json:
        print(json.dumps({"current": current}))
        return
    print(current)


def cmd_status(args):
    config = load_config()
    payload = {
        "current": current_profile(config),
        "profiles": list_profiles(config),
    }
    print(json.dumps(payload))


def cmd_set(args):
    ensure_root()
    config = load_config()
    profiles = list_profiles(config)
    if args.profile not in profiles:
        raise RuntimeError(f"Unknown profile '{args.profile}'. Available: {', '.join(profiles)}")
    if not config.has_section("general"):
        config.add_section("general")
    config.set("general", "active_profile", args.profile)
    write_config(config)
    print(f"Active profile set to {args.profile}")


def cmd_migrate_legacy(args):
    ensure_root()
    config = load_config()
    migrated = merge_legacy_profile(config)
    write_config(migrated)
    print("Migrated legacy [fan] config to named profiles; active profile is 'legacy'")


def build_parser():
    parser = argparse.ArgumentParser(description="Manage OXP fan profiles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available profiles")
    list_parser.add_argument("--json", action="store_true", help="Output JSON")
    list_parser.set_defaults(func=cmd_list)

    current_parser = subparsers.add_parser("current", help="Show active profile")
    current_parser.add_argument("--json", action="store_true", help="Output JSON")
    current_parser.set_defaults(func=cmd_current)

    status_parser = subparsers.add_parser("status", help="Show active profile and all profile names")
    status_parser.set_defaults(func=cmd_status)

    set_parser = subparsers.add_parser("set", help="Set active profile")
    set_parser.add_argument("profile", help="Profile name to activate")
    set_parser.set_defaults(func=cmd_set)

    migrate_parser = subparsers.add_parser("migrate-legacy", help="Convert a legacy [fan] config into profile sections")
    migrate_parser.set_defaults(func=cmd_migrate_legacy)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
