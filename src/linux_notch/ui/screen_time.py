"""Screen Time weekly summary and activity chart."""

from __future__ import annotations

import datetime as dt
import weakref

import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

CHART_HEIGHT = 210
DAY_LABELS = ("S", "M", "T", "W", "T", "F", "S")
GRID_MAX_HOURS = 10
GOAL_HOURS = 8


def format_duration(seconds: int) -> str:
    minutes = max(0, seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class ScreenTimeChart(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_content_height(CHART_HEIGHT)
        self.set_content_width(480)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.days: list[tuple[dt.date, int]] = []
        self.today = dt.date.today()

    def set_days(
        self,
        days: list[tuple[dt.date, int]],
        today: dt.date,
    ) -> None:
        self.days = days
        self.today = today
        self.queue_draw()

    def _draw(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        left, right, top, bottom = 8.0, 40.0, 8.0, 28.0
        chart_width = max(1.0, width - left - right)
        chart_height = max(1.0, height - top - bottom)
        max_seconds = GRID_MAX_HOURS * 3600

        cr.select_font_face(
            "Sans",
            cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_NORMAL,
        )
        cr.set_font_size(11)
        for hour in range(0, GRID_MAX_HOURS + 1, 2):
            y = top + chart_height * (1 - hour / GRID_MAX_HOURS)
            if hour == GOAL_HOURS:
                cr.set_dash([7.0, 4.0])
                cr.set_source_rgba(0.92, 0.92, 0.95, 0.68)
            else:
                cr.set_dash([])
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.14)
            cr.move_to(left, y)
            cr.line_to(left + chart_width, y)
            cr.stroke()
            cr.set_dash([])
            cr.set_source_rgba(0.80, 0.80, 0.83, 0.66)
            cr.move_to(left + chart_width + 6, y + 4)
            cr.show_text(f"{hour}h")

        slot = chart_width / max(1, len(self.days))
        bar_width = min(42.0, slot * 0.62)
        for index, (day, seconds) in enumerate(self.days):
            center = left + slot * (index + 0.5)
            bar_height = chart_height * min(
                1.0,
                max(0.0, seconds / max_seconds),
            )
            if bar_height:
                if day == self.today:
                    cr.set_source_rgba(0.03, 0.48, 0.96, 0.96)
                else:
                    cr.set_source_rgba(0.16, 0.53, 0.84, 0.42)
                cr.rectangle(
                    center - bar_width / 2,
                    top + chart_height - bar_height,
                    bar_width,
                    bar_height,
                )
                cr.fill()

            cr.set_source_rgba(0.92, 0.92, 0.94, 0.85)
            cr.move_to(center - 3.5, height - 7)
            cr.show_text(DAY_LABELS[index])


class ScreenTimePage(Gtk.Box):
    def __init__(self, service, on_content_changed=None):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
        )
        self.service = service
        self.on_content_changed = on_content_changed
        self.week_offset = 0
        self.add_css_class("screen-time-page")

        summary = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
        )
        summary.add_css_class("screen-time-summary")
        today_card, self.today_value, self.today_caption = self._summary_card(
            "Today")
        week_card, self.week_value, self.week_caption = self._summary_card(
            "This Week")
        summary.append(today_card)
        summary.append(week_card)

        chart_card = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
        )
        chart_card.add_css_class("screen-time-chart-card")
        self.week_label = Gtk.Label(xalign=0.5)
        self.week_label.add_css_class("screen-time-week-label")
        self.chart = ScreenTimeChart()
        chart_card.append(self.week_label)
        chart_card.append(self.chart)

        navigation = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        navigation.set_halign(Gtk.Align.CENTER)
        self.previous_button = Gtk.Button.new_from_icon_name(
            "go-previous-symbolic")
        self.previous_button.add_css_class("screen-time-nav-button")
        self.previous_button.set_tooltip_text("Previous week")
        self.previous_button.connect(
            "clicked", lambda *_: self.change_week(-1))
        self.next_button = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_button.add_css_class("screen-time-nav-button")
        self.next_button.set_tooltip_text("Next week")
        self.next_button.connect(
            "clicked", lambda *_: self.change_week(1))
        navigation.append(self.previous_button)
        navigation.append(self.next_button)

        privacy = Gtk.Label(
            label=(
                "Active desktop time only · Pauses after 5 minutes idle · "
                "Stored locally"
            ),
            wrap=True,
        )
        privacy.add_css_class("screen-time-privacy")

        self.append(summary)
        self.append(chart_card)
        self.append(navigation)
        self.append(privacy)
        if service is not None:
            page_ref = weakref.ref(self)

            def on_service_updated(*_args):
                page = page_ref()
                if page is not None:
                    page.refresh()

            service.connect("updated", on_service_updated)
        self.refresh()

    @staticmethod
    def _summary_card(title: str):
        card = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
        )
        card.set_hexpand(True)
        card.add_css_class("screen-time-summary-card")
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("screen-time-card-title")
        value = Gtk.Label(label="0m", xalign=0)
        value.add_css_class("screen-time-value")
        caption = Gtk.Label(label="", xalign=0, wrap=True)
        caption.add_css_class("screen-time-caption")
        card.append(title_label)
        card.append(value)
        card.append(caption)
        return card, value, caption

    def change_week(self, amount: int) -> None:
        self.week_offset = min(0, self.week_offset + amount)
        self.refresh()

    def refresh(self) -> None:
        today = dt.date.today()
        if self.service is None:
            first_day = today - dt.timedelta(days=(today.weekday() + 1) % 7)
            totals = {}
            self.week_caption.set_label("Tracking unavailable")
        else:
            first_day, totals = self.service.week_data(self.week_offset)

        days = [
            (
                first_day + dt.timedelta(days=index),
                totals.get(
                    (first_day + dt.timedelta(days=index)).isoformat(),
                    0,
                ),
            )
            for index in range(7)
        ]
        current_today = totals.get(today.isoformat(), 0) if self.week_offset == 0 else (
            self.service.week_data(0)[1].get(today.isoformat(), 0)
            if self.service is not None
            else 0
        )
        week_seconds = sum(seconds for _day, seconds in days)
        elapsed_days = 7
        if self.week_offset == 0:
            elapsed_days = min(7, max(1, (today - first_day).days + 1))
        average = round(week_seconds / elapsed_days)

        self.today_value.set_label(format_duration(current_today))
        if self.service is not None:
            method = self.service.idle_method
            self.today_caption.set_label(
                f"ACTIVE DESKTOP TIME · {method}")
        else:
            self.today_caption.set_label("ACTIVE DESKTOP TIME")
        self.week_value.set_label(format_duration(week_seconds))
        self.week_caption.set_label(
            f"DAILY AVERAGE · {format_duration(average)}")

        last_day = first_day + dt.timedelta(days=6)
        if self.week_offset == 0:
            period = "This week"
        elif self.week_offset == -1:
            period = "Last week"
        else:
            period = "Selected week"
        self.week_label.set_label(
            f"{period} · {first_day:%b %d} – {last_day:%b %d}")
        self.chart.set_days(days, today)
        self.next_button.set_sensitive(self.week_offset < 0)
        if self.on_content_changed is not None:
            self.on_content_changed()
