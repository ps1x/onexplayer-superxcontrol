#!/usr/bin/env python3
"""Run configurable actions for the OneXPlayer Super X Turbo button."""

from __future__ import annotations

import argparse
import atexit
import configparser
import io
import json
import os
import re
import select
import signal
import shutil
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG = Path("/etc/oxp-turbo-button.conf")
STATE_FILE = Path("/var/lib/oxp-turbo-button-state")
INPUT_NAME = "OneXPlayer Super X Turbo Button"
# The in-tree oxpec driver exposes tt_toggle (1 = the EC firmware owns the
# Turbo button).  The retired out-of-tree oxp-sensors module exposed
# turbo_firmware_action with the same meaning.
FIRMWARE_ACTION_ATTRS = (
    Path("/sys/devices/platform/oxp-platform/tt_toggle"),
    Path("/sys/devices/platform/oxp-platform/turbo_firmware_action"),
)
CPU_PROFILE_HELPER = Path("/usr/local/bin/oxp-cpu-profile")
RGB_HELPER = Path("/usr/local/bin/oxp-rgb")
EV_KEY = 0x01
KEY_PROG1 = 148
INPUT_EVENT = struct.Struct("llHHI")
POWER_PROFILES = {
    "power-saver", "balanced", "performance", "adaptive", "ultra", "unchanged"
}
LED_PRESETS = {
    "unchanged", "off", "dim", "mid", "bright", "rainbow", "red", "green",
    "blue", "warm", "rainbow-flow", "rainbow-breath-random", "rainbow-cycle",
    "slow-color-runner", "slow-color-breath", "slow-color-breath-2",
    "slow-color-breath-3", "flame-cycle", "cyberpunk", "teal-green-drops",
    "pink-red-drops", "whole-rainbow-cycle", "red-monster", "green-monster",
    "blue-monster", "green-breath", "cyan-breath", "pink-breath",
    "white-breath-slow", "red-solid",
}


@dataclass(frozen=True)
class ToggleState:
    name: str
    power_profile: str
    tdp: tuple[int, int, int] | None
    led: str
    command: str


@dataclass(frozen=True)
class ButtonConfig:
    behavior: str
    firmware_action: bool
    command: str
    states: tuple[ToggleState, ToggleState] | None
    initial_state: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check-config", action="store_true", help="validate configuration and exit"
    )
    mode.add_argument(
        "--print-config-json", action="store_true", help="print configuration as JSON"
    )
    mode.add_argument(
        "--write-config-json", metavar="JSON", help="validate and install JSON configuration"
    )
    return parser.parse_args()


def parse_tdp(value: str, section: str) -> tuple[int, int, int] | None:
    if value.strip().lower() == "unchanged":
        return None
    try:
        values = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise ValueError(f"[{section}] tdp must contain three integer watt values") from exc
    if len(values) != 3:
        raise ValueError(f"[{section}] tdp must contain STAPM, fast, and slow watts")
    if any(not 3 <= watts <= 80 for watts in values):
        raise ValueError(f"[{section}] TDP limits must be between 3 and 80 W")
    return values


def load_config(path: Path) -> ButtonConfig:
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(path):
        raise FileNotFoundError(f"Turbo button configuration not found: {path}")
    if not parser.has_section("general"):
        raise ValueError("configuration requires a [general] section")

    behavior = parser.get("general", "behavior", fallback="toggle").strip().lower()
    if behavior not in {"toggle", "command"}:
        raise ValueError("[general] behavior must be 'toggle' or 'command'")
    firmware_action = parser.getboolean("general", "firmware_action", fallback=True)
    command = parser.get("general", "command", fallback="").strip()

    if behavior == "command" and not command:
        raise ValueError("[general] command is required when behavior=command")

    state_names = tuple(
        name.strip() for name in parser.get("general", "states", fallback="").split(",")
        if name.strip()
    )
    if behavior == "command" and not state_names:
        return ButtonConfig(behavior, firmware_action, command, None, None)
    if len(state_names) != 2 or state_names[0] == state_names[1]:
        raise ValueError("[general] states must name exactly two different states")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,31}", name) for name in state_names):
        raise ValueError("state names may contain only letters, numbers, spaces, '_' and '-'")
    initial_state = parser.get(
        "general", "initial_state", fallback=state_names[0]
    ).strip()
    if initial_state not in state_names:
        raise ValueError("[general] initial_state must be one of the configured states")

    states = []
    for name in state_names:
        section = f"state {name}"
        if not parser.has_section(section):
            raise ValueError(f"configuration requires a [{section}] section")
        power_profile = parser.get(section, "power_profile", fallback="").strip()
        if power_profile not in POWER_PROFILES:
            allowed = ", ".join(sorted(POWER_PROFILES))
            raise ValueError(f"[{section}] invalid power_profile; choose one of: {allowed}")
        tdp = parse_tdp(parser.get(section, "tdp", fallback=""), section)
        led = parser.get(section, "led", fallback="unchanged").strip().lower()
        if led not in LED_PRESETS:
            allowed = ", ".join(sorted(LED_PRESETS))
            raise ValueError(f"[{section}] invalid led preset; choose one of: {allowed}")
        state_command = parser.get(section, "command", fallback="").strip()
        states.append(ToggleState(name, power_profile, tdp, led, state_command))

    return ButtonConfig(
        behavior, firmware_action, command, (states[0], states[1]), initial_state
    )


def config_as_dict(config: ButtonConfig) -> dict:
    payload = {
        "behavior": config.behavior,
        "firmware_action": config.firmware_action,
        "command": config.command,
        "initial_state": config.initial_state,
        "states": [],
    }
    if config.states:
        payload["states"] = [
            {
                "name": state.name,
                "power_profile": state.power_profile,
                "tdp": list(state.tdp) if state.tdp else None,
                "led": state.led,
                "command": state.command,
            }
            for state in config.states
        ]
    return payload


def one_line(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError(f"{field} must fit on one line")
    return value


def config_from_dict(payload: object) -> ButtonConfig:
    if not isinstance(payload, dict):
        raise ValueError("configuration JSON must be an object")
    behavior = one_line(payload.get("behavior", ""), "behavior").lower()
    if behavior not in {"toggle", "command"}:
        raise ValueError("behavior must be 'toggle' or 'command'")
    firmware_action = payload.get("firmware_action")
    if not isinstance(firmware_action, bool):
        raise ValueError("firmware_action must be true or false")
    command = one_line(payload.get("command", ""), "command")
    if behavior == "command" and not command:
        raise ValueError("command is required for command behavior")

    raw_states = payload.get("states", [])
    if not raw_states and behavior == "command":
        return ButtonConfig(behavior, firmware_action, command, None, None)
    if not isinstance(raw_states, list) or len(raw_states) != 2:
        raise ValueError("toggle configuration requires exactly two states")

    states = []
    for index, raw_state in enumerate(raw_states, start=1):
        if not isinstance(raw_state, dict):
            raise ValueError(f"state {index} must be an object")
        name = one_line(raw_state.get("name", ""), f"state {index} name")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,31}", name):
            raise ValueError(
                f"state {index} name may contain only letters, numbers, spaces, '_' and '-'"
            )
        profile = one_line(
            raw_state.get("power_profile", ""), f"state {index} power_profile"
        )
        if profile not in POWER_PROFILES:
            raise ValueError(f"state {index} has an invalid power profile")
        raw_tdp = raw_state.get("tdp")
        if raw_tdp is None:
            tdp = None
        elif (
            isinstance(raw_tdp, list)
            and len(raw_tdp) == 3
            and all(isinstance(value, int) and not isinstance(value, bool) for value in raw_tdp)
        ):
            tdp = tuple(raw_tdp)
            if any(not 3 <= watts <= 80 for watts in tdp):
                raise ValueError(f"state {index} TDP limits must be between 3 and 80 W")
        else:
            raise ValueError(f"state {index} tdp must be three integers or null")
        led = one_line(raw_state.get("led", "unchanged"), f"state {index} led").lower()
        if led not in LED_PRESETS:
            raise ValueError(f"state {index} has an invalid LED preset")
        state_command = one_line(raw_state.get("command", ""), f"state {index} command")
        states.append(ToggleState(name, profile, tdp, led, state_command))

    if states[0].name == states[1].name:
        raise ValueError("state names must be different")
    initial_state = one_line(payload.get("initial_state", states[0].name), "initial_state")
    if initial_state not in {state.name for state in states}:
        raise ValueError("initial_state must match one of the configured states")
    return ButtonConfig(
        behavior, firmware_action, command, (states[0], states[1]), initial_state
    )


def render_config(config: ButtonConfig) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    general = {
        "behavior": config.behavior,
        "command": config.command,
        "firmware_action": "true" if config.firmware_action else "false",
    }
    if config.states:
        general["states"] = ", ".join(state.name for state in config.states)
        general["initial_state"] = config.initial_state or config.states[0].name
    parser["general"] = general
    if config.states:
        for state in config.states:
            parser[f"state {state.name}"] = {
                "power_profile": state.power_profile,
                "tdp": "unchanged" if state.tdp is None else ", ".join(map(str, state.tdp)),
                "led": state.led,
                "command": state.command,
            }
    output = io.StringIO()
    parser.write(output)
    return output.getvalue()


def install_config(config: ButtonConfig) -> None:
    if os.geteuid() != 0:
        raise PermissionError("writing Turbo button configuration requires root")
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=DEFAULT_CONFIG.parent, encoding="utf-8"
    ) as handle:
        handle.write(render_config(config))
        temporary = Path(handle.name)
    os.replace(temporary, DEFAULT_CONFIG)
    DEFAULT_CONFIG.chmod(0o644)
    subprocess.run(
        ["/usr/bin/systemctl", "try-restart", "oxp-turbo-tdp.service"], check=True
    )


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


def firmware_action_attr() -> Path | None:
    for attr in FIRMWARE_ACTION_ATTRS:
        if attr.exists():
            return attr
    return None


def wait_for_firmware_attr(timeout: float = 15.0) -> Path | None:
    deadline = time.monotonic() + timeout
    while True:
        attr = firmware_action_attr()
        if attr is not None:
            return attr
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def set_firmware_action(enabled: bool, attr: Path | None = None) -> None:
    attr = attr if attr is not None else firmware_action_attr()
    if attr is None:
        return
    attr.write_text("1\n" if enabled else "0\n", encoding="ascii")


def apply_limits(tdp: tuple[int, int, int]) -> None:
    ryzenadj = shutil.which("ryzenadj")
    if not ryzenadj:
        raise FileNotFoundError("ryzenadj was not found in PATH")
    stapm, fast, slow = tdp
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


def run_command(command: str, state: ToggleState | None = None) -> None:
    environment = os.environ.copy()
    environment["OXP_TURBO_BEHAVIOR"] = "toggle" if state else "command"
    if state:
        environment["OXP_TURBO_STATE"] = state.name
        environment["OXP_TURBO_POWER_PROFILE"] = state.power_profile
        environment["OXP_TURBO_LED"] = state.led
        if state.tdp:
            environment["OXP_TURBO_TDP_STAPM"] = str(state.tdp[0])
            environment["OXP_TURBO_TDP_FAST"] = str(state.tdp[1])
            environment["OXP_TURBO_TDP_SLOW"] = str(state.tdp[2])
        else:
            environment["OXP_TURBO_TDP_STAPM"] = "unchanged"
            environment["OXP_TURBO_TDP_FAST"] = "unchanged"
            environment["OXP_TURBO_TDP_SLOW"] = "unchanged"
    subprocess.run(["/bin/sh", "-c", command], check=True, env=environment)


def apply_state(state: ToggleState, run_state_command: bool = True) -> None:
    if state.power_profile != "unchanged":
        subprocess.run(
            [str(CPU_PROFILE_HELPER), "set", state.power_profile], check=True
        )
    if state.tdp:
        apply_limits(state.tdp)
    if state.led != "unchanged":
        subprocess.run([str(RGB_HELPER), state.led], check=True)
    if run_state_command and state.command:
        run_command(state.command, state)


def read_state(states: tuple[ToggleState, ToggleState], initial_state: str) -> ToggleState:
    fallback = next(state for state in states if state.name == initial_state)
    try:
        saved = STATE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        saved = initial_state
    return next((state for state in states if state.name == saved), fallback)


def write_state(state: ToggleState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=STATE_FILE.parent, encoding="utf-8"
    ) as handle:
        handle.write(f"{state.name}\n")
        temporary = Path(handle.name)
    os.replace(temporary, STATE_FILE)
    STATE_FILE.chmod(0o644)


def describe_state(state: ToggleState) -> str:
    tdp = "unchanged" if state.tdp is None else "/".join(map(str, state.tdp)) + " W"
    return (
        f"state={state.name}, profile={state.power_profile}, "
        f"TDP={tdp}, LED={state.led}"
    )


def restore_firmware_action() -> None:
    try:
        set_firmware_action(True)
    except OSError:
        pass


def main() -> None:
    args = parse_args()
    if args.write_config_json is not None:
        config = config_from_dict(json.loads(args.write_config_json))
        install_config(config)
        print("Turbo button configuration saved")
        return

    config = load_config(args.config)
    if args.check_config:
        print(f"Configuration OK: behavior={config.behavior}")
        return
    if args.print_config_json:
        print(json.dumps(config_as_dict(config)))
        return
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    firmware_attr = wait_for_firmware_attr()
    if firmware_attr is None:
        print("No tt_toggle/turbo_firmware_action sysfs attribute found", flush=True)
    try:
        set_firmware_action(config.firmware_action, firmware_attr)
    except OSError as exc:
        print(f"Could not configure Turbo firmware action: {exc}", flush=True)
    atexit.register(restore_firmware_action)
    try:
        input_device = find_input_device()
    except FileNotFoundError:
        # The in-tree oxpec driver does not create a Turbo button input
        # device; only the retired oxp-sensors module did.
        input_device = None
    current_state = None
    if config.behavior == "toggle" and config.states:
        current_state = read_state(config.states, config.initial_state or config.states[0].name)
        try:
            apply_state(current_state, run_state_command=False)
        except Exception as exc:
            print(
                f"Could not fully apply saved state {current_state.name!r}: {exc}",
                flush=True,
            )
        write_state(current_state)
        print(f"Restored {describe_state(current_state)}", flush=True)
    else:
        print("Ready: custom-command behavior", flush=True)

    if input_device is None:
        if firmware_attr is None:
            print(
                "No Turbo button input device and no firmware-action sysfs "
                "attribute; exiting",
                flush=True,
            )
            raise SystemExit(1)
        if config.firmware_action:
            print(
                "Turbo button is owned by the EC firmware (tt_toggle=1); "
                "no userspace button events",
                flush=True,
            )
        else:
            print(
                "No Turbo button input device (in-tree oxpec); the button is "
                "inert while firmware_action = false",
                flush=True,
            )
        while running:
            time.sleep(60)
        return

    fd = os.open(input_device, os.O_RDONLY | os.O_NONBLOCK)
    poller = select.poll()
    poller.register(fd, select.POLLIN)
    pending = b""

    try:
        while running:
            for _fd, event_mask in poller.poll(1000):
                if event_mask & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                    raise OSError(f"input device poll failed: mask={event_mask:#x}")

                pending += os.read(fd, INPUT_EVENT.size * 64)
                while len(pending) >= INPUT_EVENT.size:
                    event, pending = pending[:INPUT_EVENT.size], pending[INPUT_EVENT.size:]
                    _sec, _usec, event_type, code, value = INPUT_EVENT.unpack(event)
                    if event_type != EV_KEY or code != KEY_PROG1 or value != 1:
                        continue
                    try:
                        if config.behavior == "command":
                            run_command(config.command)
                            print("Turbo button: custom command completed", flush=True)
                        else:
                            assert config.states is not None and current_state is not None
                            current_state = (
                                config.states[1]
                                if current_state.name == config.states[0].name
                                else config.states[0]
                            )
                            write_state(current_state)
                            apply_state(current_state)
                            print(f"Turbo button: {describe_state(current_state)}", flush=True)
                    except Exception as exc:
                        print(f"Turbo button action failed: {exc}", flush=True)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
