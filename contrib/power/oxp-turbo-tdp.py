#!/usr/bin/env python3
"""Set a TDP preset when the OneXPlayer Super X Turbo key is pressed."""

from __future__ import annotations

import argparse
import os
import select
import signal
import shutil
import struct
import subprocess
import time
from pathlib import Path


INPUT_NAME = "OneXPlayer Super X Turbo Button"
FIRMWARE_TDP = Path("/sys/devices/platform/oxp-platform/firmware_tdp")
EV_KEY = 0x01
KEY_PROG1 = 148
INPUT_EVENT = struct.Struct("llHHI")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watts", type=int, default=80)
    parser.add_argument("--normal-stapm", type=int, default=10)
    parser.add_argument("--normal-fast", type=int, default=15)
    parser.add_argument("--normal-slow", type=int, default=10)
    return parser.parse_args()


def wait_for(path: Path, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {path}")
        time.sleep(0.25)


def find_input_device() -> Path:
    for event in Path("/sys/class/input").glob("event*"):
        try:
            name = (event / "device/name").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name == INPUT_NAME:
            return Path("/dev/input") / event.name
    raise FileNotFoundError(f"input device {INPUT_NAME!r} was not found")


def read_firmware_tdp() -> tuple[int, int, int]:
    values = tuple(
        int(value) for value in FIRMWARE_TDP.read_text(encoding="ascii").split()
    )
    if len(values) != 3:
        raise RuntimeError(f"invalid firmware TDP tuple: {values}")
    return values


def apply_limits(stapm: int, fast: int, slow: int) -> None:
    ryzenadj = shutil.which("ryzenadj")
    if not ryzenadj:
        raise FileNotFoundError("ryzenadj was not found in PATH")

    subprocess.run(
        [
            ryzenadj,
            "--stapm-limit", str(stapm * 1000),
            "--fast-limit", str(fast * 1000),
            "--slow-limit", str(slow * 1000),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    args = parse_args()
    limits = (args.watts, args.normal_stapm, args.normal_fast, args.normal_slow)
    if any(not 3 <= watts <= 80 for watts in limits):
        raise ValueError("TDP limits must be between 3 and 80 W")

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    wait_for(FIRMWARE_TDP)
    input_device = find_input_device()

    def sync_from_firmware() -> None:
        firmware = read_firmware_tdp()
        turbo_enabled = firmware[0] == firmware[1] == firmware[2] and firmware[0] >= 45
        if turbo_enabled:
            applied = (args.watts, args.watts, args.watts)
            mode = "turbo"
        else:
            applied = (args.normal_stapm, args.normal_fast, args.normal_slow)
            mode = "normal"
        apply_limits(*applied)
        print(
            f"Firmware {firmware[0]}/{firmware[1]}/{firmware[2]} W: "
            f"applied {applied[0]}/{applied[1]}/{applied[2]} W ({mode})",
            flush=True,
        )

    sync_from_firmware()

    fd = os.open(input_device, os.O_RDONLY | os.O_NONBLOCK)
    poller = select.poll()
    poller.register(fd, select.POLLIN)

    try:
        while running:
            for _fd, event_mask in poller.poll(1000):
                if event_mask & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                    raise OSError(f"input device poll failed: mask={event_mask:#x}")

                data = os.read(fd, INPUT_EVENT.size * 64)
                for offset in range(0, len(data), INPUT_EVENT.size):
                    _sec, _usec, event_type, code, value = \
                        INPUT_EVENT.unpack_from(data, offset)
                    if event_type == EV_KEY and code == KEY_PROG1 and value == 1:
                        sync_from_firmware()
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
