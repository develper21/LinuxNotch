"""The collapsed island: Mochi, clock, and battery status."""

from __future__ import annotations

import time
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from linux_notch.services.power import CHARGING, DISCHARGING, FULL  # noqa: E402
from linux_notch.services.spectrum import SpectrumSource  # noqa: E402
from linux_notch.ui.equalizer import BAR_COUNT, Equalizer  # noqa: E402
from linux_notch.ui.mochi import MochiWidget  # noqa: E402


STATUS_ROTATION_SECONDS = 5


def visualizer_capture_enabled(
    status: str,
    closed_visible: bool,
    mode: str,
) -> bool:
    return (
        status == "Playing"
        and closed_visible
        and mode in {"auto", "real"}
    )


def format_pill_status(now: datetime, clock_24h: bool, power=None,
                       show_battery: bool = False) -> str:
    if (
        show_battery
        and power is not None
        and power.available
        and power.percentage >= 0
    ):
        state = {
            CHARGING: "Charging",
            DISCHARGING: "On battery",
            FULL: "Full",
        }.get(power.state, "Battery")
        return f"{power.percentage:.0f}% · {state}"

    time_format = "%H:%M" if clock_24h else "%I:%M %p"
    return f"{now.strftime(time_format)} · {now.strftime('%b %d')}"


class Pill(Gtk.Box):
    def __init__(self, cfg: dict, power=None, media=None,
                 weather=None, system=None, on_visualizer_status=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("pill")
        self.set_size_request(240, 32)
        self.cfg = cfg
        self.power = power
        self.media = media
        self.weather = weather
        self.system = system
        self.on_visualizer_status = on_visualizer_status
        self._surface_visible = False
        self._spectrum_error = ""
        self.visualizer_status = "Real audio: waiting for local music playback"
        self._showing_battery = False
        self._last_status_change = 0.0
        self._status_index = 0
        self._status_timer = 0
        self._weather_temp = ""
        self._weather_desc = ""
        self._cpu_percent = 0
        self._ram_percent = 0
        self.mochi = MochiWidget(cfg)
        self.mochi.set_content_width(28)
        self.mochi.set_content_height(28)
        self.mochi.set_size_request(28, 28)
        self.status = Gtk.Label()
        self.status.add_css_class("pill-status")
        self.status.set_hexpand(True)
        self.status.set_halign(Gtk.Align.CENTER)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.center = Gtk.Stack()
        self.center.set_hexpand(True)
        self.center.set_halign(Gtk.Align.FILL)
        self.center.set_valign(Gtk.Align.CENTER)
        self.center.add_named(self.status, "status")
        self.equalizer = Equalizer(on_idle=self._on_equalizer_idle)
        self.spectrum = SpectrumSource(
            BAR_COUNT,
            self._on_spectrum_levels,
            self._on_spectrum_failed,
        )
        self.center.add_named(self.equalizer, "equalizer")
        self.center.set_visible_child_name("status")
        self.launcher = Gtk.Button()
        self.launcher.add_css_class("launcher-button")
        self.launcher.set_icon_name("view-grid-symbolic")
        self.launcher.set_tooltip_text("Open feature selector")

        self.append(self.mochi)
        self.append(self.center)
        self.append(self.launcher)
        self.connect("map", lambda *_: self._on_map())
        self.connect("unmap", lambda *_: self._on_unmap())
        if self.power is not None:
            self.power.connect("changed", lambda *_: self._refresh_status())
        if self.weather is not None:
            self.weather.connect("changed", self._on_weather_changed)
        if self.system is not None:
            self.system.connect("changed", self._on_system_changed)
        if self.media is not None:
            self.media.connect("changed", lambda *_: self.refresh_media())
            self.media.connect("art-ready", lambda *_: self.refresh_media())
        self._refresh_status()
        self.refresh_media()

    def _refresh_status(self) -> None:
        options = self._status_options()
        self._status_index %= len(options)
        selected = options[self._status_index]
        now = datetime.now()
        if selected == "battery":
            label = format_pill_status(
                now, self.cfg.get("clock_24h", True), self.power,
                show_battery=True)
        elif selected == "weather":
            if self._weather_temp and self._weather_temp != "—":
                label = f"{self._weather_temp} · {self._weather_desc}"
            else:
                label = self._weather_desc or "Weather loading"
        elif selected == "cpu":
            label = f"CPU {self._cpu_percent}%"
        elif selected == "ram":
            label = f"RAM {self._ram_percent}%"
        else:
            label = format_pill_status(
                now, self.cfg.get("clock_24h", True))
        self.status.set_label(label)

    def _status_options(self) -> list[str]:
        options = ["clock"]
        if (
            self.power is not None
            and self.power.available
            and self.power.percentage >= 0
        ):
            options.append("battery")
        if self.weather is not None:
            options.append("weather")
        if self.system is not None:
            options.extend(("cpu", "ram"))
        return options

    def _on_weather_changed(self, _service, temp: str, desc: str, _icon: str):
        self._weather_temp = temp
        self._weather_desc = desc
        self._refresh_status()

    def _on_system_changed(self, _service, cpu: int, ram: int, _ram_gib: float):
        self._cpu_percent = cpu
        self._ram_percent = ram
        self._refresh_status()

    def _start_status_timer(self) -> None:
        if self._status_timer:
            return
        if self.weather is not None:
            self.weather.request()
        if self.system is not None:
            self.system.start()
        self._last_status_change = time.monotonic()
        self._refresh_status()
        self._status_timer = GLib.timeout_add_seconds(1, self._tick_status)
        self.update_visualizer()

    def _tick_status(self) -> bool:
        now = time.monotonic()
        if now - self._last_status_change >= STATUS_ROTATION_SECONDS:
            options = self._status_options()
            self._status_index = (self._status_index + 1) % len(options)
            self._showing_battery = options[self._status_index] == "battery"
            self._last_status_change = now
        self._refresh_status()
        return GLib.SOURCE_CONTINUE

    def _stop_status_timer(self) -> None:
        if self._status_timer:
            GLib.source_remove(self._status_timer)
            self._status_timer = 0
        if self.system is not None:
            self.system.stop()

    def _on_equalizer_idle(self) -> None:
        if self.equalizer.playback_status != "Playing":
            self.center.set_visible_child_name("status")

    def refresh_media(self) -> None:
        player = getattr(self.media, "active", None)
        status = player.status if player is not None else "Stopped"
        self.equalizer.set_artwork(
            player.art_path if player is not None else None)
        show_equalizer = self.equalizer.set_playback_status(status)
        self.update_visualizer(status)
        self.center.set_visible_child_name(
            "equalizer" if show_equalizer else "status")

    def update_visualizer(self, status: str | None = None) -> None:
        player = getattr(self.media, "active", None)
        status = status or (player.status if player is not None else "Stopped")
        mode = self.cfg.get("viz_mode", "auto")
        if mode not in {"auto", "real", "synthetic"}:
            mode = "auto"
        should_run = visualizer_capture_enabled(
            status,
            self._surface_visible and self.get_mapped(),
            mode,
        )
        if should_run:
            if not self.spectrum.running:
                self._spectrum_error = ""
                self.equalizer.external = None
                self.spectrum.start()
            if self.spectrum.running and not self._spectrum_error:
                self._set_visualizer_status(
                    "Real audio: connecting; synthetic animation is active"
                )
            return

        self.spectrum.stop()
        self.equalizer.external = None
        if mode == "synthetic":
            message = "Real audio: synthetic mode selected"
        elif status == "Paused":
            message = "Real audio: stopped while music is paused"
        elif status == "Playing":
            message = "Real audio: stopped while the notch is open or hidden"
        else:
            message = "Real audio: waiting for local music playback"
        self._set_visualizer_status(message)

    def _on_spectrum_levels(self, levels: list[float]) -> None:
        if (
            not self._surface_visible
            or not self.get_mapped()
            or self.equalizer.playback_status != "Playing"
        ):
            return
        self.equalizer.external = levels
        self._spectrum_error = ""
        self._set_visualizer_status("Real audio: active")

    def _on_spectrum_failed(self, reason: str) -> None:
        self._spectrum_error = reason
        self.equalizer.external = None
        mode = self.cfg.get("viz_mode", "auto")
        self._set_visualizer_status(
            f"Real audio unavailable; synthetic fallback ({reason})"
            if mode != "synthetic"
            else "Real audio: synthetic mode selected"
        )

    def _set_visualizer_status(self, message: str) -> None:
        if message == self.visualizer_status:
            return
        self.visualizer_status = message
        if self.on_visualizer_status is not None:
            self.on_visualizer_status(message)

    def _on_map(self) -> None:
        self._start_status_timer()
        self.update_visualizer()

    def _on_unmap(self) -> None:
        self._stop_status_timer()
        self.spectrum.stop()
        self.equalizer.external = None
        self.update_visualizer()

    def stop_visualizer(self) -> None:
        self._surface_visible = False
        self.spectrum.stop()
        self.equalizer.external = None
        self.equalizer.set_surface_visible(False)
        self._stop_status_timer()

    def set_surface_visible(self, visible: bool) -> None:
        self._surface_visible = visible
        self.equalizer.set_surface_visible(visible)
        if visible:
            if self.weather is not None:
                self.weather.request()
            if self.system is not None:
                self.system.start()
            self.refresh_media()
        else:
            self._stop_status_timer()
            if self.system is not None:
                self.system.stop()
            self.update_visualizer()

    def show_activity(self, activity: dict | None):
        self.mochi.show_activity(activity)
