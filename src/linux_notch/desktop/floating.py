from collections.abc import Callable

from linux_notch.desktop.backend import Rect
from linux_notch.desktop.capabilities import Capabilities


class FloatingWindowBackend:
    name = "floating"

    def probe(self) -> Capabilities:
        return Capabilities(
            anchor_bottom_center=False,
            above_panels=False,
            above_fullscreen=False,
            click_through_outside=False,
            per_monitor=False,
            transparent_surface=False,
            background_clipboard=False,
            window_info=False,
        )

    def attach(self, window: object, config: dict) -> None:
        return None

    def set_geometry(
        self, monitor: str, width: int, height: int, margin_bottom: int
    ) -> None:
        return None

    def set_input_region(self, rects: list[Rect]) -> None:
        return None

    def on_monitors_changed(self, callback: Callable[[], None]) -> None:
        return None

    def shutdown(self) -> None:
        return None
