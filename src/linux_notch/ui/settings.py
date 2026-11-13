"""Settings panel embedded in the expanded island."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from linux_notch import config
from linux_notch.services.sounds import SOUND_NAMES, play_sound

MODULES = [
    ("music", "Music", "MPRIS players: full controls and album art"),
    ("volume_osd", "Volume OSD", "Peek on volume changes"),
    ("battery", "Battery", "Charge ring and plug/unplug peeks"),
    ("notifications", "Notifications", "Mirror notifications as peeks"),
    ("network", "Network", "Connectivity chip and peeks"),
    ("bluetooth", "Bluetooth", "Connected device chip and peeks"),
    ("weather", "Weather", "Weather tile in the expanded card"),
    ("system", "System stats", "CPU and RAM readout while expanded"),
    ("toggles", "Quick toggles", "Mute, mic, caffeine, screenshot"),
    ("claude_usage", "Claude usage (opt-in)",
     "Reads Claude Code credentials to fetch usage from Anthropic"),
    ("clipboard", "Clipboard history",
     "Local-only clipboard history; recording is paused by default"),
    ("spotify", "Spotify", "Spotify controls through MPRIS over D-Bus"),
    ("todos", "ToDo list", "Create and track your local tasks"),
    ("face", "Face unlock", "Local face authentication for lock screen"),
]


class SettingsPanel(Gtk.Box):
    def __init__(self, cfg: dict, on_apply):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.cfg = cfg
        self.on_apply = on_apply

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
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
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        pos = Adw.PreferencesGroup(title="Position")
        pos.add(self._switch(
            "Sit on top of panels",
            "Overlap the bar at the screen edge instead of sitting below it",
            "overlap_panel"))

        margin = Adw.SpinRow.new_with_range(0, 80, 1)
        margin.set_title("Top margin")
        margin.set_subtitle("Distance from the screen edge, px")
        margin.set_value(self.cfg["margin_top"])
        margin.connect("notify::value", lambda r, _p: (
            self.cfg.__setitem__("margin_top", int(r.get_value())),
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
        return page

    def _modules_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        group = Adw.PreferencesGroup(
            title="Modules",
            description="Turning a module off removes its widgets, peeks "
                        "and background listeners entirely")
        for key, title, subtitle in MODULES:
            group.add(self._switch(title, subtitle, key,
                                   structural=True, mod=True))
        page.append(group)

        weather = Adw.PreferencesGroup(title="Weather")
        city = Adw.EntryRow(title="Location (empty = automatic)")
        city.set_text(self.cfg["weather_city"])
        city.connect("apply", lambda r: (
            self.cfg.__setitem__("weather_city", r.get_text().strip()),
            self._apply(structural=True)))
        city.set_show_apply_button(True)
        weather.add(city)
        page.append(weather)
        return page
