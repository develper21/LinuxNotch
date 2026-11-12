"""The top-attached island surface and its closed, peek, and open states."""

from __future__ import annotations

import math

import cairo
from gi.repository import Adw, Gdk, GLib, Gtk

from linux_notch.services.sounds import play_sound
from linux_notch.ui.expanded import Expanded
from linux_notch.ui.peek import Peek
from linux_notch.ui.pill import Pill
from linux_notch.ui.shape import IslandShape, ShapeGeometry

CLOSED: ShapeGeometry = {
    "width": 260,
    "height": 34,
    "radius": 12,
    "ear": 10,
}
PEEK: ShapeGeometry = {
    "width": 300,
    "height": 40,
    "radius": 14,
    "ear": 12,
}
COLLAPSE_DELAY_MS = 700
CONTENT_FADE_DELAY_MS = 120
MIN_EXPANDED_WIDTH = 420
MIN_EXPANDED_HEIGHT = 180
EXPANDED_WIDTH_FRACTION = 0.92
EXPANDED_HEIGHT_FRACTION = 0.82


def expanded_geometry(
    natural_width: int,
    natural_height: int,
    monitor_width: int,
    monitor_height: int,
) -> ShapeGeometry:
    max_width = max(1, round(monitor_width * EXPANDED_WIDTH_FRACTION))
    max_height = max(1, round(monitor_height * EXPANDED_HEIGHT_FRACTION))
    ear = min(24, max_width / 8)
    width = min(
        max_width,
        max(MIN_EXPANDED_WIDTH, natural_width + round(ear * 2)),
    )
    height = min(
        max_height,
        max(MIN_EXPANDED_HEIGHT, natural_height + 20),
    )
    return {
        "width": width,
        "height": height,
        "radius": min(28, height / 2),
        "ear": min(ear, width / 8),
    }


def _find_monitor(monitors, wanted: str):
    for index in range(monitors.get_n_items()):
        monitor = monitors.get_item(index)
        if wanted and monitor.get_connector() == wanted:
            return monitor
    return monitors.get_item(0) if monitors.get_n_items() else None


class Island(Gtk.Overlay):
    def __init__(self, cfg: dict, media, power, weather=None, system=None,
                 on_settings=None, clipboard=None):
        super().__init__()
        self.add_css_class("island")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.START)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.cfg = cfg
        self.media = media

        self._peek_timeout = 0
        self._collapse_timeout = 0
        self._fade_timeout = 0
        self._spring_timeout = 0
        self._spring_start_us = 0
        self._resize_timeout = 0
        self._collapse_pending = False
        self._hovered = False
        self._animation = None
        self._animation_start: ShapeGeometry | None = None
        self._animation_end: ShapeGeometry | None = None

        opacity = min(1.0, max(0.3, float(cfg.get("opacity", 0.97))))
        self.shape = IslandShape(CLOSED, opacity)
        self.set_child(self.shape)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(180)
        self.stack.set_interpolate_size(False)
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.stack.set_halign(Gtk.Align.FILL)
        self.stack.set_valign(Gtk.Align.FILL)
        self.add_overlay(self.stack)
        self.set_measure_overlay(self.stack, False)
        self._set_content_inset(10, CLOSED["height"])

        self.pill = Pill(cfg)
        self.peek = Peek()
        self.expanded = Expanded(
            cfg,
            media,
            power,
            weather=weather,
            system=system,
            on_settings=on_settings,
            clipboard=clipboard,
            on_mochi_changed=self.pill.mochi.outfit_changed,
            on_content_changed=self._schedule_content_resize,
            on_close=self.collapse,
        )

        self.stack.add_named(self.pill, "pill")
        self.stack.add_named(self.peek, "peek")
        self.stack.add_named(self.expanded, "expanded")
        self.stack.set_visible_child_name("pill")
        self.pill.launcher.connect("clicked", lambda *_: self.expand())

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)

        right = Gtk.GestureClick(button=3)
        right.connect("released", lambda *_: self.toggle())
        self.add_controller(right)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_enter)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    @property
    def state(self) -> str:
        return self.stack.get_visible_child_name() or "pill"

    def collapse(self) -> None:
        self._cancel_peek()
        if self.state == "expanded":
            if self._collapse_pending:
                return
            self._cancel_fade()
            self._collapse_pending = True
            self.stack.set_opacity(0.0)
            self._fade_timeout = GLib.timeout_add(
                CONTENT_FADE_DELAY_MS, self._finish_collapse)
            return

        self.stack.set_visible_child_name("pill")
        self._animate_to(CLOSED)

    def _finish_collapse(self) -> bool:
        self._fade_timeout = 0
        if self._collapse_pending:
            self.expanded.reset_to_home()
            self.stack.set_visible_child_name("pill")
            self.stack.set_opacity(1.0)
            self._animate_to(CLOSED)
            self._collapse_pending = False
            play_sound("close", self.cfg)
        return GLib.SOURCE_REMOVE

    def expand(self) -> None:
        was_expanded = self.state == "expanded"
        self._cancel_peek()
        self._cancel_fade()
        self._collapse_pending = False
        self.stack.set_visible_child_name("expanded")
        if not was_expanded:
            self.stack.set_opacity(0.0)
            self._animate_to(self._measure_expanded_geometry())
            self._fade_timeout = GLib.timeout_add(
                CONTENT_FADE_DELAY_MS, self._finish_expand)
            play_sound("open", self.cfg)
        else:
            self.stack.set_opacity(1.0)
            self._animate_to(self._measure_expanded_geometry())

    def _finish_expand(self) -> bool:
        self._fade_timeout = 0
        if self.state == "expanded":
            self.stack.set_opacity(1.0)
        return GLib.SOURCE_REMOVE

    def toggle(self) -> None:
        self.collapse() if self.state == "expanded" else self.expand()

    def show_peek(self, setter, *args) -> None:
        """Run ``setter(*args)`` on the peek widget and surface it briefly."""
        if self.state == "expanded":
            return
        setter(*args)
        self.stack.set_visible_child_name("peek")
        self._animate_to(PEEK)
        play_sound("peek", self.cfg)
        self._cancel_peek()
        ms = int(float(self.cfg.get("peek_seconds", 2.2)) * 1000)
        self._peek_timeout = GLib.timeout_add(ms, self._peek_done)

    def _peek_done(self) -> bool:
        self._peek_timeout = 0
        if self.state == "peek":
            self.stack.set_visible_child_name("pill")
            if not self._hovered:
                self._animate_to(CLOSED)
        return GLib.SOURCE_REMOVE

    def _cancel_peek(self) -> None:
        if self._peek_timeout:
            GLib.source_remove(self._peek_timeout)
            self._peek_timeout = 0

    def _cancel_fade(self) -> None:
        if self._fade_timeout:
            GLib.source_remove(self._fade_timeout)
            self._fade_timeout = 0

    def _set_content_inset(self, ear: float, height: float) -> None:
        inset = max(0, round(ear))
        self.stack.set_margin_start(inset)
        self.stack.set_margin_end(inset)
        vertical_inset = min(8, max(0, round((height - 50) / 26)))
        self.stack.set_margin_top(vertical_inset)
        self.stack.set_margin_bottom(round(vertical_inset * 1.25))

    def _schedule_content_resize(self):
        if self.state != "expanded" or self._resize_timeout:
            return
        self._resize_timeout = GLib.idle_add(self._resize_to_content)

    def _resize_to_content(self) -> bool:
        self._resize_timeout = 0
        if self.state == "expanded":
            self._animate_to(self._measure_expanded_geometry())
        return GLib.SOURCE_REMOVE

    def _monitor_size(self) -> tuple[int, int]:
        display = Gdk.Display.get_default()
        if display is None:
            return 1280, 900
        monitors = display.get_monitors()
        monitor = _find_monitor(monitors, self.cfg.get("monitor", ""))
        if monitor is None:
            return 1280, 900
        geometry = monitor.get_geometry()
        return geometry.width, geometry.height

    def _measure_expanded_geometry(self) -> ShapeGeometry:
        monitor_width, monitor_height = self._monitor_size()
        _minimum, natural_width, _min_baseline, _nat_baseline = (
            self.expanded.measure(Gtk.Orientation.HORIZONTAL, -1))
        width_geometry = expanded_geometry(
            natural_width, 0, monitor_width, monitor_height)
        content_width = max(
            1, width_geometry["width"] - round(width_geometry["ear"] * 2))
        _minimum, natural_height, _min_baseline, _nat_baseline = (
            self.expanded.measure(Gtk.Orientation.VERTICAL, content_width))
        return expanded_geometry(
            natural_width, natural_height, monitor_width, monitor_height)

    def _animate_to(self, target: ShapeGeometry) -> None:
        if self._animation is not None:
            self._animation.pause()
            self._animation = None
        if self._spring_timeout:
            GLib.source_remove(self._spring_timeout)
            self._spring_timeout = 0

        geometry = self.shape.geometry
        self._animation_start = {
            "width": geometry["width"],
            "height": geometry["height"],
            "radius": geometry["radius"],
            "ear": geometry["ear"],
        }
        self._animation_end = dict(target)
        if (
            hasattr(Adw, "SpringAnimation")
            and hasattr(Adw, "SpringParams")
            and hasattr(Adw, "CallbackAnimationTarget")
        ):
            animation_target = Adw.CallbackAnimationTarget.new(
                self._on_animation_frame)
            self._animation = Adw.SpringAnimation.new(
                self.shape,
                0.0,
                1.0,
                Adw.SpringParams.new(0.75, 1.0, 380.0),
                animation_target,
            )
            self._animation.play()
        else:
            self._spring_start_us = GLib.get_monotonic_time()
            self._spring_timeout = GLib.timeout_add(
                16, self._fallback_spring_frame)

    def _fallback_spring_frame(self) -> bool:
        elapsed = (GLib.get_monotonic_time() - self._spring_start_us) / 1_000_000
        damping = 0.75
        frequency = math.sqrt(380.0)
        damped_frequency = frequency * math.sqrt(1 - damping**2)
        decay = math.exp(-damping * frequency * elapsed)
        progress = 1 - decay * (
            math.cos(damped_frequency * elapsed)
            + damping / math.sqrt(1 - damping**2)
            * math.sin(damped_frequency * elapsed)
        )
        self._on_animation_frame(1.0 if elapsed >= 0.55 else progress)
        if elapsed >= 0.55:
            self._spring_timeout = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _on_animation_frame(self, progress: float) -> bool:
        if self._animation_start is None or self._animation_end is None:
            return False
        geometry: ShapeGeometry = {}
        for key in ("width", "height", "radius", "ear"):
            minimum = 1.0 if key in ("width", "height") else 0.0
            geometry[key] = max(
                minimum,
                self._animation_start[key]
                + (self._animation_end[key] - self._animation_start[key])
                * progress,
            )
        self.shape.set_geometry(geometry)
        self._set_content_inset(geometry["ear"], geometry["height"])
        self._update_input_region(geometry)
        return True

    def _update_input_region(self, geometry: ShapeGeometry) -> None:
        native = self.get_native()
        if native is None:
            return
        surface = native.get_surface()
        if surface is None:
            return
        width = max(1, round(geometry["width"]))
        height = max(1, round(geometry["height"]))
        region = cairo.Region(cairo.RectangleInt(0, 0, width, height))
        surface.set_input_region(region)

    def _on_click(self, _gesture, _n, _x, _y) -> None:
        if self.state in ("pill", "peek"):
            self.expand()
        else:
            self.collapse()

    def _on_enter(self, _motion, _x, _y) -> None:
        self._hovered = True
        if self._collapse_timeout:
            GLib.source_remove(self._collapse_timeout)
            self._collapse_timeout = 0
        if self.state == "pill":
            self._animate_to(PEEK)

    def _on_leave(self, _motion) -> None:
        self._hovered = False
        if self.state == "expanded":
            if self._collapse_timeout:
                GLib.source_remove(self._collapse_timeout)
            self._collapse_timeout = GLib.timeout_add(
                COLLAPSE_DELAY_MS, self._leave_collapse)
        elif self.state == "pill" and not self._peek_timeout:
            self._animate_to(CLOSED)

    def _leave_collapse(self) -> bool:
        self._collapse_timeout = 0
        if self.state == "expanded" and not self._hovered:
            self.collapse()
        return GLib.SOURCE_REMOVE

    def show_activity(self, activity: dict | None) -> None:
        self.expanded.show_activity(activity)

    def set_opacity(self, opacity: float) -> None:
        self.shape.set_opacity(min(1.0, max(0.3, opacity)))

    def on_media_changed(self) -> None:
        if self.state == "expanded":
            self.expanded.refresh_media()
