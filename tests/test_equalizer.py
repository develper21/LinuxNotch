import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cairo

from linux_notch.ui.equalizer import (
    DEFAULT_PALETTE,
    Equalizer,
    HEIGHT,
    WIDTH,
    dominant_art_palette,
)


class EqualizerPaletteTests(unittest.TestCase):
    def test_artwork_palette_picks_distinct_saturated_colors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cover.png"
            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 16, 16)
            context = cairo.Context(surface)
            context.set_source_rgb(0.9, 0.08, 0.12)
            context.rectangle(0, 0, 8, 16)
            context.fill()
            context.set_source_rgb(0.08, 0.75, 0.9)
            context.rectangle(8, 0, 8, 16)
            context.fill()
            surface.write_to_png(str(path))

            palette = dominant_art_palette(str(path))

        self.assertEqual(len(palette), 2)
        self.assertTrue(any(color[0] > color[1] for color in palette))
        self.assertTrue(any(color[2] > color[0] for color in palette))

    def test_neutral_or_unavailable_artwork_uses_the_fixed_gradient(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "neutral.png"
            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 16, 16)
            context = cairo.Context(surface)
            context.set_source_rgb(0.5, 0.5, 0.5)
            context.paint()
            surface.write_to_png(str(path))

            self.assertEqual(dominant_art_palette(str(path)), DEFAULT_PALETTE)

        self.assertEqual(dominant_art_palette("/missing/cover.png"), DEFAULT_PALETTE)

    def test_equalizer_size_stays_fixed(self):
        self.assertEqual((WIDTH, HEIGHT), (96, 20))

    def test_external_levels_replace_synthetic_targets_when_available(self):
        equalizer = SimpleNamespace(
            external=[index / 14 for index in range(14)])

        self.assertAlmostEqual(
            Equalizer._target_level(equalizer, 7, 0.5),
            0.5,
        )

    def test_missing_external_levels_keep_synthetic_targets(self):
        equalizer = SimpleNamespace(
            external=None,
            _phases=[0.0],
            _speeds=[1.0],
            _random=SimpleNamespace(uniform=lambda _low, _high: 0.0),
        )

        self.assertEqual(
            Equalizer._target_level(equalizer, 0, 0.0),
            0.5,
        )


if __name__ == "__main__":
    unittest.main()
