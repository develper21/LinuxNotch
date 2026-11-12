import unittest

import gi

gi.require_version("Gtk", "4.0")

from linux_notch.ui.expanded import FEATURES, HOME_FEATURES  # noqa: E402


class ExpandedFeatureLayoutTests(unittest.TestCase):
    def test_home_keeps_four_shortcuts_and_todo_is_in_all_features(self):
        feature_ids = {feature[0] for feature in FEATURES}
        self.assertEqual(len(HOME_FEATURES), 4)
        self.assertTrue(set(HOME_FEATURES).issubset(feature_ids))
        self.assertIn("todos", feature_ids)
        self.assertNotIn("todos", HOME_FEATURES)


if __name__ == "__main__":
    unittest.main()
