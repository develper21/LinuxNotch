import copy
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from linux_notch import config  # noqa: E402
from linux_notch.services.mail import MailMessage, MailSummary  # noqa: E402
from linux_notch.ui.expanded import (  # noqa: E402
    Expanded,
    ALL_FEATURE_COLUMNS,
    FEATURES,
    HOME_FEATURES,
    HOME_FEATURE_COLUMNS,
)


class ExpandedFeatureLayoutTests(unittest.TestCase):
    def test_home_shortcuts_include_all_requested_features(self):
        feature_ids = {feature[0] for feature in FEATURES}
        self.assertEqual(HOME_FEATURE_COLUMNS, 4)
        self.assertEqual(ALL_FEATURE_COLUMNS, 4)
        self.assertTrue(set(HOME_FEATURES).issubset(feature_ids))
        self.assertEqual(len(HOME_FEATURES), len(FEATURES))
        self.assertIn("music", HOME_FEATURES)
        self.assertIn("todos", feature_ids)
        self.assertIn("todos", HOME_FEATURES)
        self.assertIn("face", feature_ids)
        self.assertIn("face", HOME_FEATURES)
        self.assertIn("terminal", feature_ids)
        self.assertIn("terminal", HOME_FEATURES)

    def test_music_page_replaces_spotify_in_feature_shortcuts(self):
        feature_ids = {feature[0] for feature in FEATURES}
        self.assertIn("music", feature_ids)
        self.assertNotIn("spotify", feature_ids)
        self.assertNotIn("spotify", HOME_FEATURES)

    def test_terminal_page_stays_expanded_when_pointer_leaves(self):
        self.assertIn("terminal", Expanded.KEEP_OPEN_PAGES)

    def test_feature_shortcuts_have_icons_and_labels(self):
        self.assertTrue(all(feature[2] and feature[1] for feature in FEATURES))

    def test_first_playback_update_requests_expanded_geometry_resize(self):
        if not Gtk.init_check():
            self.skipTest("GTK display unavailable")

        class FakeMedia:
            active = None
            active_index = -1
            tracks = []
            directory = ""
            error_message = ""

            def connect(self, *_args):
                return None

            def get_position(self, _callback):
                return None

            def previous(self):
                return None

            def play_pause(self):
                return None

            def next(self):
                return None

            def seek_to(self, _position):
                return None

        from linux_notch.services.power import PowerService

        with tempfile.TemporaryDirectory() as directory:
            cfg = copy.deepcopy(config.DEFAULTS)
            cfg["modules"].update({
                "clipboard": False,
                "todos": False,
                "face": False,
                "terminal": False,
            })
            media = FakeMedia()
            media.directory = directory
            resize_requests = []
            expanded = Expanded(
                cfg,
                media,
                PowerService(),
                on_content_changed=lambda: resize_requests.append(True),
            )
            resize_requests.clear()
            media.active = SimpleNamespace(
                status="Playing",
                title="Song",
                path=os.path.join(directory, "song.mp3"),
                artist="Artist",
                album="Album",
                art_path="",
                length_us=1_000_000,
                can_prev=False,
                can_next=False,
            )
            media.active_index = 0

            expanded.refresh_media()

        self.assertTrue(resize_requests)
        self.assertTrue(expanded.title.get_visible())

    def test_mail_page_lists_unread_and_removes_message_after_reading(self):
        if not Gtk.init_check():
            self.skipTest("GTK display unavailable")

        class FakeMedia:
            active = None
            active_index = -1
            tracks = []
            directory = ""
            error_message = ""

            def connect(self, *_args):
                return None

            def get_position(self, _callback):
                return None

            def previous(self):
                return None

            def play_pause(self):
                return None

            def next(self):
                return None

            def seek_to(self, _position):
                return None

        summary = MailSummary(
            uid="42",
            sender="Sender <sender@example.com>",
            sender_email="sender@example.com",
            reply_to="reply@example.com",
            subject="A new message",
            date="Thu, 20 Nov 2026 10:00:00 +0000",
            message_id="<message@example.com>",
            references="",
        )

        class FakeMailService:
            secure_storage_available = True
            sent_message = None

            def fetch_unread(self, _account, callback):
                callback([summary], None)

            def open_message(self, _account, _uid, callback):
                callback(MailMessage(summary, "Message contents"), None)

            def send_message(self, *args, **kwargs):
                self.sent_message = args, kwargs
                args[4](True, None)

        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["mail_account"] = "user@gmail.com"
        cfg["modules"].update({
            "clipboard": False,
            "todos": False,
            "face": False,
            "terminal": False,
        })
        mail_service = FakeMailService()
        expanded = Expanded(
            cfg,
            FakeMedia(),
            None,
            mail_service=mail_service,
        )
        expanded.show_page("mail")

        self.assertEqual(expanded.mail_unread_count.get_label(), "1")
        self.assertEqual(
            expanded.mail_detail_stack.get_visible_child_name(),
            "inbox",
        )
        self.assertTrue(expanded.mail_disconnect_button.get_visible())
        self.assertIs(
            expanded.mail_disconnect_button.get_parent(),
            expanded.mail_toolbar,
        )
        expanded.mail_list.get_first_child().emit("clicked")
        self.assertEqual(expanded.mail_unread_count.get_label(), "0")
        self.assertEqual(
            expanded.mail_detail_stack.get_visible_child_name(),
            "reader",
        )
        self.assertEqual(
            expanded.mail_body_label.get_label(),
            "Message contents",
        )

        expanded._compose_mail(reply=True)
        self.assertEqual(
            expanded.mail_to_entry.get_text(),
            "reply@example.com",
        )
        self.assertEqual(expanded.mail_subject_entry.get_text(), "Re: A new message")
        expanded._send_mail()
        self.assertEqual(expanded.mail_status.get_label(), "Email sent.")
        self.assertIsNotNone(mail_service.sent_message)
        self.assertEqual(
            expanded.mail_detail_stack.get_visible_child_name(),
            "reader",
        )
        expanded.mail_back_button.emit("clicked")
        self.assertEqual(
            expanded.mail_detail_stack.get_visible_child_name(),
            "inbox",
        )

    def test_mail_setup_saves_address_but_clears_app_password_field(self):
        if not Gtk.init_check():
            self.skipTest("GTK display unavailable")

        class FakeMedia:
            active = None
            active_index = -1
            tracks = []
            directory = ""
            error_message = ""

            def connect(self, *_args):
                return None

            def get_position(self, _callback):
                return None

            def previous(self):
                return None

            def play_pause(self):
                return None

            def next(self):
                return None

            def seek_to(self, _position):
                return None

        class FakeMailService:
            secure_storage_available = True
            supplied = None

            def configure_account(self, account, password, callback):
                self.supplied = account, password
                callback(account, None)

            def fetch_unread(self, _account, callback):
                callback([], None)

        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["modules"].update({
            "clipboard": False,
            "todos": False,
            "face": False,
            "terminal": False,
        })
        mail_service = FakeMailService()
        expanded = Expanded(
            cfg,
            FakeMedia(),
            None,
            mail_service=mail_service,
        )
        expanded.mail_email_entry.set_text("user@gmail.com")
        expanded.mail_password_entry.set_text("app-password-not-real")

        with patch("linux_notch.ui.expanded.config.save") as save:
            expanded._connect_mail_account()

        self.assertEqual(
            mail_service.supplied,
            ("user@gmail.com", "app-password-not-real"),
        )
        self.assertEqual(cfg["mail_account"], "user@gmail.com")
        self.assertNotIn("mail_password", cfg)
        self.assertEqual(expanded.mail_password_entry.get_text(), "")
        save.assert_called_once_with(cfg)


if __name__ == "__main__":
    unittest.main()
