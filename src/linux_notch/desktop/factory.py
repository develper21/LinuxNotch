from __future__ import annotations

import os
from collections.abc import Mapping

from linux_notch.desktop.backend import DesktopBackend
from linux_notch.desktop.floating import FloatingWindowBackend


def choose_backend(env: Mapping[str, str] | None = None) -> DesktopBackend:
    environment = os.environ if env is None else env
    session = environment.get("XDG_SESSION_TYPE", "").lower()
    desktop = environment.get("XDG_CURRENT_DESKTOP", "").upper()

    if session == "wayland":
        gdk_backends = environment.get("GDK_BACKEND", "").lower().split(",")
        if gdk_backends[0] == "x11" and environment.get("DISPLAY"):
            from linux_notch.desktop.x11 import X11Backend

            if X11Backend.usable():
                return X11Backend()
        from linux_notch.desktop.layer_shell import LayerShellBackend

        if LayerShellBackend.is_supported():
            return LayerShellBackend()
        if "GNOME" in desktop:
            from linux_notch.desktop.gnome import GnomeBackend

            if GnomeBackend.helper_available():
                return GnomeBackend()
        return FloatingWindowBackend()

    if environment.get("DISPLAY"):
        from linux_notch.desktop.x11 import X11Backend

        if X11Backend.usable():
            return X11Backend()
    return FloatingWindowBackend()
