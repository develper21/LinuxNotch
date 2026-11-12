import os
import tempfile
import unittest
from unittest import mock

from linux_notch import config


class ConfigTest(unittest.TestCase):
    def test_merge_keeps_defaults_for_missing_keys(self):
        merged = config._merge(config.DEFAULTS, {"margin_top": 20})
        self.assertEqual(merged["margin_top"], 20)
        self.assertEqual(merged["layer"], config.DEFAULTS["layer"])

    def test_merge_is_deep_for_modules(self):
        merged = config._merge(config.DEFAULTS, {"modules": {"music": False}})
        self.assertFalse(merged["modules"]["music"])
        self.assertTrue(merged["modules"]["battery"])

    def test_defaults_survive_broken_config(self):
        self.assertEqual(config._merge(config.DEFAULTS, {}), config.DEFAULTS)

    def test_todo_list_is_enabled_and_empty_by_default(self):
        merged = config._merge(config.DEFAULTS, {})
        self.assertTrue(merged["modules"]["todos"])
        self.assertEqual(merged["todos"], [])

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
