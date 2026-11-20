"""Settings panel embedded in the expanded island."""

from __future__ import annotations

import os

from gi.repository import Adw, Gdk, Gtk

from linux_notch import config
from linux_notch.services.sounds import SOUND_NAMES, play_sound
from linux_notch.ui.theme import ACTIVE, PALETTE_LABELS

MODULES = [
    ("music", "Music", "Play local audio files from your music folder"),
    ("volume_osd", "Volume OSD", "Peek on volume changes"),
    ("battery", "Battery", "Charge ring and plug/unplug peeks"),
    ("notifications", "Notifications", "Mirror notifications as peeks"),
    ("network", "Network", "Connectivity chip and peeks"),
    ("bluetooth", "Bluetooth", "Connected device chip and peeks"),
    ("weather", "Weather", "Weather tile in the expanded card"),
    ("system", "Widgets", "Add desktop widgets in a future update"),
    ("screen_time", "Screen Time",
     "Local active desktop time with a weekly usage chart"),
    ("toggles", "Quick toggles", "Mute, mic, caffeine, screenshot"),
    ("claude_usage", "Claude usage (opt-in)",
     "Reads Claude Code credentials to fetch usage from Anthropic"),
    ("clipboard", "Clipboard history",
     "Local-only clipboard history; recording is paused by default"),
    ("todos", "ToDo list", "Create and track your local tasks"),
    ("face", "Face unlock", "Local face authentication for lock screen"),
    ("terminal", "Terminal", "Embedded VTE shell; starts on first use"),
]
VISUALIZER_MODES = ("auto", "real", "synthetic")
VISUALIZER_LABELS = (
    "Auto (real audio with synthetic fallback)",
    "Real audio sync (beta)",
    "Synthetic only",
)


class SettingsPanel(Gtk.Box):
    def __init__(self, cfg: dict, on_apply):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("settings-panel")
        self.cfg = cfg
        self.on_apply = on_apply

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.add_css_class("settings-content")
        content.append(self._island_page())
        content.append(self._modules_page())
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(360)
        scroll.set_max_content_height(420)
        scroll.set_child(content)
        scroll.set_vexpand(True)
        self.append(scroll)

    # -- helpers -----------------------------------------------------------

    def _apply(self, structural: bool = False):
        config.save(self.cfg)
        self.on_apply(structural)

    def _switch(self, title: str, subtitle: str, key: str,
                structural: bool = False, mod: bool = False):
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.set_active(self.cfg["modules"][key] if mod else self.cfg[key])
        def on_change(r, _p):
            if mod:
                self.cfg["modules"][key] = r.get_active()
            else:
                self.cfg[key] = r.get_active()
            self._apply(structural)
        row.connect("notify::active", on_change)
        return row

    # -- pages -------------------------------------------------------------

    def _island_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.add_css_class("settings-page")

        pos = Adw.PreferencesGroup(title="Position")
        pos.add_css_class("settings-group")
        pos.add(self._switch(
            "Sit on top of panels",
            "Overlap the bar at the screen edge instead of sitting below it",
            "overlap_panel"))

        margin = Adw.SpinRow.new_with_range(-40, 80, 1)
        margin.set_title("Bottom margin")
        margin.set_subtitle("Negative values move the notch closer to the edge")
        margin.set_value(self.cfg["margin_bottom"])
        margin.connect("notify::value", lambda r, _p: (
            self.cfg.__setitem__("margin_bottom", int(r.get_value())),
            self._apply()))
        pos.add(margin)

        monitors = ["Primary"]
        display = Gdk.Display.get_default()
        if display:
            items = display.get_monitors()
            monitors += [items.get_item(i).get_connector() or f"#{i}"
                         for i in range(items.get_n_items())]
        combo = Adw.ComboRow(title="Monitor")
        combo.set_model(Gtk.StringList.new(monitors))
        try:
            combo.set_selected(monitors.index(self.cfg["monitor"]))
        except ValueError:
            combo.set_selected(0)
        def on_monitor(r, _p):
            i = r.get_selected()
            self.cfg["monitor"] = "" if i == 0 else monitors[i]
            self._apply()
        combo.connect("notify::selected", on_monitor)
        pos.add(combo)

        overlay = Adw.SwitchRow(
            title="Above fullscreen apps",
            subtitle="Keep the island visible over games and videos")
        overlay.set_active(self.cfg["layer"] == "overlay")
        def on_overlay_change(row, _property):
            enabled = row.get_active()
            self.cfg["layer"] = "overlay" if enabled else "top"
            self.cfg["fullscreen_policy"] = "show" if enabled else "hide"
            self._apply()
        overlay.connect("notify::active", on_overlay_change)
        pos.add(overlay)
        page.append(pos)

        look = Adw.PreferencesGroup(title="Look")
        look.add_css_class("settings-group")
        theme = Adw.ComboRow(title="Notch color theme")
        theme_keys = tuple(PALETTE_LABELS)
        theme.set_model(Gtk.StringList.new([
            PALETTE_LABELS[key] for key in theme_keys
        ]))
        current_theme = self.cfg.get("notch_theme", ACTIVE)
        theme.set_selected(
            theme_keys.index(current_theme)
            if current_theme in theme_keys
            else theme_keys.index(ACTIVE)
        )

        def on_theme_changed(row, _property):
            self.cfg["notch_theme"] = theme_keys[row.get_selected()]
            self._apply()

        theme.connect("notify::selected", on_theme_changed)
        look.add(theme)
        opacity = Adw.SpinRow.new_with_range(30, 100, 5)
        opacity.set_title("Opacity")
        opacity.set_subtitle("Island background transparency, %")
        opacity.set_value(round(float(self.cfg.get("opacity", 0.97)) * 100))
        opacity.connect("notify::value", lambda r, _p: (
            self.cfg.__setitem__("opacity", round(r.get_value() / 100, 2)),
            self._apply()))
        look.add(opacity)
        color = Adw.ActionRow(title="Accent color")
        btn = Gtk.ColorDialogButton()
        btn.set_dialog(Gtk.ColorDialog(with_alpha=False))
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg["accent"])
        btn.set_rgba(rgba)
        btn.set_valign(Gtk.Align.CENTER)
        def on_color(b, _p):
            c = b.get_rgba()
            self.cfg["accent"] = "#%02x%02x%02x" % (
                int(c.red * 255), int(c.green * 255), int(c.blue * 255))
            self._apply()
        btn.connect("notify::rgba", on_color)
        color.add_suffix(btn)
        look.add(color)
        look.add(self._switch("24-hour clock", "", "clock_24h"))
        page.append(look)

        mochi = Adw.PreferencesGroup(
            title="Mochi",
            description="Configure Mochi's sound effects")
        mochi.add_css_class("settings-group")

        mochi.add(self._switch(
            "Sound effects",
            "Play Mochi reactions and island interaction sounds",
            "sound_enabled",
        ))
        volume = Adw.SpinRow.new_with_range(0, 100, 1)
        volume.set_title("Sound volume")
        volume.set_subtitle("Mochi sound-effect volume")
        volume.set_value(round(float(self.cfg.get("sound_volume", 0.12)) * 100))
        volume.connect("notify::value", lambda row, _property: (
            self.cfg.__setitem__("sound_volume", row.get_value() / 100),
            self._apply()))
        mochi.add(volume)

        sound_picker = Adw.ComboRow(title="Sound")
        sound_picker.set_model(Gtk.StringList.new(list(SOUND_NAMES)))
        mochi.add(sound_picker)
        preview = Adw.ActionRow(
            title="Preview sound",
            subtitle="Play the selected bundled effect")
        preview_button = Gtk.Button(label="Play")
        preview_button.set_valign(Gtk.Align.CENTER)
        preview_button.connect(
            "clicked",
            lambda *_: play_sound(
                SOUND_NAMES[sound_picker.get_selected()], self.cfg))
        preview.add_suffix(preview_button)
        mochi.add(preview)
        page.append(mochi)

        behavior = Adw.PreferencesGroup(title="Behavior")
        behavior.add_css_class("settings-group")
        peek = Adw.SpinRow.new_with_range(0.8, 6.0, 0.2)
        peek.set_digits(1)
        peek.set_title("Peek duration")
        peek.set_subtitle("Seconds a volume/notification peek stays up")
        peek.set_value(self.cfg["peek_seconds"])
        peek.connect("notify::value", lambda r, _p: (
            self.cfg.__setitem__("peek_seconds", round(r.get_value(), 1)),
            self._apply()))
        behavior.add(peek)
        page.append(behavior)

        visualizer = Adw.PreferencesGroup(
            title="Closed-notch visualizer",
            description=(
                "Real sync listens to the default output monitor while local "
                "music plays. It never uses the microphone or saves audio."
            ),
        )
        visualizer.add_css_class("settings-group")
        mode = Adw.ComboRow(title="Visualizer mode")
        mode.set_model(Gtk.StringList.new(list(VISUALIZER_LABELS)))
        selected_mode = self.cfg.get("viz_mode", "auto")
        if selected_mode not in VISUALIZER_MODES:
            selected_mode = "auto"
        mode.set_selected(VISUALIZER_MODES.index(selected_mode))

        def on_mode_changed(row, _property):
            self.cfg["viz_mode"] = VISUALIZER_MODES[row.get_selected()]
            self._apply()

        mode.connect("notify::selected", on_mode_changed)
        visualizer.add(mode)
        status_row = Adw.ActionRow(title="Real audio status")
        self.visualizer_status = Gtk.Label(
            label="Waiting for local music playback",
            xalign=1,
            wrap=True,
        )
        self.visualizer_status.add_css_class("tile-sub")
        self.visualizer_status.set_max_width_chars(32)
        status_row.add_suffix(self.visualizer_status)
        visualizer.add(status_row)
        page.append(visualizer)
        return page

    def _modules_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.add_css_class("settings-page")
        music = Adw.PreferencesGroup(
            title="Music",
            description="Choose the folder containing your local audio files",
        )
        music.add_css_class("settings-group")
        music_row = Adw.ActionRow(
            title="Music folder",
            subtitle="Audio files in this folder and its subfolders",
        )
        self.music_directory_entry = Gtk.Entry()
        self.music_directory_entry.set_text(
            os.path.expanduser(self.cfg.get("music_directory", "~/Music")))
        self.music_directory_entry.set_placeholder_text("~/Music")
        self.music_directory_entry.set_width_chars(22)
        self.music_directory_entry.set_hexpand(True)
        self.music_directory_entry.set_valign(Gtk.Align.CENTER)
        self.music_directory_entry.connect(
            "activate", self._apply_music_directory)
        music_row.add_suffix(self.music_directory_entry)
        browse_music = Gtk.Button(label="Browse")
        browse_music.set_valign(Gtk.Align.CENTER)
        browse_music.connect("clicked", self._browse_music_directory)
        music_row.add_suffix(browse_music)
        save_music = Gtk.Button(label="Save")
        save_music.set_valign(Gtk.Align.CENTER)
        save_music.connect("clicked", self._apply_music_directory)
        music_row.add_suffix(save_music)
        music.add(music_row)
        self.music_directory_status = Gtk.Label(
            label="", xalign=0, wrap=True)
        self.music_directory_status.add_css_class("tile-sub")
        self.music_directory_status.set_margin_start(12)
        self.music_directory_status.set_margin_end(12)
        music.add(self.music_directory_status)
        page.append(music)

        group = Adw.PreferencesGroup(
            title="Modules",
            description="Turning a module off removes its widgets, peeks "
                        "and background listeners entirely")
        group.add_css_class("settings-group")
        group.add_css_class("settings-modules")
        for key, title, subtitle in MODULES:
            group.add(self._switch(title, subtitle, key,
                                   structural=True, mod=True))
        page.append(group)

        weather = Adw.PreferencesGroup(title="Weather")
        weather.add_css_class("settings-group")
        city_row = Adw.ActionRow(
            title="Location",
            subtitle="Enter a city name, or leave empty for automatic",
        )
        self.weather_city_entry = Gtk.Entry()
        self.weather_city_entry.set_text(self.cfg["weather_city"])
        self.weather_city_entry.set_placeholder_text("City name")
        self.weather_city_entry.set_width_chars(16)
        self.weather_city_entry.set_hexpand(True)
        self.weather_city_entry.set_valign(Gtk.Align.CENTER)
        self.weather_city_entry.set_focusable(True)
        self.weather_city_entry.connect("activate", self._apply_weather_city)
        city_row.add_suffix(self.weather_city_entry)
        apply_city = Gtk.Button(label="Save")
        apply_city.set_valign(Gtk.Align.CENTER)
        apply_city.connect("clicked", self._apply_weather_city)
        city_row.add_suffix(apply_city)
        weather.add(city_row)
        page.append(weather)
        return page

    def _browse_music_directory(self, *_):
        chooser = Gtk.FileChooserNative.new(
            "Choose Music Folder",
            None,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Select",
            "Cancel",
        )
        chooser.connect("response", self._on_music_directory_selected)
        chooser.show()

    def _on_music_directory_selected(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = chooser.get_file()
            if selected is not None and selected.get_path():
                self.music_directory_entry.set_text(selected.get_path())
        chooser.destroy()

    def _apply_music_directory(self, *_):
        directory = os.path.abspath(
            os.path.expanduser(self.music_directory_entry.get_text().strip())
        )
        if not os.path.isdir(directory):
            self.music_directory_status.set_label(
                f"Folder not found: {directory}")
            return
        self.cfg["music_directory"] = directory
        self.music_directory_status.set_label("Music folder saved.")
        self._apply(structural=True)

    def _apply_weather_city(self, *_):
        self.cfg["weather_city"] = self.weather_city_entry.get_text().strip()
        self._apply(structural=True)

    def set_visualizer_status(self, message: str) -> None:
        self.visualizer_status.set_label(message)
