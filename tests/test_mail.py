import email
import email.policy
import unittest
from unittest.mock import patch
from unittest.mock import PropertyMock

from linux_notch.services.mail import (
    MailError,
    MailService,
    _message_body,
    _summary_from_message,
)


class MailServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = MailService()

    def tearDown(self):
        self.service.stop()

    def test_decodes_headers_and_strips_html_without_loading_remote_content(self):
        raw = (
            b"From: =?utf-8?q?N=C3=A9ar?= <near@example.com>\r\n"
            b"Reply-To: reply@example.com\r\n"
            b"Subject: =?utf-8?q?Hello_=E2=9C=93?=\r\n"
            b"Date: Thu, 20 Nov 2026 10:00:00 +0000\r\n"
            b"Message-ID: <message-1@example.com>\r\n"
            b"References: <prior@example.com>\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n\r\n"
            b"<html><script>do not show</script><p>Hello &amp; "
            b"welcome</p><img src='https://example.com/image.png'></html>"
        )
        message = email.message_from_bytes(raw, policy=email.policy.default)

        summary = _summary_from_message("17", message)

        self.assertEqual(summary.uid, "17")
        self.assertEqual(summary.sender_email, "near@example.com")
        self.assertIn("Néar", summary.sender)
        self.assertEqual(summary.reply_to, "reply@example.com")
        self.assertEqual(summary.subject, "Hello ✓")
        self.assertEqual(summary.message_id, "<message-1@example.com>")
        self.assertEqual(summary.references, "<prior@example.com>")
        body = _message_body(message)
        self.assertIn("Hello & welcome", body)
        self.assertNotIn("do not show", body)
        self.assertNotIn("https://example.com", body)

    def test_opening_a_message_marks_it_read_and_returns_plain_text(self):
        raw = (
            b"From: sender@example.com\r\n"
            b"To: account@gmail.com\r\n"
            b"Subject: Hello\r\n"
            b"Message-ID: <hello@example.com>\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Message body"
        )

        class FakeIMAP:
            def __init__(self):
                self.commands = []

            def select(self, mailbox, readonly=False):
                self.commands.append(("select", mailbox, readonly))
                return "OK", [b"1"]

            def uid(self, command, *args):
                self.commands.append((command, *args))
                if command == "FETCH":
                    return "OK", [(b"1 (UID 17 BODY[] {12}", raw)]
                return "OK", [b"stored"]

            def logout(self):
                return "BYE", [b"closed"]

        client = FakeIMAP()
        with (
            patch.object(self.service, "_load_password", return_value="secret"),
            patch.object(
                MailService, "_imap_login", return_value=client),
        ):
            result = self.service._open_message("account@gmail.com", "17")

        self.assertEqual(result.summary.uid, "17")
        self.assertEqual(result.body, "Message body")
        self.assertIn(("STORE", "17", "+FLAGS", r"(\Seen)"), client.commands)

    def test_inbox_query_requests_only_unread_and_orders_newest_first(self):
        headers = {
            b"42": (
                b"From: older@example.com\r\n"
                b"Subject: Older\r\n\r\n"
            ),
            b"43": (
                b"From: newer@example.com\r\n"
                b"Subject: Newer\r\n\r\n"
            ),
        }

        class FakeIMAP:
            commands = []

            def select(self, mailbox, readonly=False):
                self.commands.append(("select", mailbox, readonly))
                return "OK", [b"2"]

            def uid(self, command, *args):
                self.commands.append((command, *args))
                if command == "SEARCH":
                    return "OK", [b"42 43"]
                if command == "FETCH":
                    return "OK", [
                        (b"1 (UID 42 BODY[HEADER.FIELDS]", headers[b"42"]),
                        (b"2 (UID 43 BODY[HEADER.FIELDS]", headers[b"43"]),
                    ]
                raise AssertionError(f"Unexpected IMAP command: {command}")

            def logout(self):
                return "BYE", [b"closed"]

        client = FakeIMAP()
        client.commands = []
        with (
            patch.object(self.service, "_load_password", return_value="secret"),
            patch.object(
                MailService, "_imap_login", return_value=client),
        ):
            unread = self.service._fetch_unread("account@gmail.com")

        self.assertEqual([item.uid for item in unread], ["43", "42"])
        self.assertEqual(
            next(command for command in client.commands if command[0] == "SEARCH"),
            ("SEARCH", None, "UNSEEN"),
        )
        self.assertEqual(client.commands[0], ("select", "INBOX", True))

    def test_reply_uses_standard_thread_headers(self):
        class FakeSMTP:
            sent = None

            def send_message(self, message, **kwargs):
                self.sent = message, kwargs

            def quit(self):
                return 221, b"bye"

        smtp = FakeSMTP()
        with (
            patch.object(self.service, "_load_password", return_value="secret"),
            patch.object(MailService, "_smtp_login", return_value=smtp),
        ):
            result = self.service._send_message(
                "account@gmail.com",
                "sender@example.com",
                "Re: Hello",
                "My reply",
                "<hello@example.com>",
                "<prior@example.com> <hello@example.com>",
            )

        self.assertTrue(result)
        message, kwargs = smtp.sent
        self.assertEqual(message["In-Reply-To"], "<hello@example.com>")
        self.assertEqual(
            message["References"],
            "<prior@example.com> <hello@example.com>",
        )
        self.assertEqual(kwargs["to_addrs"], ["sender@example.com"])
        self.assertEqual(message.get_content().strip(), "My reply")

    def test_app_password_is_saved_only_after_both_gmail_logins(self):
        class FakeConnection:
            def logout(self):
                return "BYE", [b"closed"]

            def quit(self):
                return 221, b"bye"

        stored = []
        with (
            patch.object(
                MailService,
                "secure_storage_available",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                MailService, "_imap_login", return_value=FakeConnection()),
            patch.object(
                MailService, "_smtp_login", return_value=FakeConnection()),
            patch.object(
                self.service,
                "_store_password",
                side_effect=lambda account, password: stored.append(
                    (account, password)),
            ),
        ):
            account = self.service._configure_account(
                " account@gmail.com ", "abcd efgh ijkl mnop")

        self.assertEqual(account, "account@gmail.com")
        self.assertEqual(stored, [("account@gmail.com", "abcdefghijklmnop")])

    def test_invalid_recipients_are_rejected_before_smtp(self):
        with patch.object(
            self.service, "_load_password", return_value="secret"
        ), patch.object(MailService, "_smtp_login") as smtp_login:
            with self.assertRaisesRegex(MailError, "valid recipient"):
                self.service._send_message(
                    "account@gmail.com",
                    "not-an-address",
                    "Hello",
                    "body",
                    "",
                    "",
                )

        smtp_login.assert_not_called()


if __name__ == "__main__":
    unittest.main()
