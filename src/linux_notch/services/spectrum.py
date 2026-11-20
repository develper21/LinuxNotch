"""Live FFT levels from the default audio-output monitor."""

from __future__ import annotations

import math
import re
import subprocess

import gi

from gi.repository import GLib

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
except (ImportError, ValueError):
    Gst = None

RATE = 44_100
BANDS = 512
FLOOR_DB = -60.0
FREQUENCY_LOW = 40.0
FREQUENCY_HIGH = 12_000.0
SPECTRUM_INTERVAL_NS = 33_000_000
STARTUP_TIMEOUT_MS = 2_500


def default_monitor() -> str | None:
    try:
        result = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    sink = result.stdout.strip()
    if result.returncode != 0 or not sink:
        return None
    return f"{sink}.monitor"


def parse_magnitudes(structure) -> list[float] | None:
    if structure is None:
        return None
    try:
        values = structure.get_value("magnitude")
    except (AttributeError, KeyError, TypeError, ValueError):
        values = None
    if values is not None:
        try:
            magnitudes = [_decibel_value(value) for value in values]
        except (TypeError, ValueError):
            magnitudes = []
        if magnitudes:
            return magnitudes

    try:
        serialized = structure.to_string()
    except (AttributeError, TypeError, ValueError):
        return None
    match = re.search(
        r"magnitude=\(float\)\{\s*([^}]*)\}",
        serialized,
    )
    if match is None:
        return None
    try:
        return [
            _decibel_value(item.strip())
            for item in match.group(1).split(",")
            if item.strip()
        ]
    except ValueError:
        return None


def _decibel_value(value) -> float:
    decibels = float(value)
    if math.isnan(decibels) or decibels == -math.inf:
        return FLOOR_DB
    if decibels == math.inf:
        return 0.0
    return decibels


class SpectrumSource:
    def __init__(self, n_bars, on_levels, on_failed):
        self.n_bars = n_bars
        self.on_levels = on_levels
        self.on_failed = on_failed
        self.ranges: list[tuple[int, int]] = []
        self.tilt: list[float] = []
        bin_hz = (RATE / 2) / BANDS
        for index in range(n_bars):
            low = FREQUENCY_LOW * (
                FREQUENCY_HIGH / FREQUENCY_LOW
            ) ** (index / n_bars)
            high = FREQUENCY_LOW * (
                FREQUENCY_HIGH / FREQUENCY_LOW
            ) ** ((index + 1) / n_bars)
            first = min(int(low / bin_hz), BANDS - 1)
            last = min(max(first + 1, int(high / bin_hz)), BANDS)
            self.ranges.append((first, last))
            self.tilt.append(
                2.5 * math.log2(math.sqrt(low * high) / FREQUENCY_LOW)
            )
        self.ref = 0.5
        self._got_data = False
        self._watchdog_id = 0
        self._pipeline = None
        self._bus = None
        self._bus_handlers: tuple[int, ...] = ()

    @property
    def running(self) -> bool:
        return self._pipeline is not None

    @staticmethod
    def available() -> bool:
        if Gst is None:
            return False
        return all(
            Gst.ElementFactory.find(name) is not None
            for name in (
                "pulsesrc",
                "spectrum",
                "audioconvert",
                "audioresample",
                "capsfilter",
                "fakesink",
            )
        )

    def start(self) -> None:
        if self.running:
            return
        if Gst is None:
            self.on_failed("GStreamer is unavailable")
            return
        missing = [
            name for name in (
                "pulsesrc",
                "spectrum",
                "audioconvert",
                "audioresample",
                "capsfilter",
                "fakesink",
            )
            if Gst.ElementFactory.find(name) is None
        ]
        if missing:
            self.on_failed(
                f"Missing GStreamer plugins: {', '.join(missing)}"
            )
            return
        monitor = default_monitor()
        if monitor is None:
            self.on_failed(
                "Could not resolve the default output monitor with pactl"
            )
            return

        try:
            pipeline = Gst.Pipeline.new("linux-notch-spectrum")
            source = Gst.ElementFactory.make("pulsesrc", "output-monitor")
            convert = Gst.ElementFactory.make("audioconvert", "convert")
            resample = Gst.ElementFactory.make("audioresample", "resample")
            caps_filter = Gst.ElementFactory.make("capsfilter", "audio-caps")
            spectrum = Gst.ElementFactory.make("spectrum", "spectrum")
            sink = Gst.ElementFactory.make("fakesink", "discard-audio")
            if pipeline is None or any(
                item is None
                for item in (source, convert, resample, caps_filter, spectrum, sink)
            ):
                self.on_failed("Could not create the GStreamer spectrum pipeline")
                return

            source.set_property("device", monitor)
            source.set_property("buffer-time", 60_000)
            source.set_property("latency-time", 20_000)
            caps_filter.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"audio/x-raw,rate={RATE},channels=2"
                ),
            )
            spectrum.set_property("bands", BANDS)
            spectrum.set_property("threshold", -80.0)
            spectrum.set_property("interval", SPECTRUM_INTERVAL_NS)
            spectrum.set_property("post-messages", True)
            spectrum.set_property("message-magnitude", True)
            sink.set_property("sync", False)

            elements = (source, convert, resample, caps_filter, spectrum, sink)
            for element in elements:
                if not pipeline.add(element):
                    self.on_failed("Could not add an element to the spectrum pipeline")
                    return
            for first, second in zip(elements, elements[1:]):
                if not first.link(second):
                    self.on_failed("Could not link the spectrum pipeline")
                    return

            self._pipeline = pipeline
            self._bus = pipeline.get_bus()
            self._bus.add_signal_watch()
            self._bus_handlers = (
                self._bus.connect("message::element", self._on_element),
                self._bus.connect("message::error", self._on_error),
            )
            self._got_data = False
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                self._fail("GStreamer could not start the output monitor")
                return
            self._watchdog_id = GLib.timeout_add(
                STARTUP_TIMEOUT_MS, self._watchdog)
        except (GLib.Error, OSError, TypeError, ValueError) as error:
            self._fail(f"Could not start real audio sync: {error}")

    def stop(self) -> None:
        if self._watchdog_id:
            GLib.source_remove(self._watchdog_id)
            self._watchdog_id = 0
        pipeline, bus = self._pipeline, self._bus
        handlers = self._bus_handlers
        self._pipeline = None
        self._bus = None
        self._bus_handlers = ()
        if bus is not None:
            for handler_id in handlers:
                bus.disconnect(handler_id)
            bus.remove_signal_watch()
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)

    def _fail(self, reason: str) -> None:
        self.stop()
        self.on_failed(reason)

    def _watchdog(self) -> bool:
        self._watchdog_id = 0
        if self.running and not self._got_data:
            self._fail("No spectrum data arrived within 2.5 seconds")
        return GLib.SOURCE_REMOVE

    def _on_error(self, _bus, message) -> None:
        if not self.running:
            return
        error, _debug = message.parse_error()
        self._fail(f"Output monitor error: {error}")

    def _on_element(self, _bus, message) -> None:
        if not self.running:
            return
        structure = message.get_structure()
        if structure is None or structure.get_name() != "spectrum":
            return
        magnitudes = parse_magnitudes(structure)
        if not magnitudes:
            return
        self._got_data = True
        levels = []
        for (first, last), tilt in zip(self.ranges, self.tilt):
            band = magnitudes[first:min(last, len(magnitudes))]
            if not band:
                levels.append(0.0)
                continue
            decibels = max(band) + tilt
            level = min(1.0, max(0.0, (decibels - FLOOR_DB) / -FLOOR_DB))
            levels.append(level)
        self.ref = max(max(levels), self.ref * 0.995, 0.25)
        self.on_levels([
            min(1.0, level / self.ref) ** 1.3 for level in levels
        ])
