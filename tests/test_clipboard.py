import os
import tempfile
import unittest

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GdkPixbuf, GObject  # noqa: E402

from linux_notch.services.clipboard import ClipboardHistoryService  # noqa: E402


class FakeClipboard(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.text = None
        self.texture = None

    def read_text_async(self, _cancellable, callback, user_data):
        callback(self, self.text, user_data)

    def read_text_finish(self, result):
        return result

    def read_texture_async(self, _cancellable, callback, user_data):
        callback(self, self.texture, user_data)

    def read_texture_finish(self, result):
        return result


class ClipboardHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.clipboard = FakeClipboard()
        self.service = ClipboardHistoryService(
            self.clipboard, self.temp_dir.name, max_items=3,
            max_image_bytes=1024)

    def tearDown(self):
        self.service.set_recording(False)
        self.temp_dir.cleanup()

    def test_recording_is_explicitly_paused_until_enabled(self):
        self.assertFalse(self.service.recording)
        self.service.set_recording(True)
        self.assertTrue(self.service.recording)
        self.service.set_recording(False)
        self.assertFalse(self.service.recording)

    def test_changed_clipboard_is_recorded_only_while_unpaused(self):
        self.service.set_recording(True)
        self.clipboard.text = "recorded"
        self.clipboard.emit("changed")
        self.assertEqual(self.service.list_items()[0].content, "recorded")

        self.service.set_recording(False)
        self.clipboard.text = "ignored while paused"
        self.clipboard.emit("changed")
        self.assertEqual(len(self.service.list_items()), 1)

    def test_non_text_clipboard_content_is_saved_as_an_image(self):
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
        pixbuf.fill(0xffffffff)
        self.clipboard.texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        self.service.set_recording(True)
        self.clipboard.emit("changed")

        item = self.service.list_items()[0]
        self.assertEqual(item.kind, "image")
        self.assertTrue(os.path.isfile(item.content))

    def test_text_deduplicates_and_history_is_capped(self):
        self.assertTrue(self.service.record_text("first"))
        self.assertFalse(self.service.record_text("first"))
        self.service.record_text("second")
        self.service.record_text("third")
        self.service.record_text("fourth")

        self.assertEqual(
            [item.content for item in self.service.list_items()],
            ["fourth", "third", "second"],
        )

    def test_clear_removes_text_from_persistent_database_files(self):
        self.service.record_text("private-clipboard-entry")
        self.service.clear()

        for name in os.listdir(self.temp_dir.name):
            with open(os.path.join(self.temp_dir.name, name), "rb") as file:
                self.assertNotIn(b"private-clipboard-entry", file.read())

    def test_pinned_entries_survive_retention_before_recent_items(self):
        self.service.record_text("keep")
        keep = self.service.list_items()[0]
        self.service.set_pinned(keep.id, True)
        self.service.record_text("second")
        self.service.record_text("third")
        self.service.record_text("fourth")

        items = self.service.list_items()
        self.assertEqual([item.content for item in items], [
            "keep", "fourth", "third",
        ])
        self.assertTrue(items[0].pinned)

    def test_images_are_saved_locally_and_removed_by_clear(self):
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
        pixbuf.fill(0xffffffff)
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        self.assertTrue(self.service.record_texture(texture))
        item = self.service.list_items()[0]
        self.assertEqual(item.kind, "image")
        self.assertTrue(os.path.isfile(item.content))
        self.service.clear()
        self.assertFalse(os.path.exists(item.content))
        self.assertEqual(self.service.list_items(), [])

    def test_identical_images_are_deduplicated(self):
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
        pixbuf.fill(0xffffffff)
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)

        self.assertTrue(self.service.record_texture(texture))
        self.assertFalse(self.service.record_texture(texture))
        self.assertEqual(len(self.service.list_items()), 1)

    def test_image_pixel_limit_is_enforced(self):
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, True, 8, 20, 20)
        self.assertFalse(
            self.service.record_texture(Gdk.Texture.new_for_pixbuf(pixbuf)))
        self.assertEqual(self.service.list_items(), [])


if __name__ == "__main__":
    unittest.main()
