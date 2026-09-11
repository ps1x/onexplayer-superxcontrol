#!/usr/bin/env python3

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "contrib/power/oxp-turbo-tdp.py"
SPEC = importlib.util.spec_from_file_location("oxp_turbo_button", MODULE_PATH)
turbo = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = turbo
SPEC.loader.exec_module(turbo)


class ConfigTests(unittest.TestCase):
    def load(self, contents):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "turbo.conf"
            path.write_text(contents, encoding="utf-8")
            return turbo.load_config(path)

    def test_toggle_configuration(self):
        config = self.load(
            """
[general]
behavior = toggle
firmware_action = false
states = quiet, fast
initial_state = quiet

[state quiet]
power_profile = power-saver
tdp = 8, 12, 10
led = blue
command = logger quiet

[state fast]
power_profile = performance
tdp = 45, 45, 45
led = red
command = logger fast
"""
        )
        self.assertEqual(config.behavior, "toggle")
        self.assertFalse(config.firmware_action)
        self.assertEqual(config.states[0].tdp, (8, 12, 10))
        self.assertEqual(config.states[1].power_profile, "performance")

    def test_command_allows_percent_characters(self):
        config = self.load(
            """
[general]
behavior = command
firmware_action = false
command = date +%s
"""
        )
        self.assertEqual(config.command, "date +%s")
        self.assertIsNone(config.states)

    def test_rejects_out_of_range_tdp(self):
        with self.assertRaisesRegex(ValueError, "between 3 and 80 W"):
            self.load(
                """
[general]
behavior = toggle
states = low, high

[state low]
power_profile = power-saver
tdp = 2, 10, 10

[state high]
power_profile = performance
tdp = 80, 80, 81
"""
            )

    def test_json_round_trip_preserves_toggle_settings(self):
        original = turbo.config_from_dict(
            {
                "behavior": "toggle",
                "firmware_action": False,
                "command": "",
                "initial_state": "fast",
                "states": [
                    {
                        "name": "quiet",
                        "power_profile": "power-saver",
                        "tdp": None,
                        "led": "blue",
                        "command": "logger quiet",
                    },
                    {
                        "name": "fast",
                        "power_profile": "performance",
                        "tdp": [45, 50, 45],
                        "led": "red",
                        "command": "logger fast",
                    },
                ],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "turbo.conf"
            path.write_text(turbo.render_config(original), encoding="utf-8")
            restored = turbo.load_config(path)
        self.assertEqual(turbo.config_as_dict(restored), turbo.config_as_dict(original))

    def test_json_rejects_multiline_root_command(self):
        payload = turbo.config_as_dict(turbo.load_config(
            Path(__file__).parents[1] / "contrib/power/oxp-turbo-button.conf"
        ))
        payload["states"][0]["command"] = "safe\ninjected = value"
        with self.assertRaisesRegex(ValueError, "must fit on one line"):
            turbo.config_from_dict(payload)


class ActionTests(unittest.TestCase):
    def test_invalid_saved_state_uses_configured_initial_state(self):
        states = (
            turbo.ToggleState("low", "power-saver", (8, 10, 8), "unchanged", ""),
            turbo.ToggleState("high", "performance", (45, 45, 45), "unchanged", ""),
        )
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state"
            state_file.write_text("removed-state\n", encoding="utf-8")
            with mock.patch.object(turbo, "STATE_FILE", state_file):
                selected = turbo.read_state(states, "high")
        self.assertEqual(selected.name, "high")

    @mock.patch.object(turbo, "run_command")
    @mock.patch.object(turbo, "apply_limits")
    @mock.patch.object(turbo.subprocess, "run")
    def test_apply_state_runs_profile_tdp_led_and_command(
        self, subprocess_run, apply_limits, run_command
    ):
        state = turbo.ToggleState("fast", "performance", (45, 50, 45), "red", "notify")
        turbo.apply_state(state)

        subprocess_run.assert_has_calls(
            [
                mock.call(
                    [str(turbo.CPU_PROFILE_HELPER), "set", "performance"], check=True
                ),
                mock.call([str(turbo.RGB_HELPER), "red"], check=True),
            ]
        )
        apply_limits.assert_called_once_with((45, 50, 45))
        run_command.assert_called_once_with("notify", state)

    @mock.patch.object(turbo.subprocess, "run")
    def test_unchanged_state_skips_helpers(self, subprocess_run):
        state = turbo.ToggleState("custom", "unchanged", None, "unchanged", "")
        turbo.apply_state(state)
        subprocess_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
