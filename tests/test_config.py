import os
import tempfile
import unittest
from unittest import mock

from linux_notch import config


class ConfigTest(unittest.TestCase):
    def test_merge_keeps_defaults_for_missing_keys(self):
        merged = config._merge(config.DEFAULTS, {"margin_bottom": 20})
        self.assertEqual(merged["margin_bottom"], 20)
        self.assertEqual(merged["layer"], config.DEFAULTS["layer"])

    def test_legacy_top_margin_is_migrated_to_bottom_margin(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "config.json")
            with open(config_path, "w") as saved:
                saved.write('{"margin_top": 17}')
            with (
                mock.patch.object(config, "CONFIG_PATH", config_path),
            ):
                self.assertEqual(config.load()["margin_bottom"], -11)

    def test_merge_is_deep_for_modules(self):
        merged = config._merge(config.DEFAULTS, {"modules": {"music": False}})
        self.assertFalse(merged["modules"]["music"])
        self.assertTrue(merged["modules"]["battery"])

    def test_defaults_survive_broken_config(self):
        self.assertEqual(config._merge(config.DEFAULTS, {}), config.DEFAULTS)
        self.assertEqual(config.DEFAULTS["notch_theme"], "soft_black")

    def test_todo_list_is_enabled_and_empty_by_default(self):
        merged = config._merge(config.DEFAULTS, {})
        self.assertTrue(merged["modules"]["todos"])
        self.assertTrue(merged["modules"]["music"])
        self.assertEqual(merged["music_directory"], "~/Music")
        self.assertEqual(merged["todos"], [])
        self.assertTrue(merged["modules"]["face"])
        self.assertTrue(merged["modules"]["terminal"])
        self.assertTrue(merged["modules"]["screen_time"])
        self.assertTrue(merged["face_enabled"])
        self.assertEqual(merged["face_threshold"], 0.45)
        self.assertFalse(merged["face_challenge"])
        self.assertEqual(merged["viz_mode"], "auto")

    def test_face_settings_persist_across_config_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(config, "CONFIG_DIR", directory),
                mock.patch.object(
                    config, "CONFIG_PATH", os.path.join(directory, "config.json")),
            ):
                config.save({
                    **config.DEFAULTS,
                    "face_enabled": False,
                    "face_threshold": 0.55,
                    "face_challenge": True,
                })
                loaded = config.load()
                self.assertFalse(loaded["face_enabled"])
                self.assertEqual(loaded["face_threshold"], 0.55)
                self.assertTrue(loaded["face_challenge"])

    def test_visualizer_mode_persists_across_config_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(config, "CONFIG_DIR", directory),
                mock.patch.object(
                    config, "CONFIG_PATH", os.path.join(directory, "config.json")),
            ):
                config.save({**config.DEFAULTS, "viz_mode": "synthetic"})

                self.assertEqual(config.load()["viz_mode"], "synthetic")

    def test_mail_account_default_never_contains_an_app_password(self):
        self.assertEqual(config.DEFAULTS["mail_account"], "")
        self.assertNotIn("mail_password", config.DEFAULTS)

    def test_todo_tasks_persist_across_config_loads(self):
        tasks = [{"id": "task-1", "text": "Test persistence", "completed": True}]
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(config, "CONFIG_DIR", directory),
                mock.patch.object(
                    config, "CONFIG_PATH", os.path.join(directory, "config.json")),
            ):
                config.save({**config.DEFAULTS, "todos": tasks})
                self.assertEqual(config.load()["todos"], tasks)


if __name__ == "__main__":
    unittest.main()
