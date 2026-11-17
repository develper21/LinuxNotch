"""Expanded island with a feature grid and stack-based feature pages.

Every timer here lives only while the card is mapped: the 1 Hz seek tick,
the 3 s system sampler, the weather request. Unmapping tears it all down.
"""

from __future__ import annotations

import os
import sqlite3
import logging
import uuid

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from linux_notch import config
from linux_notch.services.clipboard import ClipboardHistoryService
from linux_notch.services.face_client import FaceDaemonClient
from linux_notch.services.mail import MailMessage, MailService, MailSummary
from linux_notch.ui.draw import BatteryRing, pick_icon
from linux_notch.ui.mochi import MochiWidget, OUTFITS, draw_mochi
from linux_notch.ui.terminal import TerminalPage

logger = logging.getLogger(__name__)

FEATURES = (
    ("clipboard", "Clipboard", "edit-paste-symbolic", "clipboard"),
    ("mail", "Mail", "mail-message-new-symbolic", ""),
    ("music", "Music", "audio-x-generic-symbolic", "music"),
    ("system", "Widgets", "view-grid-symbolic", "system"),
    ("todos", "ToDo", "view-list-symbolic", "todos"),
    ("face", "Face Unlock", "avatar-default-symbolic", "face"),
    ("terminal", "Terminal", "utilities-terminal-symbolic", "terminal"),
)
HOME_FEATURES = (
    "clipboard", "mail", "music", "system",
    "todos", "face", "terminal",
)
HOME_FEATURE_COLUMNS = 4
ALL_FEATURE_COLUMNS = 4


class Expanded(Gtk.Box):
    KEEP_OPEN_PAGES = frozenset({"terminal"})

    def __init__(self, cfg: dict, media, power, weather=None, system=None,
                 on_settings=None,
                 clipboard: ClipboardHistoryService | None = None,
                 on_mochi_changed=None, on_content_changed=None,
                 on_close=None, on_terminal_focus=None,
                 mail_service: MailService | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("expanded")
        self.cfg = cfg
        self.media = media
        self.power = power
        self.weather = weather
        self.system = system
        self.on_settings = on_settings
        self.on_close = on_close
        self.on_terminal_focus = on_terminal_focus
        self.on_mochi_changed = on_mochi_changed
        self.on_content_changed = on_content_changed
        self.clipboard = clipboard
        self.mail_service = mail_service

        self._pos_timer = 0
        self._seek_dragging = False
        self._position_us = 0
        self._caffeine: Gio.Subprocess | None = None
        self._mail_summaries: list[MailSummary] = []
        self._selected_mail: MailMessage | None = None
        self._reply_context: MailSummary | None = None
        self._mail_compose_return_view = "inbox"

        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.content.set_hexpand(True)
        self.content.set_halign(Gtk.Align.FILL)
        self.append(self.content)
        self.pages: dict[str, Gtk.Widget] = {}
        self.page_stack = Gtk.Stack()
        self.page_stack.set_transition_type(
            Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.page_stack.set_transition_duration(220)
        self.page_stack.set_vhomogeneous(False)
        self.page_stack.set_vexpand(True)

        self._build_header()
        self._build_inline_volume_panel()
        self.content.append(self.page_stack)
        self._build_player()
        self._build_toggles()
        self._build_tiles()
        self._build_footer()
        self._build_settings_page()
        self._build_mochi_page()
        if self.clipboard is not None:
            self._build_clipboard_page()
        if cfg.get("modules", {}).get("todos", True):
            self._build_todo_page()
        self.face_client = FaceDaemonClient()
        if cfg.get("modules", {}).get("face", True):
            self._build_face_page()
        if cfg.get("modules", {}).get("terminal", True):
            self._build_terminal_page()
        self._build_mail_page()
        self._build_features_page()
        self._build_home_page()
        self.page_stack.connect(
            "notify::visible-child-name",
            lambda *_: self._sync_pos_timer())
        self.show_page("home")

        self.connect("map", lambda *_: self._on_map())
        self.connect("unmap", lambda *_: self._on_unmap())

    # -- page navigation ---------------------------------------------------

    def _build_header(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.top_button = Gtk.Button()
        self.top_button.add_css_class("tab-btn")
        self.top_button.connect("clicked", self._on_top_button)
        self.mail_button = Gtk.Button()
        self.mail_button.add_css_class("tab-btn")
        self.mail_button.set_icon_name("mail-message-new-symbolic")
        self.mail_button.set_tooltip_text("Open unread mail")
        self.mail_button.connect("clicked", lambda *_: self.show_page("mail"))
        self.add_button = Gtk.Button()
        self.add_button.add_css_class("tab-btn")
        self.add_button.set_icon_name("list-add-symbolic")
        self.add_button.set_tooltip_text("Show all features")
        self.add_button.connect(
            "clicked", lambda *_: self.show_page("features"))

        self.settings_button = Gtk.Button()
        self.settings_button.add_css_class("tab-btn")
        self.settings_button.set_icon_name("emblem-system-symbolic")
        self.settings_button.set_tooltip_text("Settings")
        self.settings_button.connect(
            "clicked", lambda *_: self.show_page("settings"))
        self.volume_button = Gtk.Button()
        self.volume_button.add_css_class("tab-btn")
        self.volume_button.set_icon_name("audio-volume-high-symbolic")
        self.volume_button.set_tooltip_text("Show sound controls")
        self.volume_button.connect("clicked", self._toggle_inline_volume)

        self.clear_clipboard_button = Gtk.Button(label="Clear all")
        self.clear_clipboard_button.add_css_class("clipboard-clear-btn")
        self.clear_clipboard_button.set_visible(False)
        spacer = Gtk.Box(hexpand=True)

        self.bt_chip = _chip("bluetooth-active-symbolic")
        self.net_chip = _chip("network-wireless-symbolic")
        self.net_chip.set_visible(False)

        row.append(self.top_button)
        row.append(self.mail_button)
        row.append(self.add_button)
        row.append(spacer)
        row.append(self.bt_chip)
        row.append(self.net_chip)
        row.append(self.clear_clipboard_button)
        row.append(self.volume_button)
        row.append(self.settings_button)
        self.content.append(row)

    def _build_inline_volume_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        panel.add_css_class("volume-inline-panel")
        self.inline_volume_icon = Gtk.Image.new_from_icon_name(
            "audio-volume-high-symbolic")
        self.inline_volume_icon.set_pixel_size(16)
        label = Gtk.Label(label="Volume")
        label.add_css_class("tile-sub")
        self.inline_vol = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.inline_vol.set_hexpand(True)
        self.inline_vol.set_draw_value(False)
        self.inline_vol.set_size_request(160, -1)
        self.inline_vol.connect("change-value", self._on_vol_set)
        self.inline_vol_value = Gtk.Label(label="—")
        self.inline_vol_value.add_css_class("seek-time")
        panel.append(self.inline_volume_icon)
        panel.append(label)
        panel.append(self.inline_vol)
        panel.append(self.inline_vol_value)

        self.inline_volume_revealer = Gtk.Revealer()
        self.inline_volume_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.inline_volume_revealer.set_transition_duration(180)
        self.inline_volume_revealer.set_reveal_child(False)
        self.inline_volume_revealer.set_child(panel)
        self.content.append(self.inline_volume_revealer)
        self.inline_volume_revealer.connect(
            "notify::reveal-child", lambda *_: self._resize_content())
        self.inline_volume_revealer.connect(
            "notify::child-revealed", lambda *_: self._resize_content())

    def _toggle_inline_volume(self, *_):
        reveal = not self.inline_volume_revealer.get_reveal_child()
        self.inline_volume_revealer.set_reveal_child(reveal)
        self.volume_button.set_tooltip_text(
            "Hide sound controls" if reveal else "Show sound controls")
        if self.on_content_changed is not None:
            self.on_content_changed()

    def _resize_content(self):
        if self.on_content_changed is not None:
            self.on_content_changed()

    def _on_top_button(self, *_):
        if self.page_stack.get_visible_child_name() != "home":
            self.show_page("home")
        elif self.on_close is not None:
            self.on_close()

    def show_page(self, name: str):
        if name not in self.pages:
            raise ValueError(f"Unknown expanded page: {name}")
        self.page_stack.set_visible_child_name(name)
        home = name == "home"
        self.top_button.set_icon_name(
            "go-home-symbolic" if home else "go-previous-symbolic")
        self.top_button.set_tooltip_text("Close" if home else "Back")
        self.clear_clipboard_button.set_visible(name == "clipboard")
        if name == "face" and hasattr(self, "_refresh_face_status"):
            self._refresh_face_status()
        if name == "terminal":
            self.terminal_page.on_show()
            if self.on_terminal_focus is not None:
                self.on_terminal_focus()
        if name == "music":
            self.refresh_music()
            self.refresh_music_library()
        if name == "mail":
            self._show_mail_page()
        if self.on_content_changed is not None:
            self.on_content_changed()

    def reset_to_home(self):
        self.show_page("home")

    def _add_feature_page(self, name: str, title: str, content: Gtk.Widget):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("feature-title")
        page.append(heading)
        content.set_valign(Gtk.Align.CENTER)
        content.set_hexpand(True)
        content.set_vexpand(True)
        page.append(content)
        self.pages[name] = page
        self.page_stack.add_named(page, name)

    def _available_features(self):
        modules = self.cfg.get("modules", {})
        return [
            feature for feature in FEATURES
            if (not feature[3] or modules.get(feature[3], True))
            and feature[0] in self.pages
        ]

    def _feature_button(self, feature):
        feature_id, title, icon, _module = feature
        button = Gtk.Button()
        button.add_css_class("home-feature-btn")
        button.set_hexpand(True)
        button.set_tooltip_text(title)
        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=5)
        content.set_halign(Gtk.Align.CENTER)
        content.set_valign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(22)
        label = Gtk.Label(label=title)
        label.add_css_class("feature-btn-label")
        label.set_halign(Gtk.Align.CENTER)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_wrap(True)
        label.set_max_width_chars(10)
        content.append(image)
        content.append(label)
        button.set_child(content)
        button.connect(
            "clicked", lambda _button: self.show_page(feature_id))
        return button

    def _build_features_page(self):
        grid = Gtk.Grid()
        grid.add_css_class("features-grid")
        grid.set_column_homogeneous(True)
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        for index, feature in enumerate(self._available_features()):
            grid.attach(
                self._feature_button(feature),
                index % ALL_FEATURE_COLUMNS,
                index // ALL_FEATURE_COLUMNS,
                1,
                1,
            )

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(180)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_child(grid)
        self._add_feature_page("features", "All features", scroll)

    def _build_mail_page(self):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.add_css_class("mail-page")

        self.mail_setup = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
        )
        self.mail_setup.add_css_class("mail-setup")
        self.mail_setup.set_halign(Gtk.Align.CENTER)
        self.mail_setup.set_valign(Gtk.Align.CENTER)
        setup_title = Gtk.Label(label="Connect a Gmail account")
        setup_title.add_css_class("track-title")
        self.mail_email_entry = Gtk.Entry()
        self.mail_email_entry.set_placeholder_text("you@gmail.com")
        self.mail_email_entry.set_hexpand(True)
        self.mail_password_entry = Gtk.Entry()
        self.mail_password_entry.set_placeholder_text("Gmail App Password")
        self.mail_password_entry.set_visibility(False)
        self.mail_password_entry.set_input_purpose(
            Gtk.InputPurpose.PASSWORD)
        self.mail_password_entry.set_hexpand(True)
        credential_note = Gtk.Label(
            label="The app password is stored in your desktop keyring, "
                  "not in Linux Notch settings.",
            wrap=True,
        )
        credential_note.add_css_class("track-artist")
        self.mail_setup_status = Gtk.Label(
            label="Use a Gmail App Password. Your normal Google password "
                  "will not work.",
            wrap=True,
        )
        self.mail_setup_status.add_css_class("tile-sub")
        connect_button = Gtk.Button(label="Connect Gmail")
        connect_button.add_css_class("suggested-action")
        connect_button.connect("clicked", self._connect_mail_account)
        self.mail_email_entry.connect(
            "activate", lambda *_: self.mail_password_entry.grab_focus())
        self.mail_password_entry.connect(
            "activate", self._connect_mail_account)
        self.mail_setup.append(setup_title)
        self.mail_setup.append(self.mail_email_entry)
        self.mail_setup.append(self.mail_password_entry)
        self.mail_setup.append(credential_note)
        self.mail_setup.append(self.mail_setup_status)
        self.mail_setup.append(connect_button)

        toolbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
        )
        self.mail_account_label = Gtk.Label(xalign=0)
        self.mail_account_label.add_css_class("feature-title")
        self.mail_account_label.set_hexpand(True)
        self.mail_account_label.set_ellipsize(Pango.EllipsizeMode.END)
        refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text("Refresh unread mail")
        refresh_button.connect("clicked", lambda *_: self._refresh_mail())
        compose_button = Gtk.Button(label="Compose")
        compose_button.add_css_class("suggested-action")
        compose_button.connect("clicked", lambda *_: self._compose_mail())
        manage_button = Gtk.Button(label="Account")
        manage_button.set_tooltip_text("Update or disconnect this account")
        manage_button.connect("clicked", self._toggle_mail_setup)
        self.mail_disconnect_button = Gtk.Button()
        self.mail_disconnect_button.set_icon_name("system-log-out-symbolic")
        self.mail_disconnect_button.add_css_class("mail-disconnect-button")
        self.mail_disconnect_button.set_has_frame(False)
        self.mail_disconnect_button.set_tooltip_text("Disconnect this account")
        self.mail_disconnect_button.connect(
            "clicked", self._disconnect_mail_account)
        toolbar.append(self.mail_account_label)
        toolbar.append(refresh_button)
        toolbar.append(compose_button)
        toolbar.append(manage_button)
        toolbar.append(self.mail_disconnect_button)

        self.mail_status = Gtk.Label(label="", xalign=0, wrap=True)
        self.mail_status.add_css_class("tile-sub")
        self.mail_workspace = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        self.mail_workspace.add_css_class("mail-workspace")
        self.mail_workspace.set_vexpand(True)

        rail = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
        )
        rail.add_css_class("mail-account-rail")
        self.mail_account_button = Gtk.Button(label="M")
        self.mail_account_button.add_css_class("mail-account-button")
        self.mail_account_button.set_tooltip_text("Show this account's unread mail")
        self.mail_account_button.connect(
            "clicked", lambda *_: self._refresh_mail())
        rail.append(self.mail_account_button)

        inbox_view = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
        )
        inbox_view.add_css_class("mail-inbox-view")
        unread_title = Gtk.Label(label="Unread", xalign=0)
        unread_title.add_css_class("track-title")
        self.mail_unread_count = Gtk.Label(label="0", xalign=1)
        self.mail_unread_count.add_css_class("tile-sub")
        unread_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
        )
        unread_header.append(unread_title)
        unread_header.append(self.mail_unread_count)
        self.mail_list = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
        )
        self.mail_list_scroll = Gtk.ScrolledWindow()
        self.mail_list_scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.mail_list_scroll.set_child(self.mail_list)
        self.mail_list_scroll.set_vexpand(True)
        inbox_view.append(unread_header)
        inbox_view.append(self.mail_list_scroll)

        self.mail_detail_stack = Gtk.Stack()
        self.mail_detail_stack.set_hexpand(True)
        self.mail_detail_stack.set_vexpand(True)
        self.mail_detail_stack.add_named(
            inbox_view, "inbox")
        self.mail_detail_stack.add_named(
            self._build_mail_reader(), "reader")
        self.mail_detail_stack.add_named(
            self._build_mail_composer(), "compose")
        self.mail_detail_stack.set_visible_child_name("inbox")

        self.mail_workspace.append(rail)
        self.mail_workspace.append(self.mail_detail_stack)

        body.append(self.mail_setup)
        self.mail_toolbar = toolbar
        body.append(self.mail_toolbar)
        body.append(self.mail_status)
        body.append(self.mail_workspace)
        self._add_feature_page("mail", "Mail", body)
        self._show_mail_page(refresh=False)

    def _build_mail_reader(self):
        reader = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
        )
        reader.add_css_class("mail-reader")
        reader.set_hexpand(True)
        reader.set_vexpand(True)
        reader_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        back_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        back_button.set_tooltip_text("Back to unread mail")
        self.mail_back_button = back_button
        back_button.connect(
            "clicked",
            lambda *_: self.mail_detail_stack.set_visible_child_name("inbox"),
        )
        reader_header.append(back_button)
        reader_header.append(Gtk.Label(label="Email", xalign=0))
        reader.append(reader_header)
        self.mail_subject = Gtk.Label(xalign=0, wrap=True)
        self.mail_subject.add_css_class("track-title")
        self.mail_subject.set_hexpand(True)
        self.mail_sender = Gtk.Label(xalign=0, wrap=True)
        self.mail_sender.add_css_class("tile-sub")
        self.mail_date = Gtk.Label(xalign=0, wrap=True)
        self.mail_date.add_css_class("tile-sub")
        self.mail_body_label = Gtk.Label(xalign=0, yalign=0)
        self.mail_body_label.set_wrap(True)
        self.mail_body_label.set_selectable(True)
        self.mail_body_label.set_hexpand(True)
        self.mail_body_label.set_vexpand(True)
        self.mail_body_label.set_halign(Gtk.Align.FILL)
        body_scroll = Gtk.ScrolledWindow()
        body_scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        body_scroll.set_hexpand(True)
        body_scroll.add_css_class("mail-body-scroll")
        body_scroll.set_child(self.mail_body_label)
        body_scroll.set_vexpand(True)
        reply_button = Gtk.Button(label="Reply")
        reply_button.add_css_class("suggested-action")
        reply_button.set_halign(Gtk.Align.END)
        reply_button.connect("clicked", lambda *_: self._compose_mail(reply=True))
        reader.append(self.mail_subject)
        reader.append(self.mail_sender)
        reader.append(self.mail_date)
        reader.append(body_scroll)
        reader.append(reply_button)
        return reader

    def _build_mail_composer(self):
        composer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
        )
        composer.add_css_class("mail-composer")
        self.mail_to_entry = Gtk.Entry()
        self.mail_to_entry.set_placeholder_text("To")
        self.mail_subject_entry = Gtk.Entry()
        self.mail_subject_entry.set_placeholder_text("Subject")
        self.mail_compose_body = Gtk.TextView()
        self.mail_compose_body.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        compose_scroll = Gtk.ScrolledWindow()
        compose_scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        compose_scroll.set_child(self.mail_compose_body)
        compose_scroll.set_vexpand(True)
        buttons = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
        )
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", self._cancel_mail_compose)
        self.mail_send_button = Gtk.Button(label="Send")
        self.mail_send_button.add_css_class("suggested-action")
        self.mail_send_button.connect("clicked", self._send_mail)
        buttons.append(cancel)
        buttons.append(self.mail_send_button)
        composer.append(self.mail_to_entry)
        composer.append(self.mail_subject_entry)
        composer.append(compose_scroll)
        composer.append(buttons)
        return composer

    def _show_mail_page(self, refresh=True):
        account = self.cfg.get("mail_account", "").strip()
        self.mail_email_entry.set_text(account)
        self.mail_account_label.set_label(account or "Gmail")
        initial = account.partition("@")[0][:1].upper() or "M"
        self.mail_account_button.set_label(initial)
        self.mail_setup.set_visible(not bool(account))
        self.mail_toolbar.set_visible(bool(account))
        self.mail_disconnect_button.set_visible(bool(account))
        self.mail_workspace.set_visible(bool(account))
        if not account:
            self.mail_detail_stack.set_visible_child_name("inbox")
        if not account:
            self.mail_status.set_label("")
            self.mail_setup_status.set_label(
                "Use a Gmail App Password. Your normal Google password "
                "will not work.")
        elif refresh:
            self._refresh_mail()

    def _toggle_mail_setup(self, *_):
        visible = not self.mail_setup.get_visible()
        self.mail_setup.set_visible(visible)
        self.mail_email_entry.set_text(
            self.cfg.get("mail_account", "").strip())
        if visible:
            self.mail_password_entry.grab_focus()
        self._resize_content()

    def _connect_mail_account(self, *_):
        if self.mail_service is None:
            self.mail_setup_status.set_label(
                "Mail support is unavailable in this installation.")
            return
        account = self.mail_email_entry.get_text().strip()
        password = self.mail_password_entry.get_text()
        self.mail_setup_status.set_label(
            "Verifying Gmail access and saving the app password securely…")
        self.mail_setup_status.set_sensitive(False)

        def complete(saved_account, error):
            self.mail_setup_status.set_sensitive(True)
            if error:
                self.mail_setup_status.set_label(error)
                return
            if self.cfg.get("mail_account", "").strip() != saved_account:
                self._mail_summaries.clear()
                self._selected_mail = None
                self._render_mail_list()
                self.mail_detail_stack.set_visible_child_name("inbox")
            self.cfg["mail_account"] = saved_account
            try:
                config.save(self.cfg)
            except OSError:
                self.mail_setup_status.set_label(
                    "The app password is in your keyring, but the account "
                    "address could not be saved. Check settings-file "
                    "permissions and try again.")
                return
            self.mail_password_entry.set_text("")
            self._show_mail_page(refresh=False)
            self._refresh_mail()

        self.mail_service.configure_account(account, password, complete)

    def _disconnect_mail_account(self, *_):
        account = self.cfg.get("mail_account", "").strip()
        if not account or self.mail_service is None:
            return
        self.mail_status.set_label("Removing saved account…")

        def complete(_result, error):
            if error:
                self.mail_status.set_label(error)
                return
            self.cfg["mail_account"] = ""
            try:
                config.save(self.cfg)
            except OSError:
                self._show_mail_page(refresh=False)
                self.mail_status.set_label(
                    "The keyring credential was removed, but the account "
                    "setting could not be saved. Reconnect after fixing "
                    "settings-file permissions.")
                return
            self._mail_summaries.clear()
            self._selected_mail = None
            self._render_mail_list()
            self.mail_detail_stack.set_visible_child_name("inbox")
            self._show_mail_page(refresh=False)
            self._resize_content()

        self.mail_service.forget_account(account, complete)

    def _refresh_mail(self):
        account = self.cfg.get("mail_account", "").strip()
        if not account or self.mail_service is None:
            return
        self.mail_status.set_label("Loading unread mail…")

        def complete(summaries, error):
            if error:
                self.mail_status.set_label(error)
                return
            selected_uid = (
                self._selected_mail.summary.uid
                if self._selected_mail is not None
                else ""
            )
            self._mail_summaries = [
                summary for summary in summaries
                if summary.uid != selected_uid
            ]
            self.mail_unread_count.set_label(str(len(self._mail_summaries)))
            self._render_mail_list()
            self.mail_status.set_label(
                "Inbox is clear." if not self._mail_summaries
                else f"{len(self._mail_summaries)} unread email"
                     f"{'s' if len(self._mail_summaries) != 1 else ''}")

        self.mail_service.fetch_unread(account, complete)

    def _render_mail_list(self):
        child = self.mail_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.mail_list.remove(child)
            child = next_child
        for summary in self._mail_summaries:
            row = Gtk.Button()
            row.add_css_class("mail-message-row")
            row.set_hexpand(True)
            row.set_halign(Gtk.Align.FILL)
            content = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=10,
            )
            icon = Gtk.Image.new_from_icon_name("mail-unread-symbolic")
            icon.set_pixel_size(18)
            icon.add_css_class("mail-row-icon")
            details = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=2,
            )
            details.set_hexpand(True)
            sender = Gtk.Label(label=summary.sender, xalign=0)
            sender.add_css_class("mail-sender")
            sender.set_ellipsize(Pango.EllipsizeMode.END)
            subject = Gtk.Label(label=summary.subject, xalign=0)
            subject.add_css_class("mail-subject")
            subject.set_ellipsize(Pango.EllipsizeMode.END)
            date = Gtk.Label(label=summary.date, xalign=0)
            date.add_css_class("mail-date")
            date.set_ellipsize(Pango.EllipsizeMode.END)
            details.append(sender)
            details.append(subject)
            content.append(icon)
            content.append(details)
            content.append(date)
            row.set_child(content)
            row.set_tooltip_text(
                f"{summary.sender}\n{summary.subject}\n{summary.date}")
            row.connect(
                "clicked",
                lambda *_args, item=summary: self._open_mail(item),
            )
            self.mail_list.append(row)
        self._resize_content()

    def _open_mail(self, summary: MailSummary):
        if self.mail_service is None:
            return
        self.mail_status.set_label("Opening email…")

        def complete(message, error):
            if error:
                self.mail_status.set_label(error)
                return
            self._selected_mail = message
            self._mail_summaries = [
                item for item in self._mail_summaries
                if item.uid != message.summary.uid
            ]
            self.mail_unread_count.set_label(str(len(self._mail_summaries)))
            self._render_mail_list()
            self.mail_subject.set_label(message.summary.subject)
            self.mail_sender.set_label(message.summary.sender)
            self.mail_date.set_label(message.summary.date)
            self.mail_body_label.set_label(
                message.body or "(This email has no readable text body.)")
            self.mail_detail_stack.set_visible_child_name("reader")
            self.mail_status.set_label("Email marked as read.")
            self._resize_content()

        self.mail_service.open_message(
            self.cfg.get("mail_account", "").strip(),
            summary.uid,
            complete,
        )

    def _compose_mail(self, _button=None, reply=False):
        self._reply_context = None
        self.mail_to_entry.set_text("")
        self.mail_subject_entry.set_text("")
        self.mail_compose_body.get_buffer().set_text("")
        if reply and self._selected_mail is not None:
            message = self._selected_mail
            summary = message.summary
            self._reply_context = summary
            self.mail_to_entry.set_text(summary.reply_to)
            subject = summary.subject
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            self.mail_subject_entry.set_text(subject)
            quote = "\n".join(
                f"> {line}" for line in message.body.splitlines())
            self.mail_compose_body.get_buffer().set_text(
                f"\n\nOn {summary.date}, {summary.sender} wrote:\n{quote}")
        self._mail_compose_return_view = (
            "reader"
            if reply
            else self.mail_detail_stack.get_visible_child_name()
        )
        if self._mail_compose_return_view == "compose":
            self._mail_compose_return_view = "inbox"
        self.mail_detail_stack.set_visible_child_name("compose")

    def _cancel_mail_compose(self, *_):
        self.mail_detail_stack.set_visible_child_name(
            self._mail_compose_return_view)

    def _send_mail(self, *_):
        if self.mail_service is None:
            return
        start, end = self.mail_compose_body.get_buffer().get_bounds()
        body = self.mail_compose_body.get_buffer().get_text(
            start, end, True)
        self.mail_send_button.set_sensitive(False)
        self.mail_status.set_label("Sending email…")

        def complete(_result, error):
            self.mail_send_button.set_sensitive(True)
            if error:
                self.mail_status.set_label(error)
                return
            self.mail_status.set_label("Email sent.")
            self.mail_detail_stack.set_visible_child_name(
                self._mail_compose_return_view)
            self._reply_context = None

        reply = self._reply_context
        self.mail_service.send_message(
            self.cfg.get("mail_account", "").strip(),
            self.mail_to_entry.get_text().strip(),
            self.mail_subject_entry.get_text(),
            body,
            complete,
            in_reply_to=reply.message_id if reply else "",
            references=(
                " ".join(
                    part for part in (
                        reply.references if reply else "",
                        reply.message_id if reply else "",
                    ) if part
                )
            ),
        )

    def _build_terminal_page(self):
        self.terminal_page = TerminalPage()
        self._add_feature_page("terminal", "Terminal", self.terminal_page)

    # -- media player section ---------------------------------------------

    def _build_player(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        layout.add_css_class("music-layout")
        self.player_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.player_box.add_css_class("music-preview")
        self.player_box.set_size_request(260, -1)

        self.art_frame = Gtk.Overlay()
        self.art_frame.add_css_class("art-frame")
        self.art_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.art_frame.set_size_request(144, 144)
        self.art_frame.set_halign(Gtk.Align.CENTER)
        self.art = Gtk.Picture()
        self.art.set_size_request(144, 144)
        self.art.set_content_fit(Gtk.ContentFit.COVER)
        self.art_frame.set_child(self.art)
        self.art_placeholder = Gtk.Image.new_from_icon_name(
            "audio-x-generic-symbolic")
        self.art_placeholder.add_css_class("music-art-placeholder")
        self.art_placeholder.set_pixel_size(44)
        self.art_placeholder.set_halign(Gtk.Align.CENTER)
        self.art_placeholder.set_valign(Gtk.Align.CENTER)
        self.art_frame.add_overlay(self.art_placeholder)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        meta.set_halign(Gtk.Align.CENTER)
        self.title = _label("track-title", 26)
        self.title.set_xalign(0.5)
        self.title.set_justify(Gtk.Justification.CENTER)
        self.title.set_max_width_chars(28)
        self.artist = _label("track-artist", 30)
        self.artist.set_xalign(0.5)
        self.artist.set_justify(Gtk.Justification.CENTER)
        self.album = _label("track-album", 34)
        self.album.set_xalign(0.5)
        self.album.set_justify(Gtk.Justification.CENTER)
        for w in (self.title, self.artist, self.album):
            meta.append(w)
        self.title.set_visible(False)
        self.artist.set_visible(False)
        self.album.set_visible(False)

        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.seek_box = seek_box
        self.time_now = Gtk.Label(label="0:00")
        self.time_now.add_css_class("seek-time")
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.add_css_class("seek")
        self.seek.set_hexpand(True)
        self.seek.set_draw_value(False)
        self.time_total = Gtk.Label(label="0:00")
        self.time_total.add_css_class("seek-time")
        seek_box.append(self.time_now)
        seek_box.append(self.seek)
        seek_box.append(self.time_total)

        drag = Gtk.GestureClick()
        drag.connect("pressed", lambda *_: setattr(self, "_seek_dragging", True))
        drag.connect("released", self._on_seek_released)
        self.seek.add_controller(drag)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        controls.set_halign(Gtk.Align.CENTER)
        self.btn_prev = _media_btn("media-skip-backward-symbolic")
        self.btn_play = _media_btn("media-playback-start-symbolic", main=True)
        self.btn_next = _media_btn("media-skip-forward-symbolic")
        self.btn_prev.connect("clicked", lambda *_: self.media.previous())
        self.btn_play.connect("clicked", lambda *_: self.media.play_pause())
        self.btn_next.connect("clicked", lambda *_: self.media.next())
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            controls.append(b)

        self.player_box.append(self.art_frame)
        self.player_box.append(meta)
        self.player_box.append(seek_box)
        self.player_box.append(controls)
        self.music_status = Gtk.Label(
            label="", wrap=True, justify=Gtk.Justification.CENTER, xalign=0.5)
        self.music_status.add_css_class("track-artist")
        self.music_status.set_visible(False)
        self.player_box.append(self.music_status)
        layout.append(self.player_box)

        self.music_list = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4)
        music_scroll = Gtk.ScrolledWindow()
        music_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        music_scroll.set_min_content_width(240)
        music_scroll.set_min_content_height(180)
        music_scroll.set_hexpand(True)
        music_scroll.set_vexpand(True)
        music_scroll.set_child(self.music_list)
        music_scroll.add_css_class("music-library")
        layout.append(music_scroll)
        layout.set_vexpand(True)
        page.append(layout)

        if hasattr(self.media, "connect"):
            self.media.connect(
                "library-changed", lambda *_: self.refresh_music_library())
            self.media.connect("error", self._on_music_error)
            self.media.connect("art-ready", lambda *_: self.refresh_music())
        self.refresh_music_library()
        self._add_feature_page("music", "Music", page)

    def refresh_music_library(self):
        if not hasattr(self, "music_list"):
            return
        child = self.music_list.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.music_list.remove(child)
            child = following

        tracks = getattr(self.media, "tracks", [])
        for index, track in enumerate(tracks):
            title = Gtk.Label(label=track.title, xalign=0)
            title.add_css_class("music-track-title")
            subtitle_text = track.artist or os.path.relpath(
                track.path,
                getattr(self.media, "directory", os.path.dirname(track.path)),
            )
            subtitle = Gtk.Label(label=subtitle_text, xalign=0)
            subtitle.add_css_class("music-track-subtitle")
            content = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=2)
            content.set_halign(Gtk.Align.FILL)
            content.append(title)
            content.append(subtitle)
            button = Gtk.Button()
            button.add_css_class("music-track-row")
            button.set_child(content)
            button.set_tooltip_text(track.path)
            button.connect(
                "clicked",
                lambda _button, track_index=index:
                    self._play_music_track(track_index),
            )
            self.music_list.append(button)

        if not tracks:
            message = getattr(self.media, "error_message", "")
            if not message:
                message = "No supported audio files found in the selected folder."
            empty = Gtk.Label(label=message, wrap=True, xalign=0.5)
            empty.add_css_class("track-artist")
            self.music_list.append(empty)
        self.refresh_music()
        if self.on_content_changed is not None:
            self.on_content_changed()

    def _play_music_track(self, index: int):
        try:
            self.media.play_index(index)
        except (IndexError, OSError, RuntimeError) as error:
            self._on_music_error(self.media, str(error))

    def _on_music_error(self, _service, message: str):
        if hasattr(self, "music_status"):
            self.music_status.set_label(f"Music error: {message}")
            self.music_status.set_visible(True)

    # -- quick toggles ------------------------------------------------------

    def _build_toggles(self):
        self.tg_mute = _toggle("audio-volume-high-symbolic", "Mute")
        self.tg_mute.connect("toggled", self._on_mute_toggle)
        self.tg_mic = _toggle("microphone-sensitivity-high-symbolic", "Mic")
        self.tg_mic.connect("toggled", self._on_mic_toggle)
        self.tg_caffeine = _toggle(
            pick_icon(self, "preferences-desktop-screensaver-symbolic",
                      "caffeine-cup-full-symbolic", "video-display-symbolic"),
            "Caffeine")
        self.tg_caffeine.connect("toggled", self._on_caffeine_toggle)
        shot = Gtk.Button()
        shot.set_icon_name(pick_icon(
            self, "applets-screenshooter-symbolic", "camera-photo-symbolic"))
        shot.add_css_class("toggle-btn")
        shot.set_tooltip_text("Screenshot")
        shot.connect("clicked", self._on_screenshot)

        self._add_feature_page("mute", "Mute", self._control(self.tg_mute))
        self._add_feature_page(
            "microphone", "Microphone", self._control(self.tg_mic))
        self._add_feature_page(
            "caffeine", "Caffeine", self._control(self.tg_caffeine))
        self._add_feature_page(
            "screenshot", "Screenshot", self._control(shot))

    @staticmethod
    def _control(widget: Gtk.Widget) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_halign(Gtk.Align.CENTER)
        box.append(widget)
        return box

    def _on_mute_toggle(self, btn):
        Gio.Subprocess.new(
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@",
             "1" if btn.get_active() else "0"], Gio.SubprocessFlags.NONE)
        btn.set_icon_name("audio-volume-muted-symbolic" if btn.get_active()
                          else "audio-volume-high-symbolic")

    def _on_mic_toggle(self, btn):
        Gio.Subprocess.new(
            ["pactl", "set-source-mute", "@DEFAULT_SOURCE@",
             "1" if btn.get_active() else "0"], Gio.SubprocessFlags.NONE)
        btn.set_icon_name(
            "microphone-sensitivity-muted-symbolic" if btn.get_active()
            else "microphone-sensitivity-high-symbolic")

    def _on_caffeine_toggle(self, btn):
        if btn.get_active() and self._caffeine is None:
            try:
                self._caffeine = Gio.Subprocess.new(
                    ["systemd-inhibit", "--what=idle:sleep",
                     "--who=linux-notch", "--why=Caffeine",
                     "sleep", "infinity"], Gio.SubprocessFlags.NONE)
            except GLib.Error:
                btn.set_active(False)
        elif not btn.get_active() and self._caffeine is not None:
            self._caffeine.force_exit()
            self._caffeine = None

    def _on_screenshot(self, *_):
        for tool in (["spectacle", "-r"], ["flameshot", "gui"],
                     ["gnome-screenshot", "-i"]):
            if GLib.find_program_in_path(tool[0]):
                Gio.Subprocess.new(tool, Gio.SubprocessFlags.NONE)
                return

    # -- tiles -------------------------------------------------------------

    def _build_tiles(self):
        # battery
        self.battery_tile = _tile()
        self.ring = BatteryRing(accent=_hex_rgb(self.cfg.get("accent", "#ff9f0a")))
        self.ring.set_halign(Gtk.Align.CENTER)
        self.batt_label = Gtk.Label()
        self.batt_label.add_css_class("tile-sub")
        self.battery_tile.append(self.ring)
        self.battery_tile.append(self.batt_label)
        self._add_feature_page("battery", "Battery", self.battery_tile)

        # volume
        vol_tile = _tile()
        vol_tile.set_halign(Gtk.Align.CENTER)
        vol_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        vol_icon.set_halign(Gtk.Align.CENTER)
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.add_css_class("vol")
        self.vol.set_draw_value(False)
        self.vol.set_size_request(180, -1)
        self.vol.connect("change-value", self._on_vol_set)
        vol_label = Gtk.Label(label="Volume")
        vol_label.add_css_class("tile-sub")
        vol_tile.append(vol_icon)
        vol_tile.append(self.vol)
        vol_tile.append(vol_label)
        self._add_feature_page("volume", "Volume", vol_tile)

        # weather
        self.weather_tile = _tile()
        self.weather_icon = Gtk.Image.new_from_icon_name("weather-clear-symbolic")
        self.weather_icon.set_pixel_size(22)
        self.weather_icon.set_halign(Gtk.Align.CENTER)
        self.weather_temp = Gtk.Label(label="—")
        self.weather_temp.add_css_class("tile-big")
        self.weather_desc = Gtk.Label(label="Weather")
        self.weather_desc.add_css_class("tile-sub")
        self.weather_desc.set_ellipsize(Pango.EllipsizeMode.END)
        self.weather_desc.set_max_width_chars(11)
        self.weather_tile.append(self.weather_icon)
        self.weather_tile.append(self.weather_temp)
        self.weather_tile.append(self.weather_desc)
        self._add_feature_page("weather", "Weather", self.weather_tile)

        if self.weather is None:
            self.weather_tile.set_tooltip_text("Weather is disabled in Settings")
        else:
            self.weather.connect("changed", self._on_weather)

    def _build_footer(self):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name("view-grid-symbolic")
        icon.set_pixel_size(32)
        title = Gtk.Label(label="Coming soon")
        title.add_css_class("track-title")
        description = Gtk.Label(
            label=(
                "Desktop widgets that you can add to your desktop are "
                "coming soon."
            ),
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        description.add_css_class("track-artist")
        body.append(icon)
        body.append(title)
        body.append(description)
        self._add_feature_page("system", "Widgets", body)

    def _build_settings_page(self):
        from linux_notch.ui.settings import SettingsPanel

        self.settings_panel = SettingsPanel(self.cfg, self.on_settings)
        self._add_feature_page("settings", "Settings", self.settings_panel)

    def _build_mochi_page(self):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        description = Gtk.Label(
            label="Choose Mochi's look.",
            wrap=True,
            xalign=0,
        )
        body.append(description)

        grid = Gtk.Grid()
        grid.add_css_class("mochi-outfit-grid")
        grid.set_column_homogeneous(True)
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        self.mochi_outfit_buttons: dict[str, Gtk.Button] = {}
        selected = self.cfg.get("mochi_outfit", "auto")
        outfit_keys = {key for key, _label in OUTFITS}
        if selected not in outfit_keys:
            selected = "auto"

        for index, (outfit, label) in enumerate(OUTFITS):
            button = Gtk.Button()
            button.add_css_class("feature-btn")
            button.set_tooltip_text(label)
            preview = Gtk.DrawingArea()
            preview.set_content_width(58)
            preview.set_content_height(54)
            preview.set_draw_func(
                lambda _area, cr, width, height, key=outfit:
                    draw_mochi(cr, width, height, "idle", key, 0.0))
            name = Gtk.Label(label=label)
            name.add_css_class("feature-btn-label")
            content = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=4)
            content.append(preview)
            content.append(name)
            button.set_child(content)
            button.connect("clicked", self._on_mochi_outfit_selected, outfit)
            self.mochi_outfit_buttons[outfit] = button
            grid.attach(button, index % 2, index // 2, 1, 1)

        self._update_mochi_outfit_selection(selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(210)
        scroll.set_child(grid)
        body.append(scroll)
        self._add_feature_page("mochi", "Mochi", body)

    def _on_mochi_outfit_selected(self, _button, outfit: str):
        self.cfg["mochi_outfit"] = outfit
        config.save(self.cfg)
        self._update_mochi_outfit_selection(outfit)
        if self.on_mochi_changed is not None:
            self.on_mochi_changed()

    def _update_mochi_outfit_selection(self, selected: str):
        for outfit, button in self.mochi_outfit_buttons.items():
            if outfit == selected:
                button.add_css_class("mochi-outfit-selected")
            else:
                button.remove_css_class("mochi-outfit-selected")

    def _build_clipboard_page(self):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        recording_error = None
        if self.cfg.get("clipboard_recording", False):
            try:
                self.clipboard.set_recording(True)
            except (RuntimeError, OSError, sqlite3.Error) as error:
                recording_error = str(error)

        self.clipboard_status = Gtk.Label(xalign=0)
        self.clipboard_status.add_css_class("tile-sub")
        body.append(self.clipboard_status)

        self.clipboard_list = Gtk.ListBox()
        self.clipboard_list.add_css_class("clipboard-list")
        self.clipboard_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.clear_clipboard_button.connect(
            "clicked", self._on_clipboard_clear)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(150)
        scroll.set_child(self.clipboard_list)
        body.append(scroll)

        self.clipboard.connect("changed", self._refresh_clipboard)
        self.clipboard.connect("error", self._on_clipboard_error)
        self._refresh_clipboard()
        if recording_error:
            self._on_clipboard_error(self.clipboard, recording_error)
        self._add_feature_page("clipboard", "Clipboard history", body)

    def _on_clipboard_clear(self, *_):
        try:
            self.clipboard.clear()
        except (OSError, sqlite3.Error) as error:
            self._on_clipboard_error(self.clipboard, str(error))

    def _on_clipboard_error(self, _service, message):
        self.clipboard_status.set_label(f"Clipboard history error: {message}")

    def _refresh_clipboard(self, *_):
        row = self.clipboard_list.get_first_child()
        while row is not None:
            following = row.get_next_sibling()
            self.clipboard_list.remove(row)
            row = following

        try:
            items = self.clipboard.list_items()
        except (OSError, sqlite3.Error) as error:
            self._on_clipboard_error(self.clipboard, str(error))
            return
        for item in items:
            row = Gtk.ListBoxRow()
            content = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            copy = Gtk.Button()
            copy.add_css_class("flat")
            copy.set_hexpand(True)
            preview = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            if item.kind == "image":
                image = Gtk.Picture()
                image.set_size_request(48, 48)
                image.set_content_fit(Gtk.ContentFit.CONTAIN)
                try:
                    image.set_paintable(Gdk.Texture.new_from_filename(
                        item.content))
                except GLib.Error as error:
                    self._on_clipboard_error(self.clipboard, str(error))
                preview.append(image)
                preview.append(Gtk.Label(
                    label="Image", xalign=0, hexpand=True))
            else:
                text = Gtk.Label(label=item.content, xalign=0)
                text.set_wrap(True)
                text.set_lines(2)
                text.set_ellipsize(Pango.EllipsizeMode.END)
                text.set_hexpand(True)
                preview.append(text)
            copy.set_child(preview)
            copy.connect("clicked", self._copy_clipboard_item, item)
            content.append(copy)

            pin = Gtk.ToggleButton()
            pin.set_icon_name(
                "starred-symbolic" if item.pinned else "non-starred-symbolic")
            pin.set_active(item.pinned)
            pin.set_tooltip_text("Unpin item" if item.pinned else "Pin item")
            pin.connect("toggled", self._on_clipboard_pin, item.id)
            content.append(pin)
            row.set_child(content)
            self.clipboard_list.append(row)
        if self.on_content_changed is not None:
            self.on_content_changed()

    def _copy_clipboard_item(self, _button, item):
        clipboard = self.clipboard.clipboard
        if clipboard is None:
            self._on_clipboard_error(
                self.clipboard, "Clipboard is unavailable on this display")
            return
        if item.kind == "image":
            try:
                value = Gdk.Texture.new_from_filename(item.content)
            except GLib.Error as error:
                self._on_clipboard_error(self.clipboard, str(error))
                return
        else:
            value = item.content
        try:
            if not clipboard.set_content(
                    Gdk.ContentProvider.new_for_value(value)):
                self._on_clipboard_error(
                    self.clipboard, "The clipboard rejected this item.")
        except GLib.Error as error:
            self._on_clipboard_error(self.clipboard, str(error))

    def _on_clipboard_pin(self, button, item_id):
        try:
            self.clipboard.set_pinned(item_id, button.get_active())
        except (OSError, sqlite3.Error) as error:
            self._on_clipboard_error(self.clipboard, str(error))

    def _build_todo_page(self):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.todo_entry = Gtk.Entry()
        self.todo_entry.set_placeholder_text("Add a task...")
        self.todo_entry.set_hexpand(True)
        self.todo_entry.connect("activate", self._add_todo)
        add_button = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_button.add_css_class("todo-add-btn")
        add_button.set_tooltip_text("Add task")
        add_button.connect("clicked", self._add_todo)
        input_row.append(self.todo_entry)
        input_row.append(add_button)
        body.append(input_row)

        self.todo_status = Gtk.Label(
            label="Tasks are saved on this device.", xalign=0)
        self.todo_status.add_css_class("tile-sub")
        body.append(self.todo_status)

        self.todo_list = Gtk.ListBox()
        self.todo_list.add_css_class("todo-list")
        self.todo_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(110)
        scroll.set_child(self.todo_list)
        body.append(scroll)
        self._refresh_todos()
        self._add_feature_page("todos", "ToDo list", body)

    def _todo_items(self):
        items = self.cfg.get("todos", [])
        if not isinstance(items, list):
            return []
        return [
            item for item in items
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("text"), str)
            and isinstance(item.get("completed"), bool)
        ]

    def _save_todos(self, items):
        try:
            config.save({**self.cfg, "todos": items})
        except OSError as error:
            self.todo_status.set_label(f"Could not save tasks: {error}")
            return False
        self.cfg["todos"] = items
        self.todo_status.set_label("Tasks are saved on this device.")
        return True

    def _add_todo(self, *_):
        text = self.todo_entry.get_text().strip()
        if not text:
            return
        items = self._todo_items()
        items.append({
            "id": uuid.uuid4().hex,
            "text": text,
            "completed": False,
        })
        if self._save_todos(items):
            self.todo_entry.set_text("")
            self._refresh_todos()

    def _toggle_todo(self, button, item_id):
        items = [
            {**item, "completed": button.get_active()}
            if item["id"] == item_id else item
            for item in self._todo_items()
        ]
        self._save_todos(items)
        self._refresh_todos()

    def _delete_todo(self, _button, item_id):
        items = [
            item for item in self._todo_items() if item["id"] != item_id
        ]
        if self._save_todos(items):
            self._refresh_todos()

    def _refresh_todos(self):
        row = self.todo_list.get_first_child()
        while row is not None:
            following = row.get_next_sibling()
            self.todo_list.remove(row)
            row = following

        for item in self._todo_items():
            row = Gtk.ListBoxRow()
            content = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.add_css_class("todo-row")
            check = Gtk.CheckButton()
            check.set_active(item["completed"])
            label = Gtk.Label(label=item["text"], xalign=0, hexpand=True)
            label.set_wrap(True)
            check.set_child(label)
            if item["completed"]:
                label.set_markup(
                    "<span strikethrough='true'>"
                    f"{GLib.markup_escape_text(item['text'])}</span>")
                label.add_css_class("todo-completed")
            check.connect("toggled", self._toggle_todo, item["id"])
            content.append(check)

            delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            delete.add_css_class("todo-delete-btn")
            delete.set_tooltip_text("Delete task")
            delete.connect("clicked", self._delete_todo, item["id"])
            content.append(delete)
            row.set_child(content)
            self.todo_list.append(row)
        if self.on_content_changed is not None:
            self.on_content_changed()

    def refresh_music(self):
        if not hasattr(self, "music_status"):
            return
        player = self.media.active
        row = self.music_list.get_first_child()
        index = 0
        while row is not None:
            if not isinstance(row, Gtk.Button):
                row = row.get_next_sibling()
                continue
            if index == getattr(self.media, "active_index", -1):
                row.add_css_class("music-track-row-active")
            else:
                row.remove_css_class("music-track-row-active")
            index += 1
            row = row.get_next_sibling()
        if player is None:
            error = getattr(self.media, "error_message", "")
            self.music_status.set_label(
                f"Music error: {error}" if error else "")
            self.music_status.set_visible(bool(error))
            self._set_music_artwork(None)
            self.title.set_visible(False)
            self.artist.set_visible(False)
            self.album.set_visible(False)
            self.seek.set_range(0, 1)
            self.time_now.set_label("0:00")
            self.time_total.set_label("0:00")
            self.btn_prev.set_sensitive(False)
            self.btn_play.set_sensitive(False)
            self.btn_next.set_sensitive(False)
            self.seek_box.set_sensitive(False)
            self._sync_pos_timer()
            self._resize_content()
            return

        self.seek_box.set_sensitive(True)
        self.title.set_label(player.title or os.path.basename(player.path))
        self.artist.set_label(player.artist)
        self.album.set_label(player.album)
        self.title.set_visible(True)
        self.artist.set_visible(bool(player.artist))
        self.album.set_visible(bool(player.album))
        if player.art_path and os.path.exists(player.art_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    player.art_path, 144, 144, True)
                self._set_music_artwork(Gdk.Texture.new_for_pixbuf(pixbuf))
            except GLib.Error as error:
                logger.warning("Could not load local album art: %s", error)
                self._set_music_artwork(None)
        else:
            self._set_music_artwork(None)
        self.btn_play.set_icon_name(
            "media-playback-pause-symbolic"
            if player.status == "Playing"
            else "media-playback-start-symbolic")
        self.btn_prev.set_sensitive(player.can_prev)
        self.btn_play.set_sensitive(True)
        self.btn_next.set_sensitive(player.can_next)
        duration = max(1, player.length_us)
        self.seek.set_range(0, duration)
        self.time_total.set_label(_fmt_us(player.length_us))
        if player.status == "Playing":
            self.music_status.set_label("Playing")
            self.music_status.set_visible(True)
        elif player.status == "Paused":
            self.music_status.set_label("Paused")
            self.music_status.set_visible(True)
        elif getattr(self.media, "error_message", ""):
            self.music_status.set_label(
                f"Music error: {self.media.error_message}")
            self.music_status.set_visible(True)
        else:
            self.music_status.set_label("")
            self.music_status.set_visible(False)
        self._sync_pos_timer()
        self._poll_position()
        self._resize_content()

    def _set_music_artwork(self, paintable):
        self.art.set_paintable(paintable)
        self.art_placeholder.set_visible(paintable is None)

    def _build_face_page(self):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_vexpand(True)

        status_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        status_card.add_css_class("face-status-card")

        status_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_icon = Gtk.Image.new_from_icon_name("avatar-default-symbolic")
        status_icon.set_pixel_size(24)
        self.face_status_label = Gtk.Label(label="Checking face status...", xalign=0)
        self.face_status_label.add_css_class("face-status-badge")
        self.face_status_label.set_hexpand(True)
        status_header.append(status_icon)
        status_header.append(self.face_status_label)
        status_card.append(status_header)

        self.face_info_label = Gtk.Label(
            label="Local biometric recognition for lock screen.",
            xalign=0,
        )
        self.face_info_label.add_css_class("track-artist")
        status_card.append(self.face_info_label)
        body.append(status_card)

        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ctrl_box.add_css_class("face-ctrl-box")

        enable_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        enable_lbl = Gtk.Label(label="Enable Face Unlock", xalign=0, hexpand=True)
        self.face_enable_switch = Gtk.Switch()
        self.face_enable_switch.set_active(self.cfg.get("face_enabled", True))
        def on_enable_toggled(sw, _):
            val = sw.get_active()
            self.cfg["face_enabled"] = val
            config.save(self.cfg)
            self.face_client.set_enabled(val)
        self.face_enable_switch.connect("notify::active", on_enable_toggled)
        enable_row.append(enable_lbl)
        enable_row.append(self.face_enable_switch)
        ctrl_box.append(enable_row)

        thresh_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        thresh_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        thresh_lbl = Gtk.Label(label="Similarity threshold", xalign=0, hexpand=True)
        curr_thresh = float(self.cfg.get("face_threshold", 0.45))
        self.face_thresh_val = Gtk.Label(label=f"{curr_thresh:.2f}")
        self.face_thresh_val.add_css_class("track-artist")
        thresh_header.append(thresh_lbl)
        thresh_header.append(self.face_thresh_val)
        thresh_row.append(thresh_header)

        self.face_thresh_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.30, 0.70, 0.05
        )
        self.face_thresh_scale.set_value(curr_thresh)
        self.face_thresh_scale.set_hexpand(True)
        def on_thresh_changed(scale):
            val = round(scale.get_value(), 2)
            self.face_thresh_val.set_label(f"{val:.2f}")
            self.cfg["face_threshold"] = val
            config.save(self.cfg)
            self.face_client.set_threshold(val)
        self.face_thresh_scale.connect("value-changed", on_thresh_changed)
        thresh_row.append(self.face_thresh_scale)
        ctrl_box.append(thresh_row)

        chal_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        chal_meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        chal_meta.set_hexpand(True)
        chal_lbl = Gtk.Label(label="Head-movement challenge", xalign=0)
        chal_sub = Gtk.Label(
            label="Require head turn to reject 2D photos", xalign=0
        )
        chal_sub.add_css_class("track-artist")
        chal_meta.append(chal_lbl)
        chal_meta.append(chal_sub)
        self.face_chal_switch = Gtk.Switch()
        self.face_chal_switch.set_active(self.cfg.get("face_challenge", False))
        def on_chal_toggled(sw, _):
            val = sw.get_active()
            self.cfg["face_challenge"] = val
            config.save(self.cfg)
            self.face_client.set_challenge(val)
        self.face_chal_switch.connect("notify::active", on_chal_toggled)
        chal_row.append(chal_meta)
        chal_row.append(self.face_chal_switch)
        ctrl_box.append(chal_row)

        body.append(ctrl_box)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.face_enroll_btn = Gtk.Button(label="Enroll face")
        self.face_enroll_btn.set_icon_name("contact-new-symbolic")
        self.face_enroll_btn.set_hexpand(True)
        self.face_enroll_btn.connect("clicked", self._on_enroll_clicked)

        self.face_reset_btn = Gtk.Button(label="Reset")
        self.face_reset_btn.set_icon_name("user-trash-symbolic")
        self.face_reset_btn.add_css_class("destructive-action")
        self.face_reset_btn.connect("clicked", self._on_reset_clicked)

        btn_box.append(self.face_enroll_btn)
        btn_box.append(self.face_reset_btn)
        body.append(btn_box)

        self.face_test_btn = Gtk.Button(label="Test scan")
        self.face_test_btn.set_icon_name("camera-photo-symbolic")
        self.face_test_btn.connect("clicked", self._on_test_scan_clicked)
        body.append(self.face_test_btn)

        self.face_progress = Gtk.ProgressBar()
        self.face_progress.set_visible(False)
        body.append(self.face_progress)

        self.face_feedback_label = Gtk.Label(label="", xalign=0)
        self.face_feedback_label.add_css_class("track-artist")
        self.face_feedback_label.set_wrap(True)
        body.append(self.face_feedback_label)

        self._add_feature_page("face", "Face Unlock", body)

        self.face_client.connect("state-changed", self._on_face_state_changed)
        self.face_client.connect("result-received", self._on_face_result_received)
        self.face_client.connect("enroll-progress", self._on_face_enroll_progress)
        self.face_client.connect("enroll-complete", self._on_face_enroll_complete)

        self._refresh_face_status()

    def _refresh_face_status(self):
        if not hasattr(self, "face_client") or not hasattr(self, "face_status_label"):
            return
        status = self.face_client.get_status()
        enrolled = status["enrolled"]
        samples = status.get("sample_count", 0)
        if enrolled:
            text = f"Enrolled ({samples} samples)" if samples else "Enrolled"
            self.face_status_label.set_label(text)
            self.face_reset_btn.set_sensitive(True)
        else:
            self.face_status_label.set_label("Not enrolled")
            self.face_reset_btn.set_sensitive(False)

    def _on_enroll_clicked(self, _btn):
        self.face_progress.set_visible(True)
        self.face_progress.set_fraction(0.0)
        self.face_feedback_label.set_label("Starting enrollment... Look at camera.")
        try:
            self.face_client.start_enroll()
        except Exception as error:
            self.face_feedback_label.set_label(f"Enrollment error: {error}")
            self.face_progress.set_visible(False)

    def _on_reset_clicked(self, _btn):
        success = self.face_client.reset()
        if success:
            self.face_feedback_label.set_label("Face data removed.")
            self._refresh_face_status()
        else:
            self.face_feedback_label.set_label("Could not reset face data.")

    def _on_test_scan_clicked(self, _btn):
        self.face_progress.set_visible(False)
        self.face_feedback_label.set_label("Running test scan... Look at camera.")
        try:
            self.face_client.start_test_scan()
        except Exception as error:
            self.face_feedback_label.set_label(f"Test scan error: {error}")

    def _on_face_state_changed(self, _client, state, message):
        self.face_feedback_label.set_label(message)

    def _on_face_result_received(self, _client, success, score):
        if success:
            self.face_feedback_label.set_label(f"Match confirmed! Similarity: {score:.2f}")
        else:
            self.face_feedback_label.set_label(f"No match. Best similarity: {score:.2f}")

    def _on_face_enroll_progress(self, _client, step, total, pose):
        fraction = min(1.0, max(0.0, step / total)) if total > 0 else 0.0
        self.face_progress.set_visible(True)
        self.face_progress.set_fraction(fraction)
        self.face_feedback_label.set_label(f"Step {step}/{total}: {pose}")

    def _on_face_enroll_complete(self, _client, success, message):
        self.face_progress.set_visible(False)
        self.face_feedback_label.set_label(message)
        self._refresh_face_status()

    def _build_home_page(self):
        layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        layout.set_hexpand(True)
        layout.set_vexpand(True)

        character_card = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8)
        character_card.add_css_class("home-card")
        character_card.add_css_class("home-character-card")
        character_card.set_vexpand(True)
        self.home_mochi = MochiWidget(self.cfg)
        self.home_mochi.set_content_width(112)
        self.home_mochi.set_content_height(94)
        self.home_mochi.set_size_request(112, 94)
        character_button = Gtk.Button()
        character_button.add_css_class("home-character-button")
        character_button.set_child(self.home_mochi)
        character_button.set_tooltip_text("Customize Mochi")
        character_button.connect("clicked", lambda *_: self.show_page("mochi"))
        self.home_status = Gtk.Label(
            label="Ready when you are", xalign=0.5, wrap=True)
        self.home_status.add_css_class("home-status")
        self.home_status.set_ellipsize(Pango.EllipsizeMode.END)
        self.home_status.set_max_width_chars(28)
        character_card.append(character_button)
        character_card.append(self.home_status)

        grid = Gtk.Grid()
        grid.add_css_class("home-feature-grid")
        grid.set_column_homogeneous(True)
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        column = 0
        row = 0
        for feature in self._available_features():
            feature_id = feature[0]
            if feature_id not in HOME_FEATURES:
                continue
            button = self._feature_button(feature)
            grid.attach(button, column, row, 1, 1)
            column += 1
            if column == HOME_FEATURE_COLUMNS:
                column = 0
                row += 1

        layout.append(character_card)
        layout.append(grid)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.add_css_class("home-layout")
        page.set_hexpand(True)
        page.set_vexpand(True)
        page.append(layout)
        self.pages["home"] = page
        self.page_stack.add_named(page, "home")

    def show_activity(self, activity: dict | None) -> None:
        if activity is None:
            self._refresh_home_status()
            self.home_mochi.show_activity(None)
            return
        self.home_mochi.show_activity(activity)
        title = str(activity.get("title") or "Activity")
        state = str(activity.get("state") or "working").replace("-", " ").title()
        self.home_status.set_label(f"{title} · {state}")

    def _refresh_home_status(self) -> None:
        player = self.media.active
        if player is not None:
            self.home_status.set_label(
                f"Playing · {player.title or 'Unknown track'}")
        else:
            self.home_status.set_label("Ready when you are")

    # -- refresh from services --------------------------------------------

    def refresh_media(self):
        self.refresh_music()
        self._refresh_home_status()

    def refresh_battery(self):
        if not self.power.available:
            self.battery_tile.set_visible(False)
            return
        self.ring.update(self.power.percentage, self.power.charging)
        suffix = " ⚡" if self.power.charging else ""
        self.batt_label.set_label(f"{self.power.percentage:.0f}%{suffix}")

    def refresh_volume(self, percent: int, muted: bool = False):
        self.vol.set_value(percent)
        self.inline_vol.set_value(percent)
        self.inline_vol_value.set_label(f"{percent}%")
        icon = (
            "audio-volume-muted-symbolic"
            if muted else "audio-volume-high-symbolic"
        )
        self.volume_button.set_icon_name(icon)
        self.inline_volume_icon.set_from_icon_name(icon)
        if hasattr(self, "tg_mute") and self.tg_mute.get_active() != muted:
            self.tg_mute.handler_block_by_func(self._on_mute_toggle)
            self.tg_mute.set_active(muted)
            self.tg_mute.set_icon_name(
                "audio-volume-muted-symbolic" if muted
                else "audio-volume-high-symbolic")
            self.tg_mute.handler_unblock_by_func(self._on_mute_toggle)

    def refresh_network(self, name: str, kind: str, connected: bool):
        if not connected:
            self.net_chip.set_visible(False)
        else:
            icon = ("network-wireless-symbolic" if "wireless" in kind
                    else "network-wired-symbolic")
            _set_chip(self.net_chip, icon, name or "Connected")
            self.net_chip.set_visible(True)

    def refresh_bluetooth(self, device: str, connected: bool, battery: int):
        self.bt_chip.set_visible(connected)
        if connected:
            text = device if battery < 0 else f"{device} · {battery}%"
            _set_chip(self.bt_chip,
                      pick_icon(self, "bluetooth-symbolic",
                                "network-bluetooth-symbolic",
                                "bluetooth-active-symbolic"), text)

    def _on_weather(self, _svc, temp, desc, icon):
        self.weather_temp.set_label(temp)
        self.weather_desc.set_label(desc)
        # prefer the full-color weather set; symbolic suns get too abstract
        self.weather_icon.set_from_icon_name(pick_icon(
            self, icon.replace("-symbolic", ""), icon,
            "weather-few-clouds"))

    # -- lifecycle ----------------------------------------------------------

    def _on_map(self):
        self.refresh_media()
        self.refresh_battery()
        if self.weather is not None:
            self.weather.request()
        if self.system is not None:
            self.system.start()

    def _on_unmap(self):
        if self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0
        if self.system is not None:
            self.system.stop()
        if hasattr(self, "face_client"):
            self.face_client.stop_scan()

    # -- seek bar ----------------------------------------------------------

    def _sync_pos_timer(self):
        playing = self.media.active and self.media.active.status == "Playing"
        want = bool(
            playing
            and self.get_mapped()
            and self.page_stack.get_visible_child_name() == "music"
        )
        if want and not self._pos_timer:
            self._pos_timer = GLib.timeout_add_seconds(1, self._poll_position)
        elif not want and self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0

    def _poll_position(self):
        self.media.get_position(self._on_position)
        return True

    def _on_position(self, pos_us: int):
        self._position_us = pos_us
        if not self._seek_dragging:
            self.seek.set_value(pos_us)
        self.time_now.set_label(_fmt_us(pos_us))

    def _on_seek_released(self, gesture, n, x, y):
        self._seek_dragging = False
        self.media.seek_to(int(self.seek.get_value()))

    def _on_vol_set(self, scale, scroll, value):
        value = max(0, min(100, value))
        self.vol.set_value(value)
        self.inline_vol.set_value(value)
        self.inline_vol_value.set_label(f"{int(value)}%")
        Gio.Subprocess.new(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@",
             f"{int(value)}%"],
            Gio.SubprocessFlags.NONE)
        return False

def _label(css: str, width: int) -> Gtk.Label:
    lbl = Gtk.Label(xalign=0)
    lbl.add_css_class(css)
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_max_width_chars(width)
    return lbl


def _media_btn(icon: str, main: bool = False) -> Gtk.Button:
    btn = Gtk.Button()
    btn.set_icon_name(icon)
    btn.add_css_class("media-btn")
    if main:
        btn.add_css_class("media-btn--main")
    return btn


def _toggle(icon: str, tooltip: str) -> Gtk.ToggleButton:
    btn = Gtk.ToggleButton()
    btn.set_icon_name(icon)
    btn.add_css_class("toggle-btn")
    btn.set_tooltip_text(tooltip)
    return btn


def _chip(icon: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    box.add_css_class("chip")
    img = Gtk.Image.new_from_icon_name(icon)
    img.set_pixel_size(13)
    lbl = Gtk.Label()
    lbl.add_css_class("net-chip")
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_max_width_chars(14)
    box.append(img)
    box.append(lbl)
    return box


def _set_chip(chip: Gtk.Box, icon: str, text: str):
    img = chip.get_first_child()
    lbl = chip.get_last_child()
    img.set_from_icon_name(icon)
    lbl.set_label(text)


def _tile() -> Gtk.Box:
    tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    tile.add_css_class("tile")
    tile.set_valign(Gtk.Align.CENTER)
    return tile


def _fmt_us(us: int) -> str:
    s = max(0, us // 1_000_000)
    return f"{s // 60}:{s % 60:02d}"


def _hex_rgb(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
