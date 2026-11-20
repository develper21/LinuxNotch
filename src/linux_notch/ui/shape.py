from __future__ import annotations

import math
from typing import Literal, TypedDict

import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402
from linux_notch.ui.theme import ACTIVE, get_palette, rgb  # noqa: E402


ShapeFill = Literal["island", "pill"]


class ShapeGeometry(TypedDict):
    width: float
    height: float
    radius: float
    ear: float


class IslandShape(Gtk.DrawingArea):
    def __init__(
        self,
        geometry: ShapeGeometry,
        opacity: float = 1.0,
        palette_name: str = ACTIVE,
        fill: ShapeFill = "pill",
    ):
        super().__init__()
        self.geometry = dict(geometry)
        self.opacity = min(1.0, max(0.0, opacity))
        self.palette_name = palette_name
        self.fill = fill
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

    def set_palette(
        self,
        name: str,
        fill: ShapeFill | None = None,
    ) -> None:
        self.palette_name = name
        if fill is not None:
            self.fill = fill
        self.queue_draw()

    def _draw(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        palette = get_palette(self.palette_name)
        draw_island_shape(
            cr,
            width,
            height,
            self.geometry["radius"],
            self.geometry["ear"],
            self.opacity,
            fill_color=rgb(palette[self.fill]),
            border_color=rgb(palette["border"]),
            palette_alpha=palette["alpha"],
        )


def draw_island_shape(
    cr: cairo.Context,
    width: float,
    height: float,
    radius: float,
    ear: float,
    opacity: float = 1.0,
    fill_color: tuple[float, float, float] = (0, 0, 0),
    border_color: tuple[float, float, float] | None = None,
    palette_alpha: float = 1.0,
) -> None:
    """Draw the island as a rounded capsule/rectangle without shoulder cutouts."""
    if width <= 0 or height <= 0:
        return

    inset = 0.5 if border_color is not None else 0.0
    drawable_width = max(0.0, width - inset * 2)
    drawable_height = max(0.0, height - inset * 2)
    radius = min(
        max(radius, 0),
        drawable_width / 2,
        drawable_height / 2,
    )

    cr.new_path()
    cr.arc(
        inset + drawable_width - radius,
        inset + radius,
        radius,
        -math.pi / 2,
        0,
    )
    cr.arc(
        inset + drawable_width - radius,
        inset + drawable_height - radius,
        radius,
        0,
        math.pi / 2,
    )
    cr.arc(
        inset + radius,
        inset + drawable_height - radius,
        radius,
        math.pi / 2,
        math.pi,
    )
    cr.arc(
        inset + radius,
        inset + radius,
        radius,
        math.pi,
        1.5 * math.pi,
    )
    cr.close_path()
    alpha = min(1.0, max(0.0, opacity * palette_alpha))
    cr.set_source_rgba(*fill_color, alpha)
    if border_color is None:
        cr.fill()
        return
    cr.fill_preserve()
    cr.set_source_rgba(*border_color, alpha)
    cr.set_line_width(1.0)
    cr.stroke()
