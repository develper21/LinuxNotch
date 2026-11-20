"""Compact segmented equalizer animated from local playback state."""

from __future__ import annotations

import colorsys
import math
import random
import time

import cairo
import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402

from linux_notch.ui.theme import EQUALIZER_PALETTE, rgb  # noqa: E402

BAR_COUNT = 14
SEGMENT_COUNT = 7
WIDTH = 96
HEIGHT = 20
PAUSE_HOLD_SECONDS = 1.5
PALETTE_TRANSITION_SECONDS = 0.3
DEFAULT_PALETTE = tuple(rgb(color) for color in EQUALIZER_PALETTE)


def _interpolate_palette(start, end, amount: float):
    return tuple(
        tuple(a + (b - a) * amount for a, b in zip(start_color, end_color))
        for start_color, end_color in zip(start, end)
    )


def dominant_art_palette(path: str) -> tuple[tuple[float, float, float], ...]:
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 16, 16, True)
    except GLib.Error:
        return DEFAULT_PALETTE

    pixels = pixbuf.get_pixels()
    channels = pixbuf.get_n_channels()
    rowstride = pixbuf.get_rowstride()
    buckets: dict[tuple[int, int, int], list[float]] = {}
    for y in range(pixbuf.get_height()):
        for x in range(pixbuf.get_width()):
            offset = y * rowstride + x * channels
            if channels == 4 and pixels[offset + 3] < 128:
                continue
            red, green, blue = pixels[offset:offset + 3]
            maximum = max(red, green, blue)
            minimum = min(red, green, blue)
            saturation = (maximum - minimum) / max(1, maximum)
            if maximum < 48 or saturation < 0.18:
                continue
            key = (red // 32, green // 32, blue // 32)
            bucket = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0])
            bucket[0] += 1
            bucket[1] += red
            bucket[2] += green
            bucket[3] += blue

    if not buckets:
        return DEFAULT_PALETTE

    candidates = []
    for count, red_sum, green_sum, blue_sum in buckets.values():
        rgb = (
            red_sum / count / 255,
            green_sum / count / 255,
            blue_sum / count / 255,
        )
        hue = colorsys.rgb_to_hsv(*rgb)[0]
        candidates.append((count, hue, rgb))
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)

    chosen = []
    for _count, _hue, color in candidates:
        if all(
            sum((a - b) ** 2 for a, b in zip(color, existing)) >= 0.08
            for existing in chosen
        ):
            chosen.append(color)
            if len(chosen) == 3:
                break
    if len(chosen) < 2:
        return DEFAULT_PALETTE

    return tuple(sorted(chosen, key=lambda color: colorsys.rgb_to_hsv(*color)[0]))


class Equalizer(Gtk.DrawingArea):
    """A fixed-size 14 by 7 LED equalizer with synthetic playback motion."""

    def __init__(self, on_idle=None):
        super().__init__()
        self.set_content_width(WIDTH)
        self.set_content_height(HEIGHT)
        self.set_size_request(WIDTH, HEIGHT)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_opacity(0.0)
        self.set_draw_func(self._draw)
        self._random = random.Random(2026)
        self._phases = [self._random.uniform(0, math.tau) for _ in range(BAR_COUNT)]
        self._speeds = [self._random.uniform(1.5, 4.0) for _ in range(BAR_COUNT)]
        self._levels = [0.0] * BAR_COUNT
        self._peaks = [0.0] * BAR_COUNT
        self.external: list[float] | None = None
        self._status = "Stopped"
        self._paused_at = 0.0
        self._started_at = time.monotonic()
        self._last_frame = self._started_at
        self._timer = 0
        self._surface_visible = False
        self._on_idle = on_idle
        self._idle_notified = True
        self._art_path: str | None = None
        self._palette = DEFAULT_PALETTE
        self._palette_start = DEFAULT_PALETTE
        self._palette_target = DEFAULT_PALETTE
        self._palette_changed_at = 0.0
        self.connect("map", lambda *_: self._ensure_timer())
        self.connect("unmap", lambda *_: self._stop_timer())

    @property
    def playback_status(self) -> str:
        return self._status

    @property
    def animating(self) -> bool:
        return bool(self._timer)

    def set_surface_visible(self, visible: bool) -> None:
        self._surface_visible = visible
        if visible:
            self._ensure_timer()
        else:
            self._stop_timer()

    def set_playback_status(self, status: str) -> bool:
        if status not in {"Playing", "Paused", "Stopped"}:
            status = "Stopped"
        now = time.monotonic()
        changed = status != self._status
        previous = self._status
        self._status = status
        self._last_frame = now

        if status == "Playing":
            self._started_at = now
            self._idle_notified = False
        elif status == "Paused" and changed:
            self._paused_at = now
        elif status == "Stopped" and previous != "Stopped":
            self._paused_at = now - PAUSE_HOLD_SECONDS

        if changed and self._surface_visible:
            self._ensure_timer()
        return status == "Playing" or self.animating

    def set_artwork(self, path: str | None) -> None:
        path = path or ""
        if path == self._art_path:
            return
        self._art_path = path
        target = dominant_art_palette(path) if path else DEFAULT_PALETTE
        if len(target) == 2:
            target = (target[0], target[1], target[0])
        elif len(target) == 1:
            target = (target[0],) * 3
        current = self._current_palette(time.monotonic())
        self._palette_start = current
        self._palette_target = tuple(target)
        self._palette_changed_at = time.monotonic()
        self._ensure_timer()
        self.queue_draw()

    def _current_palette(self, now: float):
        if self._palette_changed_at == 0:
            return self._palette
        amount = min(
            1.0,
            max(0.0, (now - self._palette_changed_at)
                / PALETTE_TRANSITION_SECONDS),
        )
        self._palette = _interpolate_palette(
            self._palette_start, self._palette_target, amount)
        if amount >= 1:
            self._palette_changed_at = 0
        return self._palette

    def _ensure_timer(self) -> None:
        if (
            not self._timer
            and self._surface_visible
            and self.get_mapped()
            and (self._status != "Stopped" or self.get_opacity() > 0)
        ):
            self._last_frame = time.monotonic()
            self._timer = GLib.timeout_add(33, self._tick)

    def _stop_timer(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _target_level(self, index: int, elapsed: float) -> float:
        if self.external is not None and len(self.external) == BAR_COUNT:
            return min(1.0, max(0.0, self.external[index]))
        phase = self._phases[index]
        speed = self._speeds[index]
        target = (
            0.5
            + 0.35 * math.sin(elapsed * speed + phase)
            + 0.2 * math.sin(elapsed * speed * 0.37 + 2 * phase)
            + self._random.uniform(-0.08, 0.08)
        )
        return min(1.0, max(0.08, target))

    def _tick(self) -> bool:
        if not self._surface_visible or not self.get_mapped():
            self._timer = 0
            return GLib.SOURCE_REMOVE

        now = time.monotonic()
        dt = min(0.08, max(0.0, now - self._last_frame))
        self._last_frame = now
        opacity = self.get_opacity()

        if self._status == "Playing":
            elapsed = now - self._started_at
            opacity = min(1.0, opacity + dt / 0.18)
            for index in range(BAR_COUNT):
                target = self._target_level(index, elapsed)
                rate = 18.0 if target > self._levels[index] else 1.4
                self._levels[index] += (
                    target - self._levels[index]
                ) * min(1.0, dt * rate)
                self._peaks[index] = max(
                    self._levels[index],
                    self._peaks[index] - dt * 0.6,
                )
        else:
            for index in range(BAR_COUNT):
                self._levels[index] = max(
                    0.0, self._levels[index] - dt * 1.4)
                self._peaks[index] = max(
                    self._levels[index],
                    self._peaks[index] - dt * 0.6,
                )
            fade_started = (
                self._status == "Stopped"
                or now - self._paused_at >= PAUSE_HOLD_SECONDS
            )
            if fade_started:
                opacity = max(0.0, opacity - dt / 0.18)

        self.set_opacity(opacity)
        self._current_palette(now)
        self.queue_draw()

        if self._status != "Playing" and opacity <= 0.0:
            self._timer = 0
            if not self._idle_notified:
                self._idle_notified = True
                if self._on_idle is not None:
                    self._on_idle()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        palette = self._current_palette(time.monotonic())
        bar_width = 4.0
        segment_height = 2.0
        segment_gap = 1.0
        bar_gap = 2.0
        total_width = BAR_COUNT * bar_width + (BAR_COUNT - 1) * bar_gap
        left = (width - total_width) / 2
        pitch = segment_height + segment_gap

        for index, level in enumerate(self._levels):
            lit = min(SEGMENT_COUNT, round(level * SEGMENT_COUNT))
            peak_segment = min(
                SEGMENT_COUNT - 1,
                round(self._peaks[index] * SEGMENT_COUNT) - 1,
            )
            color = self._color_for_bar(index, palette)
            x = left + index * (bar_width + bar_gap)
            for segment in range(SEGMENT_COUNT):
                if segment >= lit and segment != peak_segment:
                    continue
                y = height - segment_height - segment * pitch
                alpha = 0.42 if segment == peak_segment and segment >= lit else 1.0
                cr.set_source_rgba(*color, alpha)
                cr.rectangle(x, y, bar_width, segment_height)
                cr.fill()

    @staticmethod
    def _color_for_bar(index: int, palette):
        position = index / max(1, BAR_COUNT - 1)
        scaled = position * (len(palette) - 1)
        first = min(len(palette) - 2, int(scaled))
        amount = scaled - first
        return tuple(
            a + (b - a) * amount
            for a, b in zip(palette[first], palette[first + 1])
        )
