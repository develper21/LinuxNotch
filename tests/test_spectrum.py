import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from linux_notch.services.spectrum import (  # noqa: E402
    BANDS,
    FLOOR_DB,
    SpectrumSource,
    default_monitor,
    parse_magnitudes,
)


class SpectrumSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gst.init(None)

    def test_default_monitor_uses_default_sink_monitor(self):
        with patch(
            "linux_notch.services.spectrum.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout="alsa_output.test\n",
            ),
        ) as run:
            self.assertEqual(
                default_monitor(),
                "alsa_output.test.monitor",
            )

        run.assert_called_once()

    def test_missing_default_monitor_reports_fallback_reason(self):
        failures = []
        source = SpectrumSource(14, lambda _levels: None, failures.append)
        fake_gst = SimpleNamespace(
            ElementFactory=SimpleNamespace(find=lambda _name: object()))
        with (
            patch("linux_notch.services.spectrum.Gst", fake_gst),
            patch(
                "linux_notch.services.spectrum.default_monitor",
                return_value=None,
            ),
        ):
            source.start()

        self.assertFalse(source.running)
        self.assertEqual(len(failures), 1)
        self.assertIn("default output monitor", failures[0])

    def test_watchdog_stops_a_pipeline_without_spectrum_messages(self):
        failures = []
        source = SpectrumSource(14, lambda _levels: None, failures.append)
        source._pipeline = Gst.Pipeline.new("spectrum-watchdog-test")

        source._watchdog()

        self.assertFalse(source.running)
        self.assertEqual(
            failures,
            ["No spectrum data arrived within 2.5 seconds"],
        )

    def test_magnitude_parser_reads_native_and_serialized_values(self):
        structure = Gst.Structure.new_empty("spectrum")
        structure.set_value(
            "magnitude",
            [-48.0, float("-inf"), float("nan"), float("inf")],
        )
        self.assertEqual(
            parse_magnitudes(structure),
            [-48.0, FLOOR_DB, FLOOR_DB, 0.0],
        )

        class SerializedStructure:
            def get_value(self, _key):
                raise TypeError("boxed value is unavailable")

            def to_string(self):
                return "spectrum, magnitude=(float){-55.0, -40.0};"

        self.assertEqual(
            parse_magnitudes(SerializedStructure()),
            [-55.0, -40.0],
        )

    def test_element_messages_are_grouped_into_logarithmic_bar_levels(self):
        levels = []
        source = SpectrumSource(14, levels.append, lambda _reason: None)
        source._pipeline = Gst.Pipeline.new("spectrum-test")
        magnitude = [-80.0] * BANDS
        first, last = source.ranges[0]
        for index in range(first, last):
            magnitude[index] = -30.0
        structure = Gst.Structure.new_empty("spectrum")
        structure.set_value("magnitude", magnitude)
        source._on_element(
            None,
            SimpleNamespace(get_structure=lambda: structure),
        )

        self.assertEqual(len(levels), 1)
        self.assertEqual(len(levels[0]), 14)
        self.assertGreater(levels[0][0], 0.0)
        self.assertTrue(all(0.0 <= level <= 1.0 for level in levels[0]))


if __name__ == "__main__":
    unittest.main()
