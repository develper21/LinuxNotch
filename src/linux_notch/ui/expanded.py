"""Expanded island with a feature grid and stack-based feature pages.

Every timer here lives only while the card is mapped: the 1 Hz seek tick,
the 3 s system sampler, the weather request. Unmapping tears it all down.
"""

from __future__ import annotations

import os
import sqlite3
import time
import logging

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from linux_notch import config
from linux_notch.services.clipboard import ClipboardHistoryService
from linux_notch.services.mpris import MprisService, SPOTIFY_BUS_NAME
from linux_notch.services.spotify import spotify_installed
from linux_notch.ui.draw import BatteryRing, pick_icon
from linux_notch.ui.mochi import MochiWidget, OUTFITS, draw_mochi

logger = logging.getLogger(__name__)

FEATURES = (
    ("clipboard", "Clipboard", "edit-paste-symbolic", "clipboard"),
    ("spotify", "Spotify", "audio-x-generic-symbolic", "spotify"),
    ("music", "Music", "audio-x-generic-symbolic", "music"),
    ("system", "Widgets", "view-grid-symbolic", "system"),
)


class Expanded(Gtk.Box):
    def __init__(self, cfg: dict, media, power, weather=None, system=None,
                 on_settings=None,
                 clipboard: ClipboardHistoryService | None = None,
                 spotify_available: bool | None = None,
                 on_mochi_changed=None, on_close=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("expanded")
        self.cfg = cfg
        self.media = media
        self.power = power
        self.weather = weather
        self.system = system
        self.on_settings = on_settings
        self.on_close = on_close
        self.on_mochi_changed = on_mochi_changed
        self.clipboard = clipboard
        self.spotify_available = (
            spotify_installed() if spotify_available is None
            and cfg.get("modules", {}).get("spotify", True)
            else bool(spotify_available))

        self._pos_timer = 0
        self._spotify_timer = 0
        self._seek_dragging = False
        self._position_us = 0
        self._caffeine: Gio.Subprocess | None = None

        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12)
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
        self.content.append(self.page_stack)
        self._build_player()
        self._build_toggles()
        self._build_tiles()
        self._build_footer()
        self._build_settings_page()
        self._build_mochi_page()
        if self.clipboard is not None:
            self._build_clipboard_page()
        if cfg.get("modules", {}).get("spotify", True):
            self._build_spotify_page()
        self._build_home_page()
        self.page_stack.connect(
            "notify::visible-child-name",
            lambda *_: self._sync_spotify_timer())
        self.show_page("home")

        self.connect("map", lambda *_: self._on_map())
        self.connect("unmap", lambda *_: self._on_unmap())

    # -- page navigation ---------------------------------------------------

    def _build_header(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.top_button = Gtk.Button()
        self.top_button.add_css_class("tab-btn")
        self.top_button.connect("clicked", self._on_top_button)
        self.chat_button = Gtk.Button()
        self.chat_button.add_css_class("tab-btn")
        self.chat_button.set_icon_name("mail-message-new-symbolic")
        self.chat_button.set_tooltip_text("Clipboard history")
        self.chat_button.set_visible(self.clipboard is not None)
        self.chat_button.connect("clicked", lambda *_: self.show_page("clipboard"))
        self.add_button = Gtk.Button()
        self.add_button.add_css_class("tab-btn")
        self.add_button.set_icon_name("list-add-symbolic")
        self.add_button.set_tooltip_text("Feature selector")
        self.add_button.connect("clicked", lambda *_: self.show_page("home"))

        self.settings_button = Gtk.Button()
        self.settings_button.add_css_class("tab-btn")
        self.settings_button.set_icon_name("emblem-system-symbolic")
        self.settings_button.set_tooltip_text("Settings")
        self.settings_button.connect(
            "clicked", lambda *_: self.show_page("settings"))
        self.volume_button = Gtk.Button()
        self.volume_button.add_css_class("tab-btn")
        self.volume_button.set_icon_name("audio-volume-high-symbolic")
        self.volume_button.set_tooltip_text("Volume")
        self.volume_button.connect(
            "clicked", lambda *_: self.show_page("volume"))

        self.clear_clipboard_button = Gtk.Button(label="Clear all")
        self.clear_clipboard_button.add_css_class("clipboard-clear-btn")
        self.clear_clipboard_button.set_visible(False)
        spacer = Gtk.Box(hexpand=True)

        self.bt_chip = _chip("bluetooth-active-symbolic")
        self.net_chip = _chip("network-wireless-symbolic")
        self.net_chip.set_visible(False)

        row.append(self.top_button)
        row.append(self.chat_button)
        row.append(self.add_button)
        row.append(spacer)
        row.append(self.bt_chip)
        row.append(self.net_chip)
        row.append(self.clear_clipboard_button)
        row.append(self.volume_button)
        row.append(self.settings_button)
        self.content.append(row)

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

    # -- media player section ---------------------------------------------

    def _build_player(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.player_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        art_frame = Gtk.Box()
        art_frame.add_css_class("art-frame")
        art_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.art = Gtk.Picture()
        self.art.set_size_request(92, 92)
        self.art.set_content_fit(Gtk.ContentFit.COVER)
        art_frame.append(self.art)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        meta.set_valign(Gtk.Align.CENTER)
        meta.set_hexpand(True)
        self.title = _label("track-title", 24)
        self.artist = _label("track-artist", 30)
        self.album = _label("track-album", 34)
        for w in (self.title, self.artist, self.album):
            meta.append(w)

        head.append(art_frame)
        head.append(meta)

        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
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

        self.player_box.append(head)
        self.player_box.append(seek_box)
        self.player_box.append(controls)
        page.append(self.player_box)

        # idle header shown when nothing plays
        self.idle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.idle_box.set_halign(Gtk.Align.CENTER)
        self.big_clock = Gtk.Label()
        self.big_clock.add_css_class("track-title")
        self.big_date = Gtk.Label()
        self.big_date.add_css_class("track-artist")
        self.idle_box.append(self.big_clock)
        self.idle_box.append(self.big_date)
        page.append(self.idle_box)
        self._add_feature_page("music", "Music", page)

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
        self.sys_label = Gtk.Label()
        self.sys_label.add_css_class("sys-stats")
        self.sys_label.set_visible(self.system is not None)
        if self.system is not None:
            self.system.connect("changed", self._on_system)
        stats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        stats.set_halign(Gtk.Align.CENTER)
        stats.append(self.sys_label)
        self._add_feature_page("system", "System stats", stats)

    def _build_settings_page(self):
        from linux_notch.ui.settings import SettingsPanel

        panel = SettingsPanel(self.cfg, self.on_settings)
        self._add_feature_page("settings", "Settings", panel)

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

    def _build_spotify_page(self):
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.spotify_status = Gtk.Label(
            label="", wrap=True, justify=Gtk.Justification.CENTER)
        self.spotify_art = Gtk.Picture()
        self.spotify_art.set_size_request(100, 100)
        self.spotify_art.set_content_fit(Gtk.ContentFit.COVER)
        self.spotify_art.set_halign(Gtk.Align.CENTER)
        self.spotify_title = Gtk.Label(
            label="Spotify", wrap=True, justify=Gtk.Justification.CENTER)
        self.spotify_title.add_css_class("track-title")
        self.spotify_artist = Gtk.Label(
            label="", wrap=True, justify=Gtk.Justification.CENTER)
        self.spotify_artist.add_css_class("track-artist")
        self.spotify_progress = Gtk.ProgressBar()
        self.spotify_progress.add_css_class("spotify-progress")

        controls = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        controls.set_halign(Gtk.Align.CENTER)
        self.spotify_prev = _media_btn("media-skip-backward-symbolic")
        self.spotify_play = _media_btn(
            "media-playback-start-symbolic", main=True)
        self.spotify_next = _media_btn("media-skip-forward-symbolic")
        self.spotify_prev.connect(
            "clicked", lambda *_: self._spotify_control("previous_for"))
        self.spotify_play.connect(
            "clicked", lambda *_: self._spotify_control("play_pause_for"))
        self.spotify_next.connect(
            "clicked", lambda *_: self._spotify_control("next_for"))
        controls.append(self.spotify_prev)
        controls.append(self.spotify_play)
        controls.append(self.spotify_next)

        launch = Gtk.Button(label="Open Spotify")
        launch.add_css_class("feature-btn")
        launch.connect("clicked", self._open_spotify)
        self.spotify_launch = launch

        install = Gtk.Button(label="Get Spotify")
        install.add_css_class("feature-btn")
        install.connect("clicked", self._open_spotify_install_page)
        self.spotify_install = install

        body.append(self.spotify_art)
        body.append(self.spotify_title)
        body.append(self.spotify_artist)
        body.append(self.spotify_progress)
        body.append(self.spotify_status)
        body.append(controls)
        body.append(launch)
        body.append(install)
        self._add_feature_page("spotify", "Spotify", body)
        if isinstance(self.media, MprisService):
            self.media.connect("error", self._on_spotify_error)
        self.refresh_spotify()

    def _on_spotify_error(self, _service, message):
        self.spotify_status.set_label(f"Spotify control failed: {message}")

    def _spotify_player(self):
        return getattr(self.media, "spotify_player", None)

    def refresh_spotify(self):
        if not hasattr(self, "spotify_status"):
            return
        player = self._spotify_player()
        if player is None:
            self.spotify_art.set_paintable(None)
            self.spotify_title.set_label("Spotify")
            self.spotify_artist.set_label("")
            self.spotify_progress.set_fraction(0)
            self.spotify_prev.set_sensitive(False)
            self.spotify_play.set_sensitive(False)
            self.spotify_next.set_sensitive(False)
            self.spotify_launch.set_visible(self.spotify_available)
            self.spotify_install.set_visible(not self.spotify_available)
            self.spotify_status.set_label(
                "Spotify is installed but not running."
                if self.spotify_available else "Spotify is not installed.")
            return

        self.spotify_launch.set_visible(False)
        self.spotify_install.set_visible(False)
        self.spotify_status.set_label(
            "Playing" if player.status == "Playing" else "Not playing")
        self.spotify_title.set_label(player.title or "Unknown track")
        self.spotify_artist.set_label(player.artist or "")
        self.spotify_prev.set_sensitive(player.can_prev)
        self.spotify_play.set_sensitive(True)
        self.spotify_next.set_sensitive(player.can_next)
        self.spotify_play.set_icon_name(
            "media-playback-pause-symbolic"
            if player.status == "Playing"
            else "media-playback-start-symbolic")
        if player.art_path and os.path.exists(player.art_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    player.art_path, 100, 100, True)
                self.spotify_art.set_paintable(
                    Gdk.Texture.new_for_pixbuf(pixbuf))
            except GLib.Error as error:
                logger.warning("Could not load Spotify album art: %s", error)
        else:
            self.spotify_art.set_paintable(None)
        self._sync_spotify_timer()

    def _spotify_control(self, method: str):
        player = self._spotify_player()
        callback = getattr(self.media, method, None)
        if player is not None and callback is not None:
            callback(SPOTIFY_BUS_NAME)

    def _open_spotify(self, *_):
        try:
            if not Gio.AppInfo.launch_default_for_uri("spotify:", None):
                self.spotify_status.set_label(
                    "No application could open Spotify.")
        except GLib.Error as error:
            self.spotify_status.set_label(str(error))

    def _open_spotify_install_page(self, *_):
        try:
            if not Gio.AppInfo.launch_default_for_uri(
                    "https://flathub.org/apps/com.spotify.Client", None):
                self.spotify_status.set_label(
                    "No application could open the Flathub link.")
        except GLib.Error as error:
            self.spotify_status.set_label(str(error))

    def _sync_spotify_timer(self):
        player = self._spotify_player()
        want = bool(
            self.get_mapped()
            and self.page_stack.get_visible_child_name() == "spotify"
            and player is not None
            and player.status == "Playing"
        )
        if want and not self._spotify_timer:
            self._spotify_timer = GLib.timeout_add_seconds(
                1, self._poll_spotify_position)
        elif not want and self._spotify_timer:
            GLib.source_remove(self._spotify_timer)
            self._spotify_timer = 0

    def _poll_spotify_position(self):
        get_position = getattr(self.media, "get_position_for", None)
        if get_position is None or self._spotify_player() is None:
            self._spotify_timer = 0
            return GLib.SOURCE_REMOVE
        get_position(SPOTIFY_BUS_NAME, self._on_spotify_position)
        return GLib.SOURCE_CONTINUE

    def _on_spotify_position(self, position_us: int):
        player = self._spotify_player()
        if player is not None and player.length_us > 0:
            self.spotify_progress.set_fraction(
                min(1.0, position_us / player.length_us))

    def _build_home_page(self):
        layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
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

        feature_card = Gtk.Box()
        feature_card.add_css_class("home-card")
        feature_card.add_css_class("home-feature-card")
        feature_card.set_hexpand(True)
        grid = Gtk.Grid()
        grid.add_css_class("home-feature-grid")
        grid.set_column_homogeneous(True)
        grid.set_column_spacing(6)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        modules = self.cfg.get("modules", {})
        column = 0
        row = 0
        for feature_id, title, icon, module in FEATURES:
            if module and not modules.get(module, True):
                continue
            if feature_id not in self.pages:
                continue
            button = Gtk.Button()
            button.add_css_class("home-feature-btn")
            button.set_tooltip_text(title)
            content = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            image = Gtk.Image.new_from_icon_name(icon)
            image.set_pixel_size(18)
            label = Gtk.Label(label=title)
            label.add_css_class("feature-btn-label")
            content.append(image)
            content.append(label)
            button.set_child(content)
            button.connect(
                "clicked", lambda _button, name=feature_id: self.show_page(name))
            grid.attach(button, column, row, 1, 1)
            column += 1
            if column == 2:
                column = 0
                row += 1

        feature_card.append(grid)
        layout.append(character_card)
        layout.append(feature_card)
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
        p = self.media.active
        self.refresh_spotify()
        self._refresh_home_status()
        has = p is not None
        self.player_box.set_visible(has)
        self.idle_box.set_visible(not has)
        if not has:
            self._refresh_big_clock()
            self._sync_pos_timer()
            return
        self.title.set_label(p.title or "Unknown track")
        self.artist.set_label(p.artist or "")
        self.album.set_label(p.album or "")
        self.artist.set_visible(bool(p.artist))
        self.album.set_visible(bool(p.album))
        if p.art_path:
            try:
                # load at display size so the picture's natural size is 92px
                # and never inflates the card
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    p.art_path, 92, 92, False)
                self.art.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
            except GLib.Error:
                self.art.set_paintable(None)
        else:
            self.art.set_paintable(None)
        playing = p.status == "Playing"
        self.btn_play.set_icon_name(
            "media-playback-pause-symbolic" if playing
            else "media-playback-start-symbolic")
        self.btn_prev.set_sensitive(p.can_prev)
        self.btn_next.set_sensitive(p.can_next)
        total = p.length_us
        self.seek.set_range(0, max(1, total))
        self.time_total.set_label(_fmt_us(total))
        self._sync_pos_timer()
        self._poll_position()

    def refresh_battery(self):
        if not self.power.available:
            self.battery_tile.set_visible(False)
            return
        self.ring.update(self.power.percentage, self.power.charging)
        suffix = " ⚡" if self.power.charging else ""
        self.batt_label.set_label(f"{self.power.percentage:.0f}%{suffix}")

    def refresh_volume(self, percent: int, muted: bool = False):
        self.vol.set_value(percent)
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

    def _on_system(self, _svc, cpu, ram, ram_gib):
        self.sys_label.set_label(
            f"CPU {cpu}%   ·   RAM {ram_gib:.1f} GiB ({ram}%)")

    # -- lifecycle ----------------------------------------------------------

    def _on_map(self):
        self.refresh_media()
        self.refresh_spotify()
        self.refresh_battery()
        self._refresh_big_clock()
        if self.weather is not None:
            self.weather.request()
        if self.system is not None:
            self.system.start()

    def _on_unmap(self):
        if self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0
        if self._spotify_timer:
            GLib.source_remove(self._spotify_timer)
            self._spotify_timer = 0
        if self.system is not None:
            self.system.stop()

    # -- seek bar ----------------------------------------------------------

    def _sync_pos_timer(self):
        playing = self.media.active and self.media.active.status == "Playing"
        want = bool(playing) and self.get_mapped()
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
        Gio.Subprocess.new(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@",
             f"{int(max(0, min(100, value)))}%"],
            Gio.SubprocessFlags.NONE)
        return False

    def _refresh_big_clock(self):
        fmt = "%H:%M" if self.cfg.get("clock_24h", True) else "%I:%M %p"
        self.big_clock.set_label(time.strftime(fmt))
        self.big_date.set_label(time.strftime("%A %d %B"))


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
