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
    """Draw the top-attached silhouette with concave upper shoulders."""
    if width <= 0 or height <= 0:
        return

    ear = min(max(ear, 0), width / 2)
    radius = min(max(radius, 0), (width - 2 * ear) / 2, height / 2)

    cr.new_path()
    if ear:
        cr.move_to(0, 0)
        cr.arc(0, ear, ear, -math.pi / 2, 0)
        cr.line_to(ear, height - radius)
    else:
        cr.move_to(0, 0)
        cr.line_to(0, height - radius)

    if radius:
        cr.arc_negative(
            ear + radius,
            height - radius,
            radius,
            math.pi,
            math.pi / 2,
        )
    else:
        cr.line_to(ear, height)

    cr.line_to(width - ear - radius, height)
    if radius:
        cr.arc_negative(
            width - ear - radius,
            height - radius,
            radius,
            math.pi / 2,
            0,
        )
    else:
        cr.line_to(width - ear, height)

    if ear:
        cr.line_to(width - ear, ear)
        cr.arc(width, ear, ear, math.pi, 1.5 * math.pi)
    else:
        cr.line_to(width, 0)

    cr.close_path()
    cr.set_source_rgba(0, 0, 0, min(1.0, max(0.0, opacity)))
    cr.fill()
