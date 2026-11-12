import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from linux_notch.ui.island import (  # noqa: E402
    _find_monitor,
    expanded_geometry,
)


class FakeMonitor:
    def __init__(self, connector):
        self.connector = connector

    def get_connector(self):
        return self.connector


class FakeMonitorList:
    def __init__(self, *monitors):
        self.monitors = monitors

    def get_n_items(self):
        return len(self.monitors)

    def get_item(self, index):
        return self.monitors[index]


class ExpandedSizingTests(unittest.TestCase):
    def test_expanded_size_tracks_content_dimensions(self):
        compact = expanded_geometry(420, 200, 1600, 900)
        larger = expanded_geometry(700, 360, 1600, 900)

        self.assertGreater(larger["width"], compact["width"])
        self.assertGreater(larger["height"], compact["height"])

    def test_expanded_size_stays_within_monitor_bounds(self):
        geometry = expanded_geometry(1600, 1200, 1000, 800)

        self.assertLessEqual(geometry["width"], 920)
        self.assertLessEqual(geometry["height"], 656)
        self.assertGreaterEqual(geometry["radius"], 0)
        self.assertGreaterEqual(geometry["ear"], 0)

    def test_monitor_selection_uses_configured_monitor_or_first_available(self):
        first = FakeMonitor("DP-1")
        selected = FakeMonitor("HDMI-1")
        monitors = FakeMonitorList(first, selected)

        self.assertIs(_find_monitor(monitors, "HDMI-1"), selected)
        self.assertIs(_find_monitor(monitors, ""), first)
        self.assertIsNone(_find_monitor(FakeMonitorList(), ""))


if __name__ == "__main__":
    unittest.main()
