"""Shared island palettes and colors used by GTK and Cairo rendering."""

from __future__ import annotations

from typing import TypedDict


class Palette(TypedDict):
    island: str
    border: str
    card: str
    pill: str
    alpha: float


PALETTES: dict[str, Palette] = {
    "pure_black": {
        "island": "#000000",
        "border": "#000000",
        "card": "#121212",
        "pill": "#1c1c1c",
        "alpha": 1.0,
    },
    "soft_black": {
        "island": "#0d0d10",
        "border": "#26262c",
        "card": "#17171b",
        "pill": "#202026",
        "alpha": 1.0,
    },
    "graphite": {
        "island": "#18191e",
        "border": "#32343c",
        "card": "#21232a",
        "pill": "#2b2e37",
        "alpha": 1.0,
    },
    "midnight": {
        "island": "#0b1022",
        "border": "#222c52",
        "card": "#131b36",
        "pill": "#1b2547",
        "alpha": 1.0,
    },
    "wine": {
        "island": "#1b0b12",
        "border": "#4a2030",
        "card": "#27121b",
        "pill": "#331824",
        "alpha": 1.0,
    },
    "smoked_glass": {
        "island": "#0a0a0c",
        "border": "#3a3a42",
        "card": "#16161a",
        "pill": "#202026",
        "alpha": 0.72,
    },
}
PALETTE_LABELS = {
    "soft_black": "Soft black (recommended)",
    "pure_black": "Pure black",
    "graphite": "Graphite",
    "midnight": "Midnight",
    "wine": "Wine",
    "smoked_glass": "Smoked glass",
}

ACTIVE = "soft_black"
TEXT = "#e8e8ea"
MUTED_TEXT = "#8a8a90"
CHARACTER = "#f5a25d"
EQUALIZER_PALETTE = ("#ff5c8a", "#ffb347", "#4dd8ff")
FEATURE_COLORS = {
    "music": "#ff5c8a",
    "mail": "#4dd8ff",
    "terminal": "#98c379",
    "system": "#ffb347",
}


def get_palette(name: str | None) -> Palette:
    return PALETTES.get(name or ACTIVE, PALETTES[ACTIVE])


def rgb(color: str) -> tuple[float, float, float]:
    if (
        len(color) != 7
        or not color.startswith("#")
        or any(character not in "0123456789abcdefABCDEF"
               for character in color[1:])
    ):
        raise ValueError(f"Expected a #RRGGBB color, got {color!r}")
    return tuple(
        int(color[index:index + 2], 16) / 255
        for index in (1, 3, 5)
    )


def rgba_css(color: str, alpha: float = 1.0) -> str:
    red, green, blue = (
        int(round(component * 255)) for component in rgb(color)
    )
    alpha = min(1.0, max(0.0, alpha))
    return f"rgba({red}, {green}, {blue}, {alpha:.3f})"


def css_definitions(
    name: str | None,
    accent: str = "#ff9f0a",
) -> str:
    palette = get_palette(name)
    definitions = {
        "accent": accent,
        "notch_island": rgba_css(palette["island"], palette["alpha"]),
        "notch_border": palette["border"],
        "notch_card": palette["card"],
        "notch_pill": palette["pill"],
        "notch_text": TEXT,
        "notch_muted": MUTED_TEXT,
        "notch_character": CHARACTER,
        "notch_eq_pink": EQUALIZER_PALETTE[0],
        "notch_eq_orange": EQUALIZER_PALETTE[1],
        "notch_eq_cyan": EQUALIZER_PALETTE[2],
        "notch_music": FEATURE_COLORS["music"],
        "notch_mail": FEATURE_COLORS["mail"],
        "notch_terminal": FEATURE_COLORS["terminal"],
        "notch_widgets": FEATURE_COLORS["system"],
    }
    return "".join(
        f"@define-color {key} {value};\n"
        for key, value in definitions.items()
    )
