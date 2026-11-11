"""Hand-drawn Cairo widget for the battery ring."""

from __future__ import annotations

import math

from gi.repository import Gtk


class BatteryRing(Gtk.DrawingArea):
    """Charge level as a ring, accent-colored when charging."""

    def __init__(self, accent=(1.0, 0.62, 0.04)):
        super().__init__()
        self.accent = accent
        self.percent = 0.0
        self.charging = False
        self.set_content_width(40)
        self.set_content_height(40)
        self.set_draw_func(self._draw)

    def update(self, percent: float, charging: bool):
        self.percent = percent
        self.charging = charging
        self.queue_draw()

    def _draw(self, area, cr, w, h):
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 3
        cr.set_line_width(3.5)
        cr.set_line_cap(1)  # ROUND
        # track
        cr.set_source_rgba(1, 1, 1, 0.13)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        # level, from 12 o'clock
        if self.charging:
            cr.set_source_rgb(*self.accent)
        elif self.percent <= 20:
            cr.set_source_rgb(1.0, 0.27, 0.23)
        else:
            cr.set_source_rgb(0.20, 0.84, 0.29)
        start = -math.pi / 2
        cr.arc(cx, cy, radius, start, start + 2 * math.pi * max(0.01, self.percent / 100))
        cr.stroke()


def pick_icon(widget, *names: str) -> str:
    """First icon name the current theme actually ships (breeze and adwaita
    disagree on several battery/bluetooth names)."""
    theme = Gtk.IconTheme.get_for_display(widget.get_display())
    for name in names:
        if theme.has_icon(name):
            return name
    return names[-1]
