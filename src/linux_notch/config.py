"""User configuration, stored as plain JSON in ~/.config/linux-notch/config.json.

Missing keys fall back to defaults, so upgrades never break an old config.
"""

from __future__ import annotations

import json
import os

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "linux-notch"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "linux-notch"
)

DEFAULTS = {
    # top margin in px between screen edge and the island
    "margin_top": 0,
    # sit on top of panels/bars instead of being pushed below them
    "overlap_panel": True,
    # monitor connector name ("" = primary / compositor default)
    "monitor": "",
    # "top" stays below fullscreen apps, "overlay" is always on top
    "layer": "top",
    "fullscreen_policy": "hide",
    # how often (seconds) the Claude usage module refreshes
    "claude_refresh": 60,
    # island background opacity, 0.3 .. 1.0
    "opacity": 0.97,
    # 24h clock
    "clock_24h": True,
    # seconds a peek (volume / battery / notification) stays visible
    "peek_seconds": 2.2,
    # clipboard history is opt-in and stored only on this device
    "clipboard_recording": False,
    # modules that may take over the island
    "modules": {
        "music": True,
        "volume_osd": True,
        "battery": True,
        "notifications": True,
        "network": True,
        "bluetooth": True,
        "weather": True,
        "system": True,
        "toggles": True,
        "clipboard": True,
        "spotify": True,
        # Claude usage reads Claude Code credentials only when explicitly enabled.
        "claude_usage": False,
    },
    # weather location ("" = auto by IP); any wttr.in place name works
    "weather_city": "",
    # accent color used for progress bars and highlights
    "accent": "#ff9f0a",
    # Mochi appearance and sound effects
    "mochi_outfit": "auto",
    "sound_enabled": True,
    "sound_volume": 0.12,
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _merge(base[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return _merge(DEFAULTS, json.load(f))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def write_default() -> str:
    """Write a commented default config if none exists; returns the path."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULTS, f, indent=2)
    return CONFIG_PATH


def save(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
