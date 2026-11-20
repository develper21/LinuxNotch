import unittest
import sys

import cairo

from linux_notch.ui.shape import draw_island_shape
from linux_notch.ui.theme import PALETTES, rgb


class IslandShapeTests(unittest.TestCase):
    def test_capsule_has_smooth_rounded_corners_without_shoulder_cutouts(self):
        width, height = 260, 34
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()

        draw_island_shape(context, width, height, radius=height / 2, ear=10)
        surface.flush()
        pixels = memoryview(surface.get_data())
        stride = surface.get_stride()

        def alpha_at(x, y):
            return pixels[y * stride + x * 4 + 3]

        self.assertEqual(alpha_at(1, 1), 0)
        self.assertEqual(alpha_at(width - 2, 1), 0)
        self.assertEqual(alpha_at(1, height - 1), 0)
        self.assertEqual(alpha_at(width - 2, height - 1), 0)
        self.assertEqual(alpha_at(width // 2, height // 2), 255)
        self.assertEqual(alpha_at(8, 1), 0)
        self.assertEqual(alpha_at(width - 9, 1), 0)
        self.assertEqual(alpha_at(width // 2, 1), 255)
        self.assertEqual(alpha_at(width // 2, height - 1), 255)

    def test_theme_fill_and_border_are_painted_separately(self):
        palette = PALETTES["soft_black"]
        width, height = 100, 40
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()

        draw_island_shape(
            context,
            width,
            height,
            radius=12,
            ear=8,
            fill_color=rgb(palette["island"]),
            border_color=rgb(palette["border"]),
        )
        surface.flush()
        pixels = memoryview(surface.get_data())
        stride = surface.get_stride()

        def rgba_at(x, y):
            pixel = int.from_bytes(
                pixels[y * stride + x * 4:y * stride + x * 4 + 4],
                sys.byteorder,
            )
            return (
                (pixel >> 16) & 255,
                (pixel >> 8) & 255,
                pixel & 255,
                (pixel >> 24) & 255,
            )

        self.assertEqual(rgba_at(width // 2, height // 2), (13, 13, 16, 255))
        self.assertEqual(rgba_at(width // 2, 0), (38, 38, 44, 255))


if __name__ == "__main__":
    unittest.main()
