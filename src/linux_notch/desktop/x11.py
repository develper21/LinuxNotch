from __future__ import annotations

import ctypes
import ctypes.util
import os
from collections.abc import Callable
from typing import Any

from linux_notch.desktop.backend import Rect
from linux_notch.desktop.capabilities import Capabilities


class XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


class X11Backend:
    name = "x11"
    _net_atoms = (
        "_NET_WM_WINDOW_TYPE",
        "_NET_WM_WINDOW_TYPE_DOCK",
        "_NET_WM_STATE",
        "_NET_WM_STATE_ABOVE",
        "_NET_WM_STATE_STICKY",
        "_NET_WM_STATE_SKIP_TASKBAR",
        "_NET_WM_STATE_SKIP_PAGER",
        "_NET_WM_ALLOWED_ACTIONS",
        "_NET_WM_ACTION_ABOVE",
        "ATOM",
    )

    @classmethod
    def usable(cls) -> bool:
        if not os.environ.get("DISPLAY") or not ctypes.util.find_library("X11"):
            return False
        x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        display = x11.XOpenDisplay(None)
        if not display:
            return False
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay(display)
        return True

    def __init__(self) -> None:
        library = ctypes.util.find_library("X11")
        if not library:
            raise RuntimeError("libX11 is unavailable")
        self._x11 = ctypes.CDLL(library)
        self._configure_xlib()
        self._display = self._x11.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError("Could not open the X11 display")
        self._window: Any | None = None
        self._window_id = 0
        self._map_handler = 0
        self._monitor_handler = 0
        self._tick_handler = 0
        self._last_width = 0
        self._monitor_callback: Callable[[], None] | None = None
        self._config: dict = {}
        self._shape = None
        shape_library = ctypes.util.find_library("Xext")
        if shape_library:
            self._shape = ctypes.CDLL(shape_library)
            self._shape.XShapeCombineRectangles.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(XRectangle),
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]

    def _configure_xlib(self) -> None:
        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XOpenDisplay.restype = ctypes.c_void_p
        self._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self._x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        self._x11.XDefaultScreen.restype = ctypes.c_int
        self._x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self._x11.XInternAtom.restype = ctypes.c_ulong
        self._x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._x11.XGetSelectionOwner.restype = ctypes.c_ulong
        self._x11.XChangeProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int,
        ]
        self._x11.XMoveWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._x11.XFlush.argtypes = [ctypes.c_void_p]

    def _compositing_available(self) -> bool:
        screen = self._x11.XDefaultScreen(self._display)
        atom = self._atom(f"_NET_WM_CM_S{screen}")
        return bool(self._x11.XGetSelectionOwner(self._display, atom))

    def probe(self) -> Capabilities:
        return Capabilities(
            anchor_top_center=True,
            above_panels=True,
            above_fullscreen=False,
            click_through_outside=self._shape is not None,
            per_monitor=True,
            transparent_surface=self._compositing_available(),
            background_clipboard=True,
            window_info=True,
        )

    def attach(self, window: object, config: dict) -> None:
        self._window = window
        self._config = config
        self._last_width = 0
        if not self._tick_handler and hasattr(window, "add_tick_callback"):
            self._tick_handler = window.add_tick_callback(self._on_tick)
        if not self._map_handler:
            self._map_handler = window.connect("map", lambda *_args: self._apply_hints())
        if window.get_mapped():
            self._apply_hints()

    def _on_tick(self, widget: Any, _frame_clock: Any) -> bool:
        if self._window is None or not self._window_id:
            return True
        width = widget.get_width()
        if width > 0 and width != self._last_width:
            self._last_width = width
            self._move_to_monitor()
        return True

    def _apply_hints(self) -> None:
        if self._window is None:
            return
        try:
            import gi

            gi.require_version("GdkX11", "4.0")
            from gi.repository import GdkX11
        except (ImportError, ValueError) as error:
            raise RuntimeError("GDK X11 support is required for the X11 backend") from error
        surface = self._window.get_surface()
        if surface is None:
            return
        self._window_id = int(GdkX11.X11Surface.get_xid(surface))
        atoms = {name: self._atom(name) for name in self._net_atoms}
        self._set_atom_list(
            atoms["_NET_WM_WINDOW_TYPE"],
            atoms["ATOM"],
            [atoms["_NET_WM_WINDOW_TYPE_DOCK"]],
        )
        self._set_atom_list(
            atoms["_NET_WM_STATE"],
            atoms["ATOM"],
            [
                atoms["_NET_WM_STATE_ABOVE"],
                atoms["_NET_WM_STATE_STICKY"],
                atoms["_NET_WM_STATE_SKIP_TASKBAR"],
                atoms["_NET_WM_STATE_SKIP_PAGER"],
            ],
        )
        self._set_atom_list(
            atoms["_NET_WM_ALLOWED_ACTIONS"],
            atoms["ATOM"],
            [atoms["_NET_WM_ACTION_ABOVE"]],
        )
        self._move_to_monitor()

    def _atom(self, name: str) -> int:
        return self._x11.XInternAtom(self._display, name.encode(), 0)

    def _set_atom_list(self, prop: int, atom_type: int, values: list[int]) -> None:
        data = (ctypes.c_ulong * len(values))(*values)
        self._x11.XChangeProperty(
            self._display,
            self._window_id,
            prop,
            atom_type,
            32,
            0,
            ctypes.cast(data, ctypes.POINTER(ctypes.c_ubyte)),
            len(values),
        )

    def _move_to_monitor(self) -> None:
        if self._window is None or not self._window_id:
            return
        display = self._window.get_display()
        monitors = display.get_monitors()
        wanted = self._config.get("monitor", "")
        monitor = None
        for index in range(monitors.get_n_items()):
            candidate = monitors.get_item(index)
            if candidate.get_connector() == wanted:
                monitor = candidate
                break
        if monitor is None:
            monitor = display.get_primary_monitor() or monitors.get_item(0)
        geometry = monitor.get_geometry()
        width = self._window.get_width()
        x = geometry.x + max(0, (geometry.width - width) // 2)
        y = geometry.y + int(self._config.get("margin_top", 0))
        self._x11.XMoveWindow(self._display, self._window_id, x, y)
        self._x11.XFlush(self._display)

    def set_geometry(self, monitor: str, width: int, height: int, margin_top: int) -> None:
        if self._window is None:
            return
        self._window.set_default_size(width, height)
        self._config.update(monitor=monitor, margin_top=margin_top)
        self._move_to_monitor()

    def set_input_region(self, rects: list[Rect]) -> None:
        if self._shape is None or not self._window_id:
            return
        rectangles = (XRectangle * len(rects))(
            *(XRectangle(x, y, width, height) for x, y, width, height in rects)
        )
        self._shape.XShapeCombineRectangles(
            self._display,
            self._window_id,
            2,
            0,
            0,
            rectangles,
            len(rects),
            0,
            0,
        )
        self._x11.XFlush(self._display)

    def on_monitors_changed(self, callback: Callable[[], None]) -> None:
        if self._window is None:
            return
        monitors = self._window.get_display().get_monitors()
        if self._monitor_handler:
            monitors.disconnect(self._monitor_handler)
        self._monitor_callback = callback
        self._monitor_handler = monitors.connect(
            "items-changed", lambda *_args: self._on_monitors_changed()
        )

    def _on_monitors_changed(self) -> None:
        self._move_to_monitor()
        if self._monitor_callback is not None:
            self._monitor_callback()

    def shutdown(self) -> None:
        if self._window is not None and self._tick_handler:
            self._window.remove_tick_callback(self._tick_handler)
        if self._window is not None and self._map_handler:
            self._window.disconnect(self._map_handler)
        if self._window is not None and self._monitor_handler:
            self._window.get_display().get_monitors().disconnect(self._monitor_handler)
        self._window = None
        self._window_id = 0
        self._tick_handler = 0
        self._last_width = 0
        self._map_handler = 0
        self._monitor_handler = 0
        self._monitor_callback = None
        if self._display:
            self._x11.XCloseDisplay(self._display)
            self._display = None
