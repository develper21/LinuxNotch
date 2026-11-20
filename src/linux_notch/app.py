"""Application entry point: layer-shell window, service wiring, CLI."""

from __future__ import annotations

import ctypes
import logging
import os
import sys

# gtk4-layer-shell must be resolved before libwayland-client, which GTK pulls
# in on display init — preload it globally or the surface won't anchor.
try:
    ctypes.CDLL("libgtk4-layer-shell.so.0", mode=ctypes.RTLD_GLOBAL)
except OSError:
    pass


def _ensure_backend_env() -> None:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" and "GDK_BACKEND" not in os.environ:
        from linux_notch.desktop.layer_shell import LayerShellBackend

        if not LayerShellBackend.is_supported():
            from linux_notch.desktop.gnome import GnomeBackend

            if not GnomeBackend.helper_available():
                from linux_notch.desktop.x11 import X11Backend

                if X11Backend.usable():
                    os.environ["GDK_BACKEND"] = "x11"


_ensure_backend_env()

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from linux_notch import APP_ID, __version__, config  # noqa: E402
from linux_notch.activity.dbus_service import ActivityDBusService  # noqa: E402
from linux_notch.desktop import choose_backend  # noqa: E402
from linux_notch.services.audio import AudioService  # noqa: E402
from linux_notch.services.bluetooth import BluetoothService  # noqa: E402
from linux_notch.services.clipboard import ClipboardHistoryService  # noqa: E402
from linux_notch.services.claude_usage import ClaudeUsageService  # noqa: E402
from linux_notch.services.local_music import LocalMusicPlayer  # noqa: E402
from linux_notch.services.mail import MailService  # noqa: E402
from linux_notch.services.network import NetworkService  # noqa: E402
from linux_notch.services.notify import NotifyService  # noqa: E402
from linux_notch.services.power import PowerService  # noqa: E402
from linux_notch.services.screen_time import ScreenTimeService  # noqa: E402
from linux_notch.services.system import SystemService  # noqa: E402
from linux_notch.services.weather import WeatherService  # noqa: E402
from linux_notch.services.sounds import play_sound  # noqa: E402
from linux_notch.ui.island import Island  # noqa: E402
from linux_notch.ui.theme import ACTIVE as ACTIVE_NOTCH_THEME  # noqa: E402
from linux_notch.ui.theme import css_definitions  # noqa: E402

CSS_PATH = os.path.join(os.path.dirname(__file__), "ui", "style.css")
logger = logging.getLogger(__name__)


class LostIsland(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.win: Gtk.Window | None = None
        self.island: Island | None = None
        self._css_provider: Gtk.CssProvider | None = None
        self._backend = None
        self._activity_service: ActivityDBusService | None = None
        self.mail_service = MailService()
        self.screen_time = ScreenTimeService()
        toggle_terminal = Gio.SimpleAction.new("toggle-terminal", None)
        toggle_terminal.connect("activate", lambda *_: self.toggle_terminal())
        self.add_action(toggle_terminal)
        for opt, short, desc in (
            ("toggle", "t", "Expand/collapse the island"),
            ("settings", "s", "Open settings in the island"),
            ("quit", "q", "Quit a running instance"),
            ("version", "v", "Print version"),
            ("setup-claude-usage", "\0",
             "Install the Claude Code hook for the usage module"),
            ("remove-claude-usage", "\0",
             "Remove the Claude Code usage hook"),
        ):
            self.add_main_option(opt, ord(short) if short != "\0" else 0,
                                 GLib.OptionFlags.NONE,
                                 GLib.OptionArg.NONE, desc, None)

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict()
        if opts.contains("version"):
            cmdline.print_literal(f"linux-notch {__version__}\n")
            return 0
        if opts.contains("setup-claude-usage"):
            from linux_notch import claude_setup
            cmdline.print_literal(claude_setup.install() + "\n")
            return 0
        if opts.contains("remove-claude-usage"):
            from linux_notch import claude_setup
            cmdline.print_literal(claude_setup.uninstall() + "\n")
            return 0
        if opts.contains("quit"):
            self.quit()
            return 0
        self.do_activate()
        if opts.contains("toggle") and self.island:
            self.island.toggle()
        if opts.contains("settings"):
            self.open_settings()
        return 0

    def toggle_terminal(self) -> None:
        if self.island is None:
            self.do_activate()
        if self.island is None:
            return
        expanded = self.island.expanded
        if "terminal" not in expanded.pages:
            self.open_settings()
            return
        if (
            self.island.state == "expanded"
            and expanded.page_stack.get_visible_child_name() == "terminal"
        ):
            self.island.collapse()
            return
        self.island.expand()
        expanded.show_page("terminal")

    def do_activate(self):
        if self.win:
            return
        self.hold()  # stay alive across island rebuilds
        self.cfg = config.load()
        config.write_default()
        self._activity_service = ActivityDBusService(
            on_activities_changed=self._on_activities_changed
        )
        self._activity_service.start()
        play_sound("greeting", self.cfg)
        self._load_css()
        self._build_services()
        self._sync_screen_time()
        self._build_window()

    def _on_activities_changed(self, activities):
        if self.island:
            latest = activities[-1].data if activities else None
            self.island.pill.show_activity(latest)
            self.island.show_activity(latest)

    def _on_monitors_changed(self):
        if self._backend and self.win:
            self._backend.attach(self.win, {**self.cfg, "app_id": APP_ID})

    # -- window ------------------------------------------------------------

    def _build_window(self):
        self.win = Gtk.Window(application=self)
        self.win.set_decorated(False)
        self.win.set_resizable(False)
        # only THIS window is transparent (so the rounded island floats);
        # other app windows (settings) keep their solid theme background
        self.win.add_css_class("island-window")

        self._backend = choose_backend()
        print(f"[linux-notch] Desktop backend selected: {self._backend.name}", flush=True)
        self._backend.attach(self.win, {**self.cfg, "app_id": APP_ID})
        self._backend.on_monitors_changed(self._on_monitors_changed)

        self.island = Island(self.cfg, self.media, self.power,
                             weather=self.weather, system=self.system,
                             on_settings=self.apply_config,
                             clipboard=self.clipboard,
                             on_terminal_focus=self._focus_terminal,
                             mail_service=self.mail_service,
                             screen_time=self.screen_time)
        self._wire_services()
        self.win.set_child(self.island)
        self.win.present()

    def _focus_terminal(self) -> None:
        if self.win is not None:
            self.win.present()
        focus = getattr(self._backend, "focus", None)
        if focus is not None:
            try:
                focus()
            except GLib.Error as error:
                logger.warning("GNOME helper could not focus terminal: %s", error)
    def _load_css(self):
        display = Gdk.Display.get_default()
        if self._css_provider:
            Gtk.StyleContext.remove_provider_for_display(
                display, self._css_provider)
        provider = Gtk.CssProvider()
        accent = self.cfg.get("accent", "#ff9f0a")
        with open(CSS_PATH) as f:
            css = (
                css_definitions(
                    self.cfg.get("notch_theme", ACTIVE_NOTCH_THEME),
                    accent,
                )
                + f.read()
            )
        provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css_provider = provider

    # -- settings ----------------------------------------------------------

    def open_settings(self):
        if self.island:
            self.island.expand()
            self.island.expanded.show_page("settings")

    def apply_config(self, structural: bool = False):
        """Called by the settings window after each change."""
        if structural:
            self.rebuild()
            return
        self._load_css()
        if self._backend and self.win:
            self._backend.attach(self.win, {**self.cfg, "app_id": APP_ID})
        if self.island:
            self.island.set_opacity(float(self.cfg.get("opacity", 0.97)))
            self.island.set_theme(
                self.cfg.get("notch_theme", ACTIVE_NOTCH_THEME))
            self.island.pill.mochi.outfit_changed()
            self.island.on_media_changed()
            self.island.expanded.refresh_battery()
            self.island.pill.update_visualizer()

    def rebuild(self):
        if self.clipboard:
            self.clipboard.set_recording(False)
        if self.island:
            self.island.stop_visualizer()
        if hasattr(self, "media") and hasattr(self.media, "stop"):
            self.media.stop()
        if self._backend:
            self._backend.shutdown()
            self._backend = None
        if self.win:
            self.win.destroy()
        self.win = self.island = None
        self._build_services()
        self._sync_screen_time()
        self._build_window()

    def _sync_screen_time(self):
        if self.cfg.get("modules", {}).get("screen_time", True):
            self.screen_time.start()
        else:
            self.screen_time.stop()

    # -- services ----------------------------------------------------------

    def _build_services(self):
        mods = self.cfg.get("modules", {})
        self.media = (
            LocalMusicPlayer(self.cfg.get("music_directory", "~/Music"))
            if mods.get("music", True)
            else _NullMedia()
        )
        self.power = PowerService()
        self.audio = AudioService() if mods.get("volume_osd", True) else None
        self.notifier = NotifyService() if mods.get("notifications", True) else None
        self.network = NetworkService() if mods.get("network", True) else None
        self.bluetooth = (BluetoothService()
                          if mods.get("bluetooth", True) else None)
        self.weather = (WeatherService(self.cfg.get("weather_city", ""))
                        if mods.get("weather", True) else None)
        self.system = SystemService() if mods.get("system", True) else None
        self.claude = (
            ClaudeUsageService(self.cfg.get("claude_refresh", 60))
            if mods.get("claude_usage", False)
            else None
        )
        self.clipboard = None
        if mods.get("clipboard", True):
            display = Gdk.Display.get_default()
            clipboard = display.get_clipboard() if display else None
            self.clipboard = ClipboardHistoryService(clipboard)

    def _wire_services(self):
        isl = self.island
        if isinstance(self.media, LocalMusicPlayer):
            self.media.connect("changed", lambda *_: isl.on_media_changed())
        self.power.connect(
            "changed", lambda *_: isl.expanded.refresh_battery())
        if self.cfg.get("modules", {}).get("battery", True):
            self.power.connect(
                "plug-event",
                lambda _s, plugged: isl.show_peek(
                    isl.peek.show_battery, self.power.percentage, plugged))
        if self.audio:
            self.audio.connect(
                "volume",
                lambda _s, p, m: (isl.show_peek(isl.peek.show_volume, p, m),
                                  isl.expanded.refresh_volume(p, m)))
        if self.notifier:
            self.notifier.connect(
                "notified",
                lambda _s, app, summary, body, icon: isl.show_peek(
                    isl.peek.show_notification, app, summary, body, icon))
        if self.network:
            self.network.connect(
                "changed",
                lambda _s, name, kind, up: (
                    isl.show_peek(isl.peek.show_network, name, kind, up),
                    isl.expanded.refresh_network(name, kind, up)))
            isl.expanded.refresh_network(
                self.network.name, self.network.kind, self.network.connected)
        if self.bluetooth:
            self.bluetooth.connect(
                "changed",
                lambda _s, dev, up, batt: (
                    isl.show_peek(isl.peek.show_bluetooth, dev, up),
                    isl.expanded.refresh_bluetooth(dev, up, batt)))
            isl.expanded.refresh_bluetooth(
                self.bluetooth.device, self.bluetooth.connected,
                self.bluetooth.battery)
        else:
            isl.expanded.refresh_bluetooth("", False, -1)

    def do_shutdown(self):
        if self.clipboard:
            self.clipboard.set_recording(False)
        if self.island:
            self.island.stop_visualizer()
        if hasattr(self, "media") and hasattr(self.media, "stop"):
            self.media.stop()
        self.mail_service.stop()
        self.screen_time.stop()
        if self._activity_service:
            self._activity_service.stop()
            self._activity_service = None
        if self._backend:
            self._backend.shutdown()
            self._backend = None
        Adw.Application.do_shutdown(self)


class _NullMedia:
    """Stand-in when the music module is disabled."""
    active = None

    def connect(self, *a): ...
    def play_pause(self): ...
    def next(self): ...
    def previous(self): ...
    def seek_to(self, *a): ...
    def get_position(self, *a): ...


def main() -> int:
    app = LostIsland()
    try:
        return app.run(sys.argv)
    except KeyboardInterrupt:
        logger.info("Received Ctrl+C; Linux Notch shut down cleanly.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
