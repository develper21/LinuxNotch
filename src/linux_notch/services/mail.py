"""Gmail IMAP/SMTP access with app passwords kept in the desktop keyring."""

from __future__ import annotations

import concurrent.futures
import email
import email.header
import email.message
import email.policy
import email.utils
import html.parser
import imaplib
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass

import gi

from gi.repository import GLib

try:
    gi.require_version("Secret", "1")
    from gi.repository import Secret
except (ImportError, ValueError):
    Secret = None

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
NETWORK_TIMEOUT = 15
FETCH_BATCH_SIZE = 50
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
SECRET_SCHEMA_NAME = "org.linux-notch.mail"

if Secret is not None:
    _SECRET_SCHEMA = Secret.Schema.new(
        SECRET_SCHEMA_NAME,
        Secret.SchemaFlags.NONE,
        {"account": Secret.SchemaAttributeType.STRING},
    )
else:
    _SECRET_SCHEMA = None


class MailError(Exception):
    """A safe, user-facing mail error that never includes credentials."""


@dataclass(frozen=True)
class MailSummary:
    uid: str
    sender: str
    sender_email: str
    reply_to: str
    subject: str
    date: str
    message_id: str
    references: str


@dataclass(frozen=True)
class MailMessage:
    summary: MailSummary
    body: str


class _PlainTextHTMLParser(html.parser.HTMLParser):
    _BLOCK_TAGS = frozenset({
        "address", "article", "br", "dd", "div", "dl", "dt", "h1", "h2",
        "h3", "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "section",
        "table", "tr", "ul",
    })
    _HIDDEN_TAGS = frozenset({"head", "script", "style"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in self._HIDDEN_TAGS:
            self._hidden_depth += 1
        elif tag in self._BLOCK_TAGS and self._parts:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN_TAGS and self._hidden_depth:
            self._hidden_depth -= 1
        elif tag in self._BLOCK_TAGS and self._parts:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def text(self) -> str:
        lines = (part.strip() for part in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line)


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(value)))
    except (LookupError, UnicodeError, ValueError):
        return value


def _summary_from_message(uid: str, message) -> MailSummary:
    display_name, sender_email = email.utils.parseaddr(
        _decode_header(message.get("From")))
    sender_email = sender_email.strip()
    sender = display_name.strip() or sender_email or "Unknown sender"
    if sender_email and display_name:
        sender = f"{display_name.strip()} <{sender_email}>"
    reply_to = email.utils.parseaddr(
        _decode_header(message.get("Reply-To")))[1].strip()
    references = " ".join(
        _decode_header(message.get("References")).split())
    return MailSummary(
        uid=uid,
        sender=sender,
        sender_email=sender_email,
        reply_to=reply_to or sender_email,
        subject=_decode_header(message.get("Subject")) or "(no subject)",
        date=_decode_header(message.get("Date")),
        message_id=_decode_header(message.get("Message-ID")),
        references=references,
    )


def _message_body(message) -> str:
    plain_parts = []
    html_parts = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            plain_parts.append(text)
        else:
            parser = _PlainTextHTMLParser()
            parser.feed(text)
            html_parts.append(parser.text())

    return "\n\n".join(plain_parts or html_parts).strip()


def _header_bytes(raw_message: bytes) -> bytes:
    return raw_message[:MAX_MESSAGE_BYTES]


class MailService:
    """Runs blocking Gmail operations off the GTK thread."""

    def __init__(self):
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="linux-notch-mail",
        )
        self._closed = False

    @property
    def secure_storage_available(self) -> bool:
        return Secret is not None and _SECRET_SCHEMA is not None

    def configure_account(self, account: str, password: str, callback) -> None:
        self._submit(
            self._configure_account,
            (account, password),
            callback,
        )

    def fetch_unread(self, account: str, callback) -> None:
        self._submit(self._fetch_unread, (account,), callback)

    def open_message(self, account: str, uid: str, callback) -> None:
        self._submit(self._open_message, (account, uid), callback)

    def send_message(
        self,
        account: str,
        recipient: str,
        subject: str,
        body: str,
        callback,
        in_reply_to: str = "",
        references: str = "",
    ) -> None:
        self._submit(
            self._send_message,
            (account, recipient, subject, body, in_reply_to, references),
            callback,
        )

    def forget_account(self, account: str, callback) -> None:
        self._submit(self._forget_account, (account,), callback)

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _submit(self, operation, args: tuple, callback) -> None:
        if self._closed:
            GLib.idle_add(
                callback, None, "Mail service is shutting down.")
            return
        future = self._executor.submit(operation, *args)
        future.add_done_callback(
            lambda completed: GLib.idle_add(
                self._deliver, completed, callback))

    @staticmethod
    def _deliver(future, callback) -> bool:
        try:
            result = future.result()
        except MailError as error:
            callback(None, str(error))
        except Exception as error:
            logger.error("Mail operation failed (%s)", type(error).__name__)
            callback(None, "Email operation failed. Please try again.")
        else:
            callback(result, None)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _normalize_account(account: str) -> str:
        value = account.strip()
        if (
            not value
            or value.count("@") != 1
            or any(character.isspace() for character in value)
        ):
            raise MailError("Enter a valid Gmail address.")
        return value

    @staticmethod
    def _secret_attributes(account: str) -> dict[str, str]:
        return {"account": account.strip().lower()}

    def _store_password(self, account: str, password: str) -> None:
        if not self.secure_storage_available:
            raise MailError(
                "Secure keyring support is unavailable. Install libsecret "
                "and unlock your desktop keyring.")
        try:
            stored = Secret.password_store_sync(
                _SECRET_SCHEMA,
                self._secret_attributes(account),
                Secret.COLLECTION_DEFAULT,
                "Linux Notch Gmail App Password",
                password,
                None,
            )
        except GLib.Error:
            raise MailError(
                "Could not access the desktop keyring. Unlock it and try again."
            ) from None
        if not stored:
            raise MailError("The desktop keyring did not save the password.")

    def _load_password(self, account: str) -> str:
        if not self.secure_storage_available:
            raise MailError(
                "Secure keyring support is unavailable. Install libsecret "
                "and unlock your desktop keyring.")
        try:
            password = Secret.password_lookup_sync(
                _SECRET_SCHEMA,
                self._secret_attributes(account),
                None,
            )
        except GLib.Error:
            raise MailError(
                "Could not access the desktop keyring. Unlock it and try again."
            ) from None
        if not password:
            raise MailError(
                "No saved app password was found. Reconnect this account.")
        return password

    def _clear_password(self, account: str) -> None:
        if not self.secure_storage_available:
            raise MailError(
                "Secure keyring support is unavailable; the account was not "
                "disconnected.")
        try:
            Secret.password_clear_sync(
                _SECRET_SCHEMA,
                self._secret_attributes(account),
                None,
            )
        except GLib.Error:
            raise MailError(
                "Could not access the desktop keyring. Unlock it and try again."
            ) from None

    @staticmethod
    def _imap_login(account: str, password: str):
        client = None
        try:
            client = imaplib.IMAP4_SSL(
                IMAP_HOST,
                IMAP_PORT,
                timeout=NETWORK_TIMEOUT,
                ssl_context=ssl.create_default_context(),
            )
            status, _data = client.login(account, password)
        except (imaplib.IMAP4.error, OSError, ssl.SSLError):
            if client is not None:
                MailService._close_imap(client)
            raise MailError(
                "Gmail IMAP login failed. Check the address and App Password."
            ) from None
        if status != "OK":
            MailService._close_imap(client)
            raise MailError(
                "Gmail IMAP login failed. Check the address and App Password."
            )
        return client

    @staticmethod
    def _smtp_login(account: str, password: str):
        client = None
        try:
            client = smtplib.SMTP_SSL(
                SMTP_HOST,
                SMTP_PORT,
                timeout=NETWORK_TIMEOUT,
                context=ssl.create_default_context(),
            )
            client.login(account, password)
        except (smtplib.SMTPException, OSError, ssl.SSLError):
            if client is not None:
                try:
                    client.close()
                except OSError:
                    pass
            raise MailError(
                "Gmail SMTP login failed. Check the address and App Password."
            ) from None
        return client

    @staticmethod
    def _close_imap(client) -> None:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    @staticmethod
    def _check_imap_status(response, message: str) -> list:
        if not response or response[0] != "OK":
            raise MailError(message)
        return response[1] or []

    def _configure_account(self, account: str, password: str) -> str:
        account = self._normalize_account(account)
        password = password.replace(" ", "").strip()
        if not password or any(character.isspace() for character in password):
            raise MailError("Enter a Gmail App Password.")
        if not self.secure_storage_available:
            raise MailError(
                "Secure keyring support is unavailable. Install libsecret "
                "and unlock your desktop keyring.")

        imap = self._imap_login(account, password)
        self._close_imap(imap)
        smtp = self._smtp_login(account, password)
        try:
            smtp.quit()
        except (smtplib.SMTPException, OSError):
            pass
        self._store_password(account, password)
        return account

    def _fetch_unread(self, account: str) -> list[MailSummary]:
        account = self._normalize_account(account)
        password = self._load_password(account)
        client = self._imap_login(account, password)
        try:
            self._check_imap_status(
                client.select("INBOX", readonly=True),
                "Could not open the Gmail inbox.",
            )
            search_data = self._check_imap_status(
                client.uid("SEARCH", None, "UNSEEN"),
                "Could not search the Gmail inbox.",
            )
            uids = search_data[0].split() if search_data else []
            summaries = []
            for start in range(0, len(uids), FETCH_BATCH_SIZE):
                batch = uids[start:start + FETCH_BATCH_SIZE]
                uid_list = b",".join(batch).decode("ascii")
                fetched = self._check_imap_status(
                    client.uid(
                        "FETCH",
                        uid_list,
                        "(UID BODY.PEEK[HEADER.FIELDS "
                        "(FROM SUBJECT DATE REPLY-TO MESSAGE-ID REFERENCES)])",
                    ),
                    "Could not read Gmail message headers.",
                )
                summaries.extend(self._parse_headers(fetched))
        finally:
            self._close_imap(client)
        return sorted(
            summaries,
            key=lambda item: int(item.uid),
            reverse=True,
        )

    @staticmethod
    def _parse_headers(fetched: list) -> list[MailSummary]:
        summaries = []
        for item in fetched:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            match = re.search(rb"\bUID\s+(\d+)\b", item[0])
            if match is None or not isinstance(item[1], bytes):
                continue
            message = email.message_from_bytes(
                item[1], policy=email.policy.default)
            summaries.append(_summary_from_message(
                match.group(1).decode("ascii"), message))
        return summaries

    def _open_message(self, account: str, uid: str) -> MailMessage:
        account = self._normalize_account(account)
        if not uid.isdecimal():
            raise MailError("The selected email is invalid.")
        password = self._load_password(account)
        client = self._imap_login(account, password)
        try:
            self._check_imap_status(
                client.select("INBOX", readonly=False),
                "Could not open the Gmail inbox.",
            )
            fetched = self._check_imap_status(
                client.uid(
                    "FETCH",
                    uid,
                    f"(UID BODY.PEEK[]<0.{MAX_MESSAGE_BYTES}>)",
                ),
                "Could not open this email.",
            )
            raw_message = next(
                (
                    item[1] for item in fetched
                    if isinstance(item, tuple)
                    and len(item) > 1
                    and isinstance(item[1], bytes)
                ),
                None,
            )
            if raw_message is None:
                raise MailError("This email is no longer available.")
            message = email.message_from_bytes(
                _header_bytes(raw_message),
                policy=email.policy.default,
            )
            self._check_imap_status(
                client.uid("STORE", uid, "+FLAGS", r"(\Seen)"),
                "Could not mark this email as read.",
            )
        finally:
            self._close_imap(client)
        return MailMessage(
            summary=_summary_from_message(uid, message),
            body=_message_body(message),
        )

    def _send_message(
        self,
        account: str,
        recipient: str,
        subject: str,
        body: str,
        in_reply_to: str,
        references: str,
    ) -> bool:
        account = self._normalize_account(account)
        recipients = [
            address for _name, address in email.utils.getaddresses([recipient])
            if address
        ]
        if (
            not recipients
            or any(character in recipient for character in "\r\n")
            or any("@" not in address for address in recipients)
        ):
            raise MailError("Enter at least one valid recipient email address.")
        if any(character in subject for character in "\r\n"):
            raise MailError("The subject must be a single line.")

        password = self._load_password(account)
        message = email.message.EmailMessage()
        message["From"] = account
        message["To"] = recipient
        message["Subject"] = subject.strip() or "(no subject)"
        message.set_content(body)
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references

        client = self._smtp_login(account, password)
        try:
            client.send_message(
                message,
                from_addr=account,
                to_addrs=recipients,
            )
        except (smtplib.SMTPException, OSError):
            raise MailError("Gmail could not send this email.") from None
        finally:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                pass
        return True

    def _forget_account(self, account: str) -> bool:
        account = self._normalize_account(account)
        self._clear_password(account)
        return True
