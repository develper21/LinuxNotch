import os
import tempfile
import unittest
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from linux_notch import config  # noqa: E402
from linux_notch.ui.theme import (  # noqa: E402
    ACTIVE,
    CHARACTER,
    EQUALIZER_PALETTE,
    PALETTE_LABELS,
    PALETTES,
    css_definitions,
    get_palette,
    rgb,
)

CSS_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "src",
    "linux_notch",
    "ui",
    "style.css",
)


class ThemeTests(unittest.TestCase):
    def test_default_and_palette_colors_match_the_theme_plan(self):
        self.assertEqual(config.DEFAULTS["notch_theme"], ACTIVE)
        self.assertEqual(PALETTES["soft_black"]["island"], "#0d0d10")
        self.assertEqual(PALETTES["soft_black"]["border"], "#26262c")
        self.assertEqual(PALETTES["soft_black"]["card"], "#17171b")
        self.assertEqual(PALETTES["soft_black"]["pill"], "#202026")
        self.assertEqual(PALETTES["smoked_glass"]["alpha"], 0.72)
        self.assertEqual(CHARACTER, "#f5a25d")
        self.assertEqual(
            EQUALIZER_PALETTE,
            ("#ff5c8a", "#ffb347", "#4dd8ff"),
        )

    def test_rgb_parses_hex_and_rejects_invalid_values(self):
        self.assertEqual(
            rgb("#ff8000"),
            (1.0, 128 / 255, 0.0),
        )
        with self.assertRaises(ValueError):
            rgb("not-a-color")

    def test_unknown_palette_falls_back_to_soft_black(self):
        self.assertEqual(get_palette("missing"), PALETTES[ACTIVE])

    def test_theme_stylesheet_parses_for_each_palette(self):
        if not Gtk.init_check():
            self.skipTest("GTK display unavailable")
        with open(CSS_PATH, encoding="utf-8") as stylesheet:
            base_css = stylesheet.read()

        for name in PALETTES:
            with self.subTest(palette=name):
                provider = Gtk.CssProvider()
                errors = []
                provider.connect(
                    "parsing-error",
                    lambda _provider, _section, error: errors.append(str(error)),
                )
                css = css_definitions(name) + base_css
                provider.load_from_data(css.encode("utf-8"))
                self.assertEqual(errors, [])

    def test_settings_picker_saves_theme_and_applies_without_rebuild(self):
        if not Gtk.init_check():
            self.skipTest("GTK display unavailable")
        cfg = config._merge(config.DEFAULTS, {})
        applied = []
        from linux_notch.ui.settings import SettingsPanel

        panel = SettingsPanel(cfg, lambda structural: applied.append(structural))

        def descendants(widget):
            child = widget.get_first_child()
            while child is not None:
                yield child
                yield from descendants(child)
                child = child.get_next_sibling()

        picker = next(
            child for child in descendants(panel)
            if isinstance(child, Adw.ComboRow)
            and child.get_title() == "Notch color theme"
        )
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(config, "CONFIG_DIR", directory),
                patch.object(
                    config,
                    "CONFIG_PATH",
                    os.path.join(directory, "config.json"),
                ),
            ):
                picker.set_selected(tuple(PALETTE_LABELS).index("pure_black"))
                self.assertEqual(config.load()["notch_theme"], "pure_black")

        self.assertEqual(cfg["notch_theme"], "pure_black")
        self.assertEqual(applied, [False])


if __name__ == "__main__":
    unittest.main()
