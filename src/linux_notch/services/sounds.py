from __future__ import annotations

import logging
import math
import shutil
import subprocess
from pathlib import Path

SOUND_NAMES = (
    "annoyed", "approval", "approve", "attach", "blip", "close", "dizzy",
    "error", "finish", "greeting", "greet", "gulp", "hover", "love", "open",
    "peek", "pop", "proud", "question", "rate", "search", "send", "slap",
    "sleep", "think", "tick", "wink", "work", "yawn",
)

_LOG = logging.getLogger(__name__)
_SOUND_DIR = Path(__file__).resolve().parents[1] / "resources" / "sounds"
_PAPLAY: str | None = None
_MISSING_PAPLAY_WARNED = False


def play_sound(name: str, config: dict, *, player: str | None = None) -> bool:
    if name not in SOUND_NAMES:
        raise ValueError(f"Unknown Linux Notch sound: {name}")
    if not config.get("sound_enabled", True):
        return False

    try:
        volume = float(config.get("sound_volume", 0.12))
    except (TypeError, ValueError) as error:
        _LOG.warning("Invalid Linux Notch sound volume %r: %s", config.get("sound_volume"), error)
        return False
    if not math.isfinite(volume):
        _LOG.warning("Invalid non-finite Linux Notch sound volume: %r", volume)
        return False
    volume = min(1.0, max(0.0, volume))
    if volume == 0:
        return False

    sound_path = _SOUND_DIR / f"{name}.wav"
    if not sound_path.is_file():
        raise FileNotFoundError(f"Bundled sound asset is missing: {sound_path}")

    global _PAPLAY, _MISSING_PAPLAY_WARNED
    executable = player or _PAPLAY or shutil.which("paplay")
    if not executable:
        if not _MISSING_PAPLAY_WARNED:
            _LOG.warning("paplay is unavailable; install pulseaudio-utils to enable Mochi sounds")
            _MISSING_PAPLAY_WARNED = True
        return False
    _PAPLAY = executable

    try:
        subprocess.Popen(
            [executable, "--volume", str(round(volume * 65536)), str(sound_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as error:
        _LOG.warning("Could not play Linux Notch sound %s: %s", name, error)
        return False
    return True
