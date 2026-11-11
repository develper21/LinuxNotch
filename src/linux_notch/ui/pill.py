"""The collapsed island: Mochi only."""

from __future__ import annotations

from gi.repository import Gtk

from linux_notch.ui.mochi import MochiWidget


class Pill(Gtk.Box):
    def __init__(self, cfg: dict):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("pill")
        self.set_size_request(240, 32)
        self.mochi = MochiWidget(cfg)
        self.mochi.set_content_width(28)
        self.mochi.set_content_height(28)
        self.mochi.set_size_request(28, 28)
        self.launcher = Gtk.Button()
        self.launcher.add_css_class("launcher-button")
        self.launcher.set_icon_name("view-grid-symbolic")
        self.launcher.set_tooltip_text("Open feature selector")

        spacer = Gtk.Box(hexpand=True)
        self.append(self.mochi)
        self.append(spacer)
        self.append(self.launcher)

    def show_activity(self, activity: dict | None):
        self.mochi.show_activity(activity)
