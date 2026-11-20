import unittest
from datetime import datetime
from types import SimpleNamespace

from linux_notch.services.power import CHARGING, DISCHARGING, FULL
from linux_notch.ui.pill import (
    Pill,
    format_pill_status,
    visualizer_capture_enabled,
)


class PillStatusTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 18, 13, 40)

    def test_clock_status_includes_time_and_date_in_both_clock_formats(self):
        self.assertEqual(
            format_pill_status(self.now, True),
            "13:40 · Nov 18",
        )
        self.assertEqual(
            format_pill_status(self.now, False),
            "01:40 PM · Nov 18",
        )

    def test_battery_status_includes_percentage_and_power_state(self):
        for state, expected in (
            (CHARGING, "82% · Charging"),
            (DISCHARGING, "82% · On battery"),
            (FULL, "82% · Full"),
        ):
            power = SimpleNamespace(
                available=True,
                percentage=82.4,
                state=state,
            )
            self.assertEqual(
                format_pill_status(self.now, True, power, show_battery=True),
                expected,
            )

    def test_unavailable_battery_falls_back_to_clock(self):
        power = SimpleNamespace(available=False, percentage=-1, state=0)
        self.assertEqual(
            format_pill_status(self.now, True, power, show_battery=True),
            "13:40 · Nov 18",
        )

    def test_closed_pill_rotates_cpu_and_ram_as_separate_statuses(self):
        context = SimpleNamespace(
            power=None,
            weather=object(),
            system=object(),
        )

        self.assertEqual(
            Pill._status_options(context),
            ["clock", "weather", "cpu", "ram"],
        )

    def test_real_capture_requires_playing_and_visible_closed_notch(self):
        self.assertTrue(visualizer_capture_enabled("Playing", True, "auto"))
        self.assertTrue(visualizer_capture_enabled("Playing", True, "real"))
        self.assertFalse(visualizer_capture_enabled("Playing", True, "synthetic"))
        self.assertFalse(visualizer_capture_enabled("Paused", True, "real"))
        self.assertFalse(visualizer_capture_enabled("Playing", False, "real"))


if __name__ == "__main__":
    unittest.main()
