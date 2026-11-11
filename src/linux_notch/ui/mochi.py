from __future__ import annotations

import math
from datetime import date
from typing import Any

import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from linux_notch.services.sounds import play_sound  # noqa: E402

MOODS = {
    "idle", "working", "thinking", "searching", "approval", "question",
    "error", "finished", "ratelimit", "sleeping", "dizzy", "annoyed",
    "love", "proud", "wink",
}

OUTFITS = (
    ("auto", "Seasonal"),
    ("none", "None"),
    ("partyHat", "Party hat"),
    ("beanie", "Beanie"),
    ("crown", "Crown"),
    ("sunglasses", "Sunglasses"),
    ("roundGlasses", "Round glasses"),
    ("bow", "Bow"),
    ("scarf", "Scarf"),
    ("witchHat", "Witch hat"),
    ("pumpkin", "Pumpkin"),
    ("santaHat", "Santa hat"),
    ("bunnyEars", "Bunny ears"),
)

_MOOD_COLORS = {
    "idle": (0.93, 0.94, 0.96),
    "working": (0.60, 0.79, 1.0),
    "thinking": (0.78, 0.68, 1.0),
    "searching": (0.69, 0.72, 1.0),
    "approval": (1.0, 0.78, 0.40),
    "question": (0.63, 0.91, 0.96),
    "error": (1.0, 0.62, 0.66),
    "finished": (0.62, 0.93, 0.79),
    "ratelimit": (1.0, 0.75, 0.51),
    "sleeping": (0.75, 0.80, 0.88),
    "dizzy": (1.0, 0.68, 0.83),
    "annoyed": (1.0, 0.73, 0.70),
    "love": (1.0, 0.69, 0.80),
    "proud": (0.69, 0.91, 0.81),
    "wink": (0.83, 0.79, 1.0),
}

_MOOD_SOUNDS = {
    "working": "work",
    "thinking": "think",
    "searching": "search",
    "approval": "approval",
    "question": "question",
    "error": "error",
    "finished": "finish",
    "ratelimit": "rate",
    "sleeping": "sleep",
    "dizzy": "dizzy",
    "annoyed": "annoyed",
    "love": "love",
    "proud": "proud",
    "wink": "wink",
}


def seasonal_outfit(today: date | None = None) -> str:
    current = today or date.today()
    month, day, year = current.month, current.day, current.year
    if (month == 12 and day == 31) or (month == 1 and day <= 2):
        return "partyHat"
    if month == 12 and day <= 26:
        return "santaHat"
    if month == 10 or (month == 11 and day == 1):
        return "witchHat"
    easter_month, easter_day = _easter_date(year)
    easter = date(year, easter_month, easter_day)
    if -2 <= (current - easter).days <= 1:
        return "bunnyEars"
    if (month == 6 and day >= 21) or month in (7, 8):
        return "sunglasses"
    return "none"


def _easter_date(year: int) -> tuple[int, int]:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    easter_offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * easter_offset) // 451
    month = (h + easter_offset - 7 * m + 114) // 31
    return month, (h + easter_offset - 7 * m + 114) % 31 + 1


def mood_for_activity(activity: dict[str, Any] | None) -> str:
    if activity is None:
        return "idle"
    state = str(activity.get("state", "")).lower().replace("_", "-")
    title = str(activity.get("title", "")).lower()
    combined = f"{state} {title}"
    if state in MOODS:
        return state
    if state in ("approve", "approved", "success", "complete", "completed", "finished", "done"):
        return "finished"
    if state in ("error", "failed", "failure", "cancelled", "canceled"):
        return "error"
    if any(word in combined for word in ("approval", "permission", "waiting")):
        return "approval"
    if any(word in combined for word in ("question", "input", "answer")):
        return "question"
    if any(word in combined for word in ("error", "failed", "failure")):
        return "error"
    if any(word in combined for word in ("rate-limit", "ratelimit", "throttle")):
        return "ratelimit"
    if any(word in combined for word in ("success", "complete", "finished", "done")):
        return "finished"
    if "search" in combined:
        return "searching"
    if any(word in combined for word in ("think", "reason")):
        return "thinking"
    if any(word in combined for word in ("sleep", "offline")):
        return "sleeping"
    if state in ("idle", "ready", "stopped"):
        return "idle"
    return "working"


def sound_for_activity(activity: dict[str, Any], mood: str) -> str | None:
    state = str(activity.get("state", "")).lower().replace("_", "-")
    if state in ("approve", "approved"):
        return "approve"
    return _MOOD_SOUNDS.get(mood)


def _blend(color: tuple[float, float, float], amount: float) -> tuple[float, float, float]:
    return tuple(1.0 + (component - 1.0) * amount for component in color)


def _superellipse_path(cr, rx: float, ry: float) -> None:
    exponent = 2.0 / 2.7
    for index in range(81):
        angle = math.tau * index / 80
        cosine, sine = math.cos(angle), math.sin(angle)
        x = rx * math.copysign(abs(cosine) ** exponent, cosine)
        y = ry * math.copysign(abs(sine) ** exponent, sine)
        if index == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
    cr.close_path()


def _ellipse(cr, x: float, y: float, rx: float, ry: float) -> None:
    cr.save()
    cr.translate(x, y)
    cr.scale(rx, ry)
    cr.arc(0, 0, 1, 0, math.tau)
    cr.restore()


def _rounded_rectangle(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _eye(cr, x: float, y: float, mood: str, phase: float, side: int) -> None:
    cr.save()
    cr.translate(x, y)
    look = 0.8 if mood in ("thinking", "searching") else 0
    blink = mood == "idle" and phase % 4.2 < 0.14
    cr.set_source_rgb(0.10, 0.08, 0.10)
    if mood == "sleeping" or blink:
        cr.set_line_width(1.45)
        cr.set_line_cap(1)
        cr.arc(0, 0, 2.5, 0.16 * math.pi, 0.84 * math.pi)
        cr.stroke()
    elif mood == "finished":
        cr.set_line_width(1.7)
        cr.set_line_cap(1)
        cr.arc(0, 1.1, 2.8, math.pi, math.tau)
        cr.stroke()
    elif mood == "error":
        cr.set_line_width(1.8)
        cr.move_to(-2.4, 0.2)
        cr.line_to(2.4, 0.2)
        cr.stroke()
    elif mood == "dizzy":
        cr.set_line_width(1.15)
        cr.arc(0, 0, 2.2, phase * 2 + side * math.pi, phase * 2 + side * math.pi + math.tau * 0.85)
        cr.stroke()
    elif mood == "ratelimit":
        cr.set_line_width(1.5)
        cr.move_to(-2.5, -0.5)
        cr.line_to(2.5, 0.7)
        cr.stroke()
    elif mood == "annoyed":
        cr.set_line_width(1.1)
        cr.move_to(-2.5, -1.7)
        cr.line_to(2.3, -0.8)
        cr.stroke()
        _ellipse(cr, 0, 0.7, 1.65, 2.3)
        cr.fill()
    else:
        eye_height = 3.0 if mood == "approval" else 4.0
        _ellipse(cr, look, 0, 2.1, eye_height)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.78)
        cr.arc(look - 0.55, -1.25, 0.65, 0, math.tau)
        cr.fill()
    cr.restore()


def _draw_outfit(cr, outfit: str, rx: float, ry: float, phase: float) -> None:
    cr.save()
    if outfit == "partyHat":
        cr.move_to(-8, -15)
        cr.line_to(-1, -32)
        cr.line_to(7, -15)
        cr.close_path()
        cr.set_source_rgb(0.97, 0.36, 0.48)
        cr.fill_preserve()
        cr.set_source_rgb(0.72, 0.18, 0.32)
        cr.set_line_width(0.8)
        cr.stroke()
        for x, y, color in ((-2, -24, (1.0, 0.82, 0.24)), (2, -19, (0.35, 0.72, 1.0))):
            cr.set_source_rgb(*color)
            cr.arc(x, y, 1.1, 0, math.tau)
            cr.fill()
        cr.set_source_rgb(1.0, 0.83, 0.28)
        cr.arc(-1, -32, 2.1, 0, math.tau)
        cr.fill()
    elif outfit == "beanie":
        cr.arc(0, -16, 16, math.pi, math.tau)
        cr.line_to(15, -13)
        cr.line_to(-15, -13)
        cr.close_path()
        cr.set_source_rgb(0.39, 0.46, 0.82)
        cr.fill()
        cr.set_source_rgb(0.77, 0.80, 1.0)
        cr.set_line_width(3.2)
        cr.move_to(-14, -14)
        cr.line_to(14, -14)
        cr.stroke()
        cr.arc(0, -32, 2.8, 0, math.tau)
        cr.fill()
    elif outfit == "crown":
        cr.move_to(-12, -14)
        cr.line_to(-10, -24)
        cr.line_to(-4, -19)
        cr.line_to(0, -27)
        cr.line_to(4, -19)
        cr.line_to(10, -24)
        cr.line_to(12, -14)
        cr.close_path()
        cr.set_source_rgb(1.0, 0.75, 0.17)
        cr.fill_preserve()
        cr.set_source_rgb(0.68, 0.40, 0.08)
        cr.set_line_width(0.8)
        cr.stroke()
        for x in (-7, 0, 7):
            cr.set_source_rgb(0.89, 0.27, 0.36)
            cr.arc(x, -19, 1.2, 0, math.tau)
            cr.fill()
    elif outfit in ("sunglasses", "roundGlasses"):
        cr.set_line_width(1.2 if outfit == "roundGlasses" else 0.9)
        if outfit == "roundGlasses":
            cr.set_source_rgb(0.26, 0.18, 0.13)
        else:
            cr.set_source_rgb(0.10, 0.13, 0.20)
        for x in (-8, 8):
            if outfit == "sunglasses":
                _rounded_rectangle(cr, x - 4.0, -4.0, 8.0, 7.0, 1.7)
                cr.fill()
                cr.set_source_rgba(0.75, 0.86, 1.0, 0.42)
                cr.move_to(x - 1.5, -2.7)
                cr.line_to(x + 1.4, 0.2)
                cr.stroke()
                cr.set_source_rgb(0.10, 0.13, 0.20)
            else:
                cr.arc(x, -0.5, 4.5, 0, math.tau)
                cr.stroke()
        cr.move_to(-3.5, -1)
        cr.line_to(3.5, -1)
        cr.stroke()
    elif outfit == "bow":
        cr.set_source_rgb(0.96, 0.30, 0.48)
        cr.move_to(0, -19)
        cr.curve_to(-9, -27, -12, -18, -1, -15)
        cr.curve_to(-12, -11, -7, -8, 0, -14)
        cr.curve_to(7, -8, 12, -11, 1, -15)
        cr.curve_to(12, -18, 9, -27, 0, -19)
        cr.fill()
        cr.set_source_rgb(0.68, 0.12, 0.29)
        cr.arc(0, -16, 2.0, 0, math.tau)
        cr.fill()
    elif outfit == "scarf":
        cr.set_source_rgb(0.80, 0.14, 0.21)
        cr.arc(0, 3.0, 17.0, 0.10 * math.pi, 0.90 * math.pi)
        cr.set_line_width(5.5)
        cr.stroke()
        cr.move_to(-11, 10)
        cr.curve_to(-13, 14, -13 + math.sin(phase * 2) * 1.2, 20, -8, 24)
        cr.line_to(-3, 21)
        cr.line_to(-6, 11)
        cr.close_path()
        cr.fill()
        cr.set_source_rgb(1.0, 0.91, 0.85)
        cr.set_line_width(1.0)
        cr.move_to(-12, 14)
        cr.line_to(-5, 14)
        cr.stroke()
    elif outfit == "witchHat":
        cr.move_to(-15, -14)
        cr.line_to(0, -34)
        cr.line_to(13, -14)
        cr.close_path()
        cr.set_source_rgb(0.36, 0.23, 0.57)
        cr.fill()
        _ellipse(cr, 0, -13, 17, 3.0)
        cr.set_source_rgb(0.31, 0.19, 0.52)
        cr.fill()
        cr.set_source_rgb(0.97, 0.59, 0.23)
        cr.set_line_width(2)
        cr.move_to(-9, -15)
        cr.line_to(9, -15)
        cr.stroke()
    elif outfit == "pumpkin":
        cr.set_source_rgba(0.60, 0.23, 0.06, 0.32)
        cr.set_line_width(1.2)
        for x in (-13, -7, 0, 7, 13):
            cr.move_to(x, -ry + 3)
            cr.curve_to(x - 4, -4, x - 4, 7, x, ry - 2)
            cr.stroke()
        cr.set_source_rgb(0.24, 0.56, 0.18)
        cr.move_to(-1, -ry + 1)
        cr.curve_to(-4, -ry - 8, 3, -ry - 10, 2, -ry + 1)
        cr.fill()
    elif outfit == "santaHat":
        cr.move_to(-14, -14)
        cr.curve_to(-10, -28, 4, -36, 10, -31)
        cr.line_to(13, -15)
        cr.close_path()
        cr.set_source_rgb(0.83, 0.16, 0.22)
        cr.fill()
        cr.set_source_rgb(0.97, 0.96, 0.93)
        cr.set_line_width(4)
        cr.move_to(-13, -14)
        cr.curve_to(-4, -16, 6, -16, 13, -14)
        cr.stroke()
        cr.arc(10, -31, 3.0, 0, math.tau)
        cr.fill()
    elif outfit == "bunnyEars":
        for x, tilt in ((-6, -0.11), (6, 0.11)):
            cr.save()
            cr.translate(x, -16)
            cr.rotate(tilt)
            _ellipse(cr, 0, -9, 4.2, 12.0)
            cr.set_source_rgb(0.97, 0.94, 0.95)
            cr.fill_preserve()
            cr.set_source_rgb(0.76, 0.70, 0.76)
            cr.set_line_width(0.8)
            cr.stroke()
            _ellipse(cr, 0, -9, 1.8, 8.2)
            cr.set_source_rgb(0.96, 0.56, 0.67)
            cr.fill()
            cr.restore()
    cr.restore()


def draw_mochi(cr, width: int, height: int, mood: str = "idle",
               outfit: str = "none", phase: float = 0.0) -> None:
    mood = mood if mood in MOODS else "idle"
    outfit = seasonal_outfit() if outfit == "auto" else outfit
    if outfit not in {key for key, _label in OUTFITS}:
        outfit = "none"

    scale = min(width / 58.0, height / 55.0)
    cr.save()
    cr.translate(width / 2, height / 2 + (math.sin(phase * 2.0) * 1.1 if mood != "sleeping" else 0))
    cr.scale(scale, scale)

    cr.save()
    cr.scale(0.72, 1)
    cr.set_source_rgba(0.02, 0.025, 0.04, 0.25)
    _ellipse(cr, 0, 19.5, 18, 3.3)
    cr.fill()
    cr.restore()

    rx, ry = 25.0, 19.0
    color = (0.98, 0.55, 0.18) if outfit == "pumpkin" else _blend(_MOOD_COLORS[mood], 0.72)
    cr.save()
    cr.scale(1, 0.94)
    _superellipse_path(cr, rx, ry)
    gradient = cairo.LinearGradient(0, -ry, 0, ry)
    gradient.add_color_stop_rgba(0, min(1, color[0] + 0.08), min(1, color[1] + 0.06), min(1, color[2] + 0.05), 1)
    gradient.add_color_stop_rgba(1, color[0] * 0.88, color[1] * 0.88, color[2] * 0.90, 1)
    cr.set_source(gradient)
    cr.fill_preserve()
    cr.set_source_rgba(0.18, 0.16, 0.19, 0.18)
    cr.set_line_width(0.9)
    cr.stroke()
    cr.restore()

    cr.save()
    cr.set_source_rgba(1, 1, 1, 0.3)
    _ellipse(cr, -11, -13.2, 8.0, 2.2)
    cr.fill()
    cr.restore()

    if mood in ("approval", "question", "error", "finished", "ratelimit", "proud"):
        cr.set_source_rgba(0.96, 0.50, 0.39, 0.42)
        for x in (-14, 14):
            _ellipse(cr, x, 6.0, 3.2, 1.8)
            cr.fill()

    _eye(cr, -8.0, -1.0, mood, phase, -1)
    _eye(cr, 8.0, -1.0, mood, phase, 1)

    if mood == "approval":
        cr.set_source_rgb(0.94, 0.52, 0.08)
        cr.set_line_width(2.0)
        cr.set_line_cap(1)
        cr.move_to(0, 7)
        cr.line_to(0, 10)
        cr.stroke()
        cr.arc(0, 13, 0.7, 0, math.tau)
        cr.fill()
    elif mood == "question":
        cr.set_source_rgb(0.12, 0.61, 0.76)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(8)
        cr.move_to(15, -13)
        cr.show_text("?")
    elif mood == "error":
        cr.set_source_rgb(0.75, 0.13, 0.20)
        cr.set_line_width(1.5)
        cr.move_to(-2.5, 9)
        cr.line_to(2.5, 9)
        cr.stroke()
    elif mood in ("finished", "proud", "love"):
        cr.set_source_rgb(0.20, 0.42, 0.31)
        cr.set_line_width(1.3)
        cr.set_line_cap(1)
        cr.arc(0, 7, 3.2, 0.18 * math.pi, 0.82 * math.pi)
        cr.stroke()
    elif mood == "sleeping":
        cr.set_source_rgba(0.47, 0.55, 0.72, 0.9)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(7)
        cr.move_to(16, -12)
        cr.show_text("z")
        cr.set_font_size(5)
        cr.move_to(21, -17)
        cr.show_text("z")

    if mood == "ratelimit":
        cr.set_source_rgb(0.28, 0.62, 0.94)
        cr.move_to(19, -6)
        cr.curve_to(15, -2, 17, 1, 19, 2)
        cr.curve_to(22, 0, 23, -3, 19, -6)
        cr.fill()

    _draw_outfit(cr, outfit, rx, ry, phase)
    cr.restore()


class MochiWidget(Gtk.DrawingArea):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.set_content_width(58)
        self.set_content_height(54)
        self.set_draw_func(self._draw)
        self.set_tooltip_text("Click to open Linux Notch")
        self._mood = "idle"
        self._activity_mood = "idle"
        self._phase = 0.0
        self._timer = 0
        self._last_activity_key: tuple[Any, ...] | None = None
        self._last_progress: Any = None

        self.connect("map", lambda *_: self._start_animation())
        self.connect("unmap", lambda *_: self._stop_animation())
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_enter)
        self.add_controller(motion)

    @property
    def outfit(self) -> str:
        value = self.cfg.get("mochi_outfit", "auto")
        return value if value in {key for key, _label in OUTFITS} else "auto"

    def _draw(self, _area, cr, width: int, height: int) -> None:
        draw_mochi(cr, width, height, self._mood, self.outfit, self._phase)

    def _start_animation(self) -> None:
        if not self._timer:
            self._timer = GLib.timeout_add(60, self._tick)

    def _stop_animation(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self) -> bool:
        self._phase += 0.06
        self.queue_draw()
        return True

    def _on_enter(self, *_args) -> None:
        play_sound("hover", self.cfg)

    def show_activity(self, activity: dict[str, Any] | None) -> None:
        mood = mood_for_activity(activity)
        key = None if activity is None else (
            activity.get("activity_id"),
            activity.get("state"),
            activity.get("progress"),
        )
        previous_mood = self._activity_mood
        previous_key = self._last_activity_key
        previous_progress = self._last_progress
        self._activity_mood = mood
        self._last_activity_key = key
        self._last_progress = activity.get("progress") if activity else None
        self._mood = mood
        if mood != previous_mood:
            sound = sound_for_activity(activity, mood) if activity else None
            if sound:
                play_sound(sound, self.cfg)
        elif (
            key != previous_key
            and self._last_progress != previous_progress
            and mood in ("working", "searching")
        ):
            play_sound("tick", self.cfg)
        self.queue_draw()

    def set_mood(self, mood: str, *, sound: bool = False) -> None:
        if mood not in MOODS:
            raise ValueError(f"Unknown Mochi mood: {mood}")
        old_mood = self._activity_mood
        self._activity_mood = mood
        self._mood = mood
        if sound and mood != old_mood and mood in _MOOD_SOUNDS:
            play_sound(_MOOD_SOUNDS[mood], self.cfg)
        self.queue_draw()

    def outfit_changed(self) -> None:
        self.queue_draw()
