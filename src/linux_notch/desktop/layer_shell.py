from __future__ import annotations

import ctypes
import ctypes.util
from collections.abc import Callable
from typing import Any

from linux_notch.desktop.backend import Rect
from linux_notch.desktop.capabilities import Capabilities


def _layer_shell_module() -> Any | None:
    try:
        import gi

        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell
    except (ImportError, ValueError):
        return None
    return Gtk4LayerShell


class LayerShellBackend:
    name = "layer-shell"

    @classmethod
    def is_supported(cls) -> bool:
        library = ctypes.util.find_library("gtk4-layer-shell")
        if not library:
            return False
        module = _layer_shell_module()
        return bool(module and getattr(module, "is_supported", lambda: False)())

    def __init__(self) -> None:
        module = _layer_shell_module()
        if module is None or not module.is_supported():
            raise RuntimeError("gtk4-layer-shell is not supported by this session")
        self._layer_shell = module
        self._window: Any | None = None
        self._monitor_handler = 0
        self._monitor_callback: Callable[[], None] | None = None

    def probe(self) -> Capabilities:
        return Capabilities(
            anchor_top_center=True,
            above_panels=True,
            above_fullscreen=True,
            click_through_outside=True,
            per_monitor=True,
            transparent_surface=True,
            background_clipboard=False,
            window_info=True,
        )

    def attach(self, window: object, config: dict) -> None:
        ls = self._layer_shell
        self._window = window
        ls.init_for_window(window)
        ls.set_namespace(window, "linux-notch")
        layer = ls.Layer.OVERLAY if config.get("layer") == "overlay" else ls.Layer.TOP
        ls.set_layer(window, layer)
        ls.set_anchor(window, ls.Edge.TOP, True)
        ls.set_margin(window, ls.Edge.TOP, int(config.get("margin_top", 0)))
        ls.set_exclusive_zone(
            window, -1 if config.get("overlap_panel", True) else 0
        )
        self._pick_monitor(window, config.get("monitor", ""))

    def _pick_monitor(self, window: Any, wanted: str) -> None:
        if not wanted:
            return
        monitors = window.get_display().get_monitors()
        for index in range(monitors.get_n_items()):
            monitor = monitors.get_item(index)
            if monitor.get_connector() == wanted:
                self._layer_shell.set_monitor(window, monitor)
                return

    def set_geometry(self, monitor: str, width: int, height: int, margin_top: int) -> None:
        if self._window is None:
            return
        self._window.set_default_size(width, height)
        self._layer_shell.set_margin(
            self._window, self._layer_shell.Edge.TOP, margin_top
        )
        self._pick_monitor(self._window, monitor)

    def set_input_region(self, rects: list[Rect]) -> None:
        return None

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
        if self._window is not None:
            self._pick_monitor(self._window, "")
        if self._monitor_callback is not None:
            self._monitor_callback()

    def shutdown(self) -> None:
        if self._window is not None and self._monitor_handler:
            self._window.get_display().get_monitors().disconnect(self._monitor_handler)
        self._monitor_handler = 0
        self._monitor_callback = None
        self._window = None
