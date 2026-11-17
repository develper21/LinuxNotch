from __future__ import annotations

import math
from typing import TypedDict

import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class ShapeGeometry(TypedDict):
    width: float
    height: float
    radius: float
    ear: float


class IslandShape(Gtk.DrawingArea):
    def __init__(self, geometry: ShapeGeometry, opacity: float = 1.0):
        super().__init__()
        self.geometry = dict(geometry)
        self.opacity = min(1.0, max(0.0, opacity))
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_draw_func(self._draw)
        self.set_geometry(geometry)

    def set_geometry(self, geometry: ShapeGeometry) -> None:
        self.geometry = dict(geometry)
        width = max(1, round(geometry["width"]))
        height = max(1, round(geometry["height"]))
        self.set_content_width(width)
        self.set_content_height(height)
        self.set_size_request(width, height)
        self.queue_draw()

    def set_opacity(self, opacity: float) -> None:
        self.opacity = min(1.0, max(0.0, opacity))
        self.queue_draw()

    def _draw(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        draw_island_shape(
            cr,
            width,
            height,
            self.geometry["radius"],
            self.geometry["ear"],
            self.opacity,
        )


def draw_island_shape(
    cr: cairo.Context,
    width: float,
    height: float,
    radius: float,
    ear: float,
    opacity: float = 1.0,
) -> None:
    """Draw the island as a rounded capsule/rectangle without shoulder cutouts."""
    if width <= 0 or height <= 0:
        return

    radius = min(max(radius, 0), width / 2, height / 2)

    cr.new_path()
    cr.arc(width - radius, radius, radius, -math.pi / 2, 0)
    cr.arc(width - radius, height - radius, radius, 0, math.pi / 2)
    cr.arc(radius, height - radius, radius, math.pi / 2, math.pi)
    cr.arc(radius, radius, radius, math.pi, 1.5 * math.pi)
    cr.close_path()
    cr.set_source_rgba(0, 0, 0, min(1.0, max(0.0, opacity)))
    cr.fill()
