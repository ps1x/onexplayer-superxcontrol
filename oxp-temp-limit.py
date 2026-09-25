#!/usr/bin/env python3
"""Manage the CPU Tctl limit on OneXPlayer Super X."""

import argparse
import fcntl
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

RYZENADJ = Path("/usr/local/bin/ryzenadj")
STATE = Path("/var/lib/oxp-temp-limit.json")
LOCK = Path("/run/lock/oxp-temp-limit.lock")
LIMITS = (75, 80, 85, 90, 95)


def current_limit():
    result = subprocess.run(
        [str(RYZENADJ), "--info"], capture_output=True, text=True, check=True, timeout=10
    )
    match = re.search(r"^\|\s*THM LIMIT CORE\s*\|\s*([\d.]+)\s*\|", result.stdout, re.M)
    if not match:
        raise RuntimeError("ryzenadj did not report THM LIMIT CORE")
    return round(float(match.group(1)))


def saved_state():
    if not STATE.exists():
        return None
    data = json.loads(STATE.read_text())
    if data.get("limit") not in LIMITS or not isinstance(data.get("previous_limit"), int):
        raise RuntimeError("invalid saved temperature-limit state")
    return data


def write_state(limit, previous_limit):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=STATE.parent, delete=False) as handle:
        json.dump({"limit": limit, "previous_limit": previous_limit}, handle)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o644)
    os.replace(temp_path, STATE)


def apply_limit(limit):
    subprocess.run([str(RYZENADJ), f"--tctl-temp={limit}"], check=True, timeout=10)
    actual = current_limit()
    if actual != limit:
        raise RuntimeError(f"requested {limit}C, firmware reports {actual}C")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "set", "off", "apply"))
    parser.add_argument("limit", nargs="?", type=int, choices=LIMITS)
    args = parser.parse_args()
    if (args.command == "set") != (args.limit is not None):
        parser.error("set requires a temperature; other commands take no temperature")

    if args.command == "status":
        state = saved_state()
        print(json.dumps({"limit": state["limit"] if state else None}))
        return
    if os.geteuid() != 0:
        parser.error("on, off and apply require root")
    if not RYZENADJ.exists():
        raise FileNotFoundError(RYZENADJ)

    with LOCK.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state = saved_state()
        if args.command == "set":
            previous = state["previous_limit"] if state else current_limit()
            apply_limit(args.limit)
            write_state(args.limit, previous)
        elif args.command == "off":
            if state:
                apply_limit(state["previous_limit"])
                STATE.unlink()
        elif state:
            apply_limit(state["limit"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Error: {exc}") from exc
