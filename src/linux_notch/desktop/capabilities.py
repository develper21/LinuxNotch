from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    anchor_top_center: bool
    above_panels: bool
    above_fullscreen: bool
    click_through_outside: bool
    per_monitor: bool
    transparent_surface: bool
    background_clipboard: bool
    window_info: bool
