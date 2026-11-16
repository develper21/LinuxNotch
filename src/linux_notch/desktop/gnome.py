from __future__ import annotations

from collections.abc import Callable
from typing import Any

from linux_notch.desktop.backend import Rect
from linux_notch.desktop.capabilities import Capabilities

BUS_NAME = "org.linuxnotch.GnomeHelper"
OBJECT_PATH = "/org/linuxnotch/GnomeHelper"
INTERFACE = "org.linuxnotch.GnomeHelper"


def _gio() -> tuple[Any, Any]:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    return Gio, GLib


class GnomeBackend:
    name = "gnome-extension"

    @classmethod
    def helper_available(cls) -> bool:
        try:
            Gio, GLib = _gio()
        except (ImportError, ValueError):
            return False
        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            connection.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "GetNameOwner",
                GLib.Variant("(s)", (BUS_NAME,)),
                GLib.VariantType.new("(s)"),
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
        except GLib.Error:
            return False
        return True

    def __init__(self) -> None:
        if not self.helper_available():
            raise RuntimeError("Linux Notch GNOME Shell helper is not running")
        Gio, _ = _gio()
        self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._window: Any | None = None
        self._monitor_subscription = 0

    def probe(self) -> Capabilities:
        return Capabilities(
            anchor_bottom_center=True,
            above_panels=True,
            above_fullscreen=False,
            click_through_outside=True,
            per_monitor=True,
            transparent_surface=True,
            background_clipboard=False,
            window_info=True,
        )

    def attach(self, window: object, config: dict) -> None:
        _, GLib = _gio()
        self._window = window
        self._connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            "Attach",
            GLib.Variant(
                "(ssi)",
                (
                    str(config.get("app_id", "org.linuxnotch.LinuxNotch")),
                    str(config.get("monitor", "")),
                    int(config.get("margin_bottom", -28)),
                ),
            ),
            None,
            0,
            3000,
            None,
        )
        self._connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            "SetFullscreenPolicy",
            GLib.Variant("(s)", (str(config.get("fullscreen_policy", "hide")),)),
            None,
            0,
            3000,
            None,
        )

    def set_geometry(
        self, monitor: str, width: int, height: int, margin_bottom: int
    ) -> None:
        _, GLib = _gio()
        self._connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            "SetSize",
            GLib.Variant("(ii)", (width, height)),
            None,
            0,
            3000,
            None,
        )

    def focus(self) -> None:
        _, GLib = _gio()
        self._connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            "Focus",
            GLib.Variant("()", ()),
            None,
            0,
            3000,
            None,
        )

    def set_input_region(self, rects: list[Rect]) -> None:
        return None

    def on_monitors_changed(self, callback: Callable[[], None]) -> None:
        Gio, _ = _gio()
        if self._monitor_subscription:
            self._connection.signal_unsubscribe(self._monitor_subscription)
        self._monitor_subscription = self._connection.signal_subscribe(
            BUS_NAME,
            INTERFACE,
            "MonitorsChanged",
            OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            lambda *_args: callback(),
            None,
        )

    def shutdown(self) -> None:
        if self._monitor_subscription:
            self._connection.signal_unsubscribe(self._monitor_subscription)
            self._monitor_subscription = 0
        self._window = None
