"""Local active-desktop time tracking and daily history."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import subprocess
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, GObject  # noqa: E402

IDLE_THRESHOLD_SECONDS = 5 * 60
SAMPLE_INTERVAL_SECONDS = 30
MUTTER_IDLE_BUS_NAME = "org.gnome.Mutter.IdleMonitor"
MUTTER_IDLE_OBJECT_PATH = "/org/gnome/Mutter/IdleMonitor/Core"
MUTTER_IDLE_INTERFACE = "org.gnome.Mutter.IdleMonitor"
SCREENSAVER_BUS_NAME = "org.freedesktop.ScreenSaver"
SCREENSAVER_OBJECT_PATH = "/ScreenSaver"
SCREENSAVER_INTERFACE = "org.freedesktop.ScreenSaver"


def _default_database_path() -> str:
    state_home = os.environ.get(
        "XDG_STATE_HOME",
        os.path.join(os.path.expanduser("~"), ".local", "state"),
    )
    return os.path.join(state_home, "linux-notch", "screen-time.sqlite3")


def _week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=(day.weekday() + 1) % 7)


class ScreenTimeService(GObject.Object):
    """Track desktop activity; no application or input details are recorded."""

    __gsignals__ = {
        "updated": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(
        self,
        database_path: str | None = None,
        idle_detector=None,
        monotonic=time.monotonic,
        wall_clock=time.time,
        idle_threshold: int = IDLE_THRESHOLD_SECONDS,
        interval_seconds: int = SAMPLE_INTERVAL_SECONDS,
    ):
        super().__init__()
        self.database_path = database_path or _default_database_path()
        self._idle_detector = idle_detector
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._idle_threshold = idle_threshold
        self._interval_seconds = interval_seconds
        self._timer_id = 0
        self._last_monotonic: float | None = None
        self._idle_proxy = None
        self._screensaver_proxy = None
        self._xprintidle = shutil.which("xprintidle")
        self._session_id = os.environ.get("XDG_SESSION_ID", "")
        self.idle_method = (
            "injected" if idle_detector is not None else "unavailable")
        self._init_database()

    def _init_database(self) -> None:
        os.makedirs(
            os.path.dirname(self.database_path) or ".",
            exist_ok=True,
        )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_totals (
                    day TEXT PRIMARY KEY,
                    seconds INTEGER NOT NULL DEFAULT 0
                        CHECK(seconds >= 0)
                )
                """
            )

    @property
    def tracking(self) -> bool:
        return bool(self._timer_id)

    def start(self) -> None:
        if self._timer_id:
            return
        self._last_monotonic = self._monotonic()
        self._timer_id = GLib.timeout_add_seconds(
            self._interval_seconds,
            self._sample,
        )
        self._sample()

    def stop(self) -> None:
        if not self._timer_id:
            return
        self._sample()
        GLib.source_remove(self._timer_id)
        self._timer_id = 0
        self._last_monotonic = None

    def sample_now(self) -> None:
        self._sample()

    def week_data(self, week_offset: int = 0) -> tuple[dt.date, dict[str, int]]:
        today = dt.date.fromtimestamp(self._wall_clock())
        first_day = _week_start(today) + dt.timedelta(days=7 * week_offset)
        last_day = first_day + dt.timedelta(days=6)
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT day, seconds
                FROM daily_totals
                WHERE day >= ? AND day <= ?
                """,
                (first_day.isoformat(), last_day.isoformat()),
            ).fetchall()
        return first_day, {day: int(seconds) for day, seconds in rows}

    def _sample(self) -> bool:
        now_monotonic = self._monotonic()
        previous = self._last_monotonic
        self._last_monotonic = now_monotonic
        if previous is None:
            return GLib.SOURCE_CONTINUE

        elapsed = max(0.0, now_monotonic - previous)
        if not elapsed:
            return GLib.SOURCE_CONTINUE

        try:
            idle_ms = (
                self._idle_detector()
                if self._idle_detector is not None
                else self._get_idle_ms()
            )
        except (OSError, GLib.Error, subprocess.SubprocessError, ValueError):
            idle_ms = None
        if idle_ms is None:
            return GLib.SOURCE_CONTINUE

        idle_seconds = max(0.0, idle_ms / 1000)
        idle_tail = max(0.0, idle_seconds - self._idle_threshold)
        active_seconds = max(0.0, elapsed - idle_tail)
        if active_seconds:
            self._record_interval(
                self._wall_clock() - active_seconds,
                self._wall_clock(),
                active_seconds,
            )
            self.emit("updated")
        return GLib.SOURCE_CONTINUE

    def _get_idle_ms(self) -> int | None:
        if self._idle_proxy is None:
            try:
                self._idle_proxy = Gio.DBusProxy.new_for_bus_sync(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                    None,
                    MUTTER_IDLE_BUS_NAME,
                    MUTTER_IDLE_OBJECT_PATH,
                    MUTTER_IDLE_INTERFACE,
                    None,
                )
            except GLib.Error:
                self._idle_proxy = False
        if self._idle_proxy:
            try:
                result = self._idle_proxy.call_sync(
                    "GetIdletime",
                    None,
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
                self.idle_method = "GNOME Mutter"
                return int(result.unpack()[0])
            except GLib.Error:
                self._idle_proxy = False

        if self._screensaver_proxy is None:
            try:
                self._screensaver_proxy = Gio.DBusProxy.new_for_bus_sync(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                    None,
                    SCREENSAVER_BUS_NAME,
                    SCREENSAVER_OBJECT_PATH,
                    SCREENSAVER_INTERFACE,
                    None,
                )
            except GLib.Error:
                self._screensaver_proxy = False
        if self._screensaver_proxy:
            try:
                result = self._screensaver_proxy.call_sync(
                    "GetSessionIdleTime",
                    None,
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
                self.idle_method = "Desktop ScreenSaver"
                return int(result.unpack()[0]) * 1000
            except GLib.Error:
                self._screensaver_proxy = False

        if self._xprintidle:
            try:
                result = subprocess.run(
                    [self._xprintidle],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                result = None
            if result is not None and result.returncode == 0:
                self.idle_method = "X11"
                return int(result.stdout.strip())

        if self._session_id:
            try:
                result = subprocess.run(
                    [
                        "loginctl",
                        "show-session",
                        self._session_id,
                        "--property=IdleHint",
                        "--value",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                result = None
            if result is not None and result.returncode == 0:
                value = result.stdout.strip().lower()
                if value == "true":
                    self.idle_method = "systemd-logind"
                    return (
                        self._idle_threshold + self._interval_seconds
                    ) * 1000
                if value == "false":
                    self.idle_method = "systemd-logind"
                    return 0
        return None

    def _record_interval(
        self,
        start_timestamp: float,
        end_timestamp: float,
        seconds: float,
    ) -> None:
        start = dt.datetime.fromtimestamp(start_timestamp)
        end = dt.datetime.fromtimestamp(end_timestamp)
        remaining = max(0, round(seconds))
        if remaining == 0:
            return

        with sqlite3.connect(self.database_path) as connection:
            cursor = start
            while cursor.date() < end.date():
                midnight = dt.datetime.combine(
                    cursor.date() + dt.timedelta(days=1),
                    dt.time.min,
                )
                portion = min(remaining, max(0, round(
                    (midnight - cursor).total_seconds())))
                self._add_seconds(connection, cursor.date(), portion)
                remaining -= portion
                cursor = midnight
            self._add_seconds(connection, end.date(), remaining)

    @staticmethod
    def _add_seconds(
        connection: sqlite3.Connection,
        day: dt.date,
        seconds: int,
    ) -> None:
        if seconds <= 0:
            return
        connection.execute(
            """
            INSERT INTO daily_totals(day, seconds) VALUES (?, ?)
            ON CONFLICT(day) DO UPDATE SET
                seconds = daily_totals.seconds + excluded.seconds
            """,
            (day.isoformat(), seconds),
        )
