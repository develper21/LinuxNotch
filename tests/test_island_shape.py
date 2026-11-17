import unittest

import cairo

from linux_notch.ui.shape import draw_island_shape


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


if __name__ == "__main__":
    unittest.main()
