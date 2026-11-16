from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeAlias

from linux_notch.desktop.capabilities import Capabilities

Rect: TypeAlias = tuple[int, int, int, int]


def bottom_center_position(
    monitor_x: int,
    monitor_y: int,
    monitor_width: int,
    monitor_height: int,
    window_width: int,
    window_height: int,
    margin_bottom: int,
) -> tuple[int, int]:
    x = monitor_x + max(0, (monitor_width - window_width) // 2)
    y = monitor_y + monitor_height - window_height - margin_bottom
    return x, y


class DesktopBackend(Protocol):
    name: str

    def probe(self) -> Capabilities: ...
    def attach(self, window: object, config: dict) -> None: ...
    def set_geometry(
        self, monitor: str, width: int, height: int, margin_bottom: int
    ) -> None: ...
    def set_input_region(self, rects: list[Rect]) -> None: ...
    def on_monitors_changed(self, callback: Callable[[], None]) -> None: ...
    def shutdown(self) -> None: ...
