import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from linux_notch.services.screen_time import ScreenTimeService


class ScreenTimeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.monotonic = [100.0]
        self.wall_clock = [
            dt.datetime(2026, 11, 20, 12, 0).timestamp()
        ]
        self.idle_ms = [0]
        self.service = ScreenTimeService(
            database_path=os.path.join(
                self.temp_dir.name, "screen-time.sqlite3"),
            idle_detector=lambda: self.idle_ms[0],
            monotonic=lambda: self.monotonic[0],
            wall_clock=lambda: self.wall_clock[0],
            idle_threshold=300,
            interval_seconds=30,
        )

    def tearDown(self):
        self.service.stop()
        self.temp_dir.cleanup()

    def sample(self, elapsed, idle_ms=0, at=None):
        self.monotonic[0] += elapsed
        self.wall_clock[0] = (
            at if at is not None
            else self.wall_clock[0] + elapsed
        )
        self.idle_ms[0] = idle_ms
        self.service._last_monotonic = self.monotonic[0] - elapsed
        self.service._sample()

    def test_records_only_daily_active_duration(self):
        self.sample(30, idle_ms=20_000)
        day = dt.date.fromtimestamp(self.wall_clock[0]).isoformat()

        with sqlite3.connect(self.service.database_path) as connection:
            row = connection.execute(
                "SELECT day, seconds FROM daily_totals").fetchone()

        self.assertEqual(row, (day, 30))

    def test_excludes_idle_tail_beyond_threshold(self):
        self.sample(30, idle_ms=320_000)

        with sqlite3.connect(self.service.database_path) as connection:
            seconds = connection.execute(
                "SELECT COALESCE(SUM(seconds), 0) FROM daily_totals"
            ).fetchone()[0]

        self.assertEqual(seconds, 10)

    def test_long_idle_interval_does_not_add_screen_time(self):
        self.sample(30, idle_ms=600_000)

        with sqlite3.connect(self.service.database_path) as connection:
            rows = connection.execute(
                "SELECT COUNT(*) FROM daily_totals").fetchone()[0]

        self.assertEqual(rows, 0)

    def test_active_time_is_split_across_midnight(self):
        after_midnight = dt.datetime(2026, 11, 21, 0, 0, 30).timestamp()
        self.sample(60, at=after_midnight)

        with sqlite3.connect(self.service.database_path) as connection:
            rows = connection.execute(
                "SELECT day, seconds FROM daily_totals ORDER BY day"
            ).fetchall()

        self.assertEqual(
            rows,
            [("2026-11-20", 30), ("2026-11-21", 30)],
        )

    def test_week_data_returns_seven_day_window_and_local_totals(self):
        self.sample(30)
        first_day, totals = self.service.week_data()

        self.assertEqual(first_day.weekday(), 6)
        self.assertEqual(len(totals), 1)
        self.assertEqual(
            totals[dt.date.fromtimestamp(self.wall_clock[0]).isoformat()],
            30,
        )

    def test_history_contains_only_aggregated_daily_data(self):
        with sqlite3.connect(self.service.database_path) as connection:
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(daily_totals)")
            }

        self.assertEqual(columns, {"day", "seconds"})

    def test_logind_idle_hint_excludes_the_current_idle_sample(self):
        self.service._idle_proxy = False
        self.service._screensaver_proxy = False
        self.service._xprintidle = None
        self.service._session_id = "42"
        with patch(
            "linux_notch.services.screen_time.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout="true\n",
            ),
        ):
            idle_ms = self.service._get_idle_ms()

        self.assertEqual(idle_ms, 330_000)
        self.assertEqual(self.service.idle_method, "systemd-logind")


if __name__ == "__main__":
    unittest.main()
