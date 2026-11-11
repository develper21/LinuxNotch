"""Spotify installation detection for the MPRIS-backed feature page."""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def spotify_installed() -> bool:
    if shutil.which("spotify"):
        return True
    for executable, args in (
        ("flatpak", ["info", "com.spotify.Client"]),
        ("snap", ["list", "spotify"]),
    ):
        if not shutil.which(executable):
            continue
        try:
            result = subprocess.run(
                [executable, *args],
                capture_output=True,
                check=False,
                timeout=3,
            )
        except subprocess.TimeoutExpired:
            logger.warning("%s installation check timed out", executable)
            continue
        except OSError as error:
            logger.warning("Could not check Spotify via %s: %s",
                           executable, error)
            continue
        if result.returncode == 0:
            return True
    return False
