import unittest
from datetime import date

import cairo

from linux_notch.ui.mochi import (
    MOODS,
    OUTFITS,
    draw_mochi,
    mood_for_activity,
    seasonal_outfit,
    sound_for_activity,
)


class MochiTests(unittest.TestCase):
    def test_activity_states_map_to_character_moods(self):
        examples = {
            "running": "working",
            "needs-approval": "approval",
            "waiting-for-input": "approval",
            "question": "question",
            "failed": "error",
            "completed": "finished",
            "searching": "searching",
            "thinking": "thinking",
            "rate-limit": "ratelimit",
            "sleeping": "sleeping",
            "love": "love",
            "wink": "wink",
            "approved": "finished",
            "cancelled": "error",
            "unrecognized": "working",
        }
        for state, mood in examples.items():
            with self.subTest(state=state):
                self.assertEqual(mood_for_activity({"state": state}), mood)
        self.assertEqual(mood_for_activity(None), "idle")
        self.assertEqual(mood_for_activity({"state": "approved"}), "finished")
        self.assertEqual(sound_for_activity({"state": "approved"}, "finished"), "approve")
        self.assertEqual(sound_for_activity({"state": "complete"}, "finished"), "finish")

    def test_seasonal_outfits_follow_the_calendar(self):
        self.assertEqual(seasonal_outfit(date(2026, 12, 31)), "partyHat")
        self.assertEqual(seasonal_outfit(date(2026, 12, 20)), "santaHat")
        self.assertEqual(seasonal_outfit(date(2026, 10, 12)), "witchHat")
        self.assertEqual(seasonal_outfit(date(2026, 6, 21)), "sunglasses")
        self.assertEqual(seasonal_outfit(date(2026, 4, 3)), "bunnyEars")
        self.assertEqual(seasonal_outfit(date(2026, 5, 15)), "none")

    def test_every_mood_and_outfit_renders_to_cairo_surface(self):
        outfits = [name for name, _label in OUTFITS]
        self.assertEqual(len(outfits), 13)
        self.assertEqual(len(MOODS), 15)
        for mood in MOODS:
            for outfit in outfits:
                with self.subTest(mood=mood, outfit=outfit):
                    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 58, 55)
                    draw_mochi(cairo.Context(surface), 58, 55, mood, outfit, 0.8)
                    surface.flush()


if __name__ == "__main__":
    unittest.main()
