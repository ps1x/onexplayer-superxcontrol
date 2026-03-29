#!/usr/bin/env python3
"""
OXP fan control daemon with named profile support.
"""

import configparser
import logging
import signal
import sys
import time
from collections import deque
from pathlib import Path

DEFAULT_CONFIG = """[general]
active_profile = balanced

[profile silent]
target_temp = 72
min_temp = 50
max_temp = 82
interval = 1
kp = 4.0
ki = 0.15
kd = 4.0
max_pwm_change = 5
min_pwm = 40
50 = 0
58 = 45
65 = 90
72 = 140
78 = 200
82 = 255

[profile balanced]
target_temp = 78
min_temp = 55
max_temp = 88
interval = 1
kp = 4.0
ki = 0.15
kd = 4.0
max_pwm_change = 5
min_pwm = 40
55 = 0
62 = 50
70 = 100
78 = 150
84 = 210
88 = 255

[profile watercool]
target_temp = 85
min_temp = 65
max_temp = 95
interval = 1
kp = 4.0
ki = 0.15
kd = 4.0
max_pwm_change = 5
min_pwm = 40
65 = 0
75 = 60
82 = 100
88 = 150
92 = 200
95 = 255

[profile aggressive]
target_temp = 65
min_temp = 50
max_temp = 85
interval = 1
kp = 6.0
ki = 0.2
kd = 3.0
max_pwm_change = 15
min_pwm = 40
50 = 40
55 = 120
60 = 150
65 = 180
70 = 210
75 = 240
80 = 255
"""

CONFIG_PATH = Path("/etc/oxp-fan-control.conf")
HWMON_PATH = None

PROFILE_PREFIX = "profile "
PARAM_DEFAULTS = {
    "target_temp": 78.0,
    "min_temp": 55.0,
    "max_temp": 88.0,
    "interval": 1.0,
    "kp": 4.0,
    "ki": 0.15,
    "kd": 4.0,
    "max_pwm_change": 5,
    "min_pwm": 40,
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("oxp-fan")


class PIDController:
    def __init__(self, kp, ki, kd, target, min_output=0, max_output=255):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.target = target
        self.min_output = min_output
        self.max_output = max_output
        self.integral = 0
        self.last_error = 0
        self.last_time = time.time()

    def reset(self):
        self.integral = 0
        self.last_error = 0
        self.last_time = time.time()

    def compute(self, current_value):
        now = time.time()
        dt = max(now - self.last_time, 0.1)

        error = current_value - self.target
        p_term = self.kp * error

        self.integral += error * dt
        self.integral = max(-100, min(100, self.integral))
        i_term = self.ki * self.integral

        d_term = 0
        if dt > 0:
            d_value = (current_value - (current_value - error)) / dt
            d_term = -self.kd * d_value

        output = p_term + i_term + d_term
        output = max(self.min_output, min(self.max_output, output))

        self.last_error = error
        self.last_time = now
        return output


def find_hwmon():
    for hwmon_dir in Path("/sys/class/hwmon").glob("hwmon*"):
        name_file = hwmon_dir / "name"
        if name_file.exists() and name_file.read_text().strip() == "oxpec":
            return hwmon_dir
    return None


def read_temp():
    for hwmon_dir in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            for label_file in hwmon_dir.glob("temp*_label"):
                label = label_file.read_text().strip()
                if label in ["Tctl", "Tdie", "CPU", "Core"]:
                    temp_file = label_file.with_name(label_file.name.replace("_label", "_input"))
                    if temp_file.exists():
                        return int(temp_file.read_text().strip()) / 1000.0

            temp_file = hwmon_dir / "temp1_input"
            if temp_file.exists():
                temp = int(temp_file.read_text().strip())
                if temp > 0:
                    return temp / 1000.0
        except (ValueError, IOError):
            continue
    return None


def set_fan_speed(pwm_value):
    if not HWMON_PATH:
        return False
    try:
        (HWMON_PATH / "pwm1_enable").write_text("1")
        (HWMON_PATH / "pwm1").write_text(str(int(pwm_value)))
        return True
    except IOError as exc:
        logger.error("Error setting fan speed: %s", exc)
        return False


def create_default_config():
    if CONFIG_PATH.exists():
        return
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(DEFAULT_CONFIG)
    logger.info("Created default config at %s", CONFIG_PATH)


def load_config():
    config = configparser.ConfigParser()
    config.read_string(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH)
    return config


def list_profiles(config):
    profiles = []
    for section in config.sections():
        if section.startswith(PROFILE_PREFIX):
            profiles.append(section[len(PROFILE_PREFIX):])
    return profiles


def get_profile_section(config, profile_name):
    if profile_name == "legacy" and config.has_section("fan"):
        return "fan"

    section = f"{PROFILE_PREFIX}{profile_name}"
    if config.has_section(section):
        return section
    return None


def get_active_profile_name(config):
    profiles = list_profiles(config)
    if profiles:
        requested = config.get("general", "active_profile", fallback=profiles[0]).strip()
        if requested in profiles:
            return requested
        return profiles[0]

    if config.has_section("fan"):
        return "legacy"

    raise RuntimeError("No usable fan profile found in config")


def parse_fan_curve(config, section):
    curve = {}
    for key, value in config.items(section):
        if key.isdigit():
            curve[int(key)] = int(value)
    return dict(sorted(curve.items()))


def get_base_pwm(temp, curve, min_temp):
    if temp < min_temp or not curve:
        return 0

    thresholds = sorted(curve.keys())

    if temp <= thresholds[0]:
        return curve[thresholds[0]]
    if temp >= thresholds[-1]:
        return curve[thresholds[-1]]

    for index in range(len(thresholds) - 1):
        left = thresholds[index]
        right = thresholds[index + 1]
        if left <= temp <= right:
            left_pwm = curve[left]
            right_pwm = curve[right]
            return left_pwm + (right_pwm - left_pwm) * (temp - left) / (right - left)
    return 0


def load_runtime_settings():
    config = load_config()
    profile_name = get_active_profile_name(config)
    section = get_profile_section(config, profile_name)
    curve = parse_fan_curve(config, section)
    settings = {
        "profile_name": profile_name,
        "target_temp": config.getfloat(section, "target_temp", fallback=PARAM_DEFAULTS["target_temp"]),
        "min_temp": config.getfloat(section, "min_temp", fallback=PARAM_DEFAULTS["min_temp"]),
        "max_temp": config.getfloat(section, "max_temp", fallback=PARAM_DEFAULTS["max_temp"]),
        "interval": config.getfloat(section, "interval", fallback=PARAM_DEFAULTS["interval"]),
        "kp": config.getfloat(section, "kp", fallback=PARAM_DEFAULTS["kp"]),
        "ki": config.getfloat(section, "ki", fallback=PARAM_DEFAULTS["ki"]),
        "kd": config.getfloat(section, "kd", fallback=PARAM_DEFAULTS["kd"]),
        "max_pwm_change": config.getint(section, "max_pwm_change", fallback=PARAM_DEFAULTS["max_pwm_change"]),
        "min_pwm": config.getint(section, "min_pwm", fallback=PARAM_DEFAULTS["min_pwm"]),
        "curve": curve,
    }
    return settings


def main():
    global HWMON_PATH

    running = True

    def signal_handler(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    HWMON_PATH = find_hwmon()
    if not HWMON_PATH:
        logger.error("Could not find oxp-sensors hwmon device.")
        sys.exit(1)

    logger.info("Found OXP hwmon at: %s", HWMON_PATH)
    create_default_config()

    current_mtime = None
    current_profile = None
    settings = None
    pid = None
    temp_history = deque(maxlen=3)
    last_pwm = 0
    fan_off = True
    manual_off_applied = False

    logger.info("Starting fan control daemon...")

    while running:
        try:
            config_mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else None
            if settings is None or config_mtime != current_mtime:
                settings = load_runtime_settings()
                current_mtime = config_mtime
                temp_history.clear()
                last_pwm = 0
                fan_off = True
                manual_off_applied = False
                pid = PIDController(
                    settings["kp"],
                    settings["ki"],
                    settings["kd"],
                    settings["target_temp"],
                    0,
                    255,
                )
                if current_profile != settings["profile_name"]:
                    logger.info(
                        "Loaded fan profile '%s' (target=%sC min=%sC max=%sC)",
                        settings["profile_name"],
                        settings["target_temp"],
                        settings["min_temp"],
                        settings["max_temp"],
                    )
                else:
                    logger.info("Reloaded fan profile '%s'", settings["profile_name"])
                current_profile = settings["profile_name"]

            temp = read_temp()
            if temp is None:
                logger.warning("Could not read temperature.")
                time.sleep(settings["interval"])
                continue

            temp_history.append(temp)
            smoothed_temp = sum(temp_history) / len(temp_history)

            if smoothed_temp >= settings["max_temp"]:
                target_pwm = 255
                fan_off = False
                logger.warning(
                    "EMERGENCY COOLING [%s]: Temp %.1fC >= %.1fC",
                    current_profile,
                    smoothed_temp,
                    settings["max_temp"],
                )
            else:
                base_pwm = get_base_pwm(smoothed_temp, settings["curve"], settings["min_temp"])

                if base_pwm == 0 and not fan_off and smoothed_temp >= (settings["min_temp"] - 3.0):
                    base_pwm = settings["min_pwm"]

                if base_pwm == 0:
                    if not manual_off_applied:
                        set_fan_speed(0)
                        manual_off_applied = True
                    if not fan_off:
                        fan_off = True
                        pid.reset()
                        last_pwm = 0
                        logger.info(
                            "[%s] Temp: %.1fC -> Fan: OFF",
                            current_profile,
                            smoothed_temp,
                        )
                    time.sleep(settings["interval"])
                    continue

                is_starting = fan_off
                fan_off = False
                manual_off_applied = False

                pid_adjustment = pid.compute(smoothed_temp)
                target_pwm = base_pwm + pid_adjustment

                if settings["max_pwm_change"] > 0 and not is_starting:
                    pwm_diff = target_pwm - last_pwm
                    if abs(pwm_diff) > settings["max_pwm_change"]:
                        step = settings["max_pwm_change"] if pwm_diff > 0 else -settings["max_pwm_change"]
                        target_pwm = last_pwm + step

                if target_pwm < settings["min_pwm"]:
                    target_pwm = settings["min_pwm"]

                target_pwm = max(0, min(255, target_pwm))

            if int(target_pwm) != int(last_pwm):
                if set_fan_speed(target_pwm):
                    logger.info(
                        "[%s] Temp: %.1fC -> PWM: %d",
                        current_profile,
                        smoothed_temp,
                        int(target_pwm),
                    )
                    last_pwm = target_pwm

            time.sleep(settings["interval"])

        except Exception as exc:
            logger.error("Error in main loop: %s", exc)
            time.sleep(settings["interval"] if settings else 1.0)

    logger.info("Restoring automatic fan control...")
    try:
        (HWMON_PATH / "pwm1_enable").write_text("0")
    except IOError:
        pass
    logger.info("Fan control stopped.")


if __name__ == "__main__":
    main()
