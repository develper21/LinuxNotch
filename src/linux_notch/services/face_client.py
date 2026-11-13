"""D-Bus client for interacting with the Linux Notch Face Daemon."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
from gi.repository import Gio, GLib, GObject  # noqa: E402

from linux_notch.services.face_daemon import BUS_NAME, INTERFACE, OBJECT_PATH  # noqa: E402
from linux_notch.services.face_engine import (  # noqa: E402
    DEFAULT_THRESHOLD,
    EMBEDDINGS_PATH,
)

logger = logging.getLogger(__name__)


class FaceDaemonClient(GObject.Object):
    __gsignals__ = {
        "state-changed": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (str, str),
        ),
        "frame-received": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (float, float, float, float),
        ),
        "result-received": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (bool, float),
        ),
        "enroll-progress": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (int, int, str),
        ),
        "enroll-complete": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (bool, str),
        ),
    }

    def __init__(self, enrollment_path: Path = EMBEDDINGS_PATH):
        super().__init__()
        self._enrollment_path = enrollment_path
        self._connection: Gio.DBusConnection | None = None
        self._subscriptions: list[int] = []
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._subscribe_signals()
        except GLib.Error as error:
            logger.warning("Could not connect to session D-Bus: %s", error)

    def _subscribe_signals(self) -> None:
        if self._connection is None:
            return
        sub = self._connection.signal_subscribe(
            BUS_NAME,
            INTERFACE,
            None,
            OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_dbus_signal,
        )
        self._subscriptions.append(sub)

    def _on_dbus_signal(
        self,
        _connection: Gio.DBusConnection,
        _sender_name: str,
        _object_path: str,
        _interface_name: str,
        signal_name: str,
        parameters: GLib.Variant,
    ) -> None:
        try:
            if signal_name == "ScanState":
                state, msg = parameters.unpack()
                self.emit("state-changed", state, msg)
            elif signal_name == "ScanFrame":
                x, y, w, h, _landmarks = parameters.unpack()
                self.emit("frame-received", float(x), float(y), float(w), float(h))
            elif signal_name == "ScanResult":
                success, score = parameters.unpack()
                self.emit("result-received", bool(success), float(score))
            elif signal_name == "EnrollProgress":
                step, total, pose = parameters.unpack()
                self.emit("enroll-progress", int(step), int(total), str(pose))
            elif signal_name == "EnrollComplete":
                success, msg = parameters.unpack()
                self.emit("enroll-complete", bool(success), str(msg))
        except Exception as error:
            logger.error("Error processing FaceDaemon signal %s: %s", signal_name, error)

    def is_available(self) -> bool:
        if self._connection is None:
            return False
        try:
            val = self._connection.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "GetNameOwner",
                GLib.Variant("(s)", (BUS_NAME,)),
                GLib.VariantType.new("(s)"),
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            return bool(val and val.unpack()[0])
        except GLib.Error:
            return False

    def _call(self, method: str, parameters: GLib.Variant | None = None, return_type: str | None = None) -> Any:
        if self._connection is None:
            raise RuntimeError("D-Bus connection is not available.")
        params = parameters if parameters is not None else GLib.Variant("()", ())
        expected = GLib.VariantType.new(return_type) if return_type else GLib.VariantType.new("()")
        result = self._connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            method,
            params,
            expected,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        return result.unpack() if result else None

    def get_status(self) -> dict[str, Any]:
        if self.is_available():
            try:
                res = self._call("GetStatus", return_type="(bibdb)")
                if res:
                    is_enrolled, sample_count, enabled, threshold, challenge_enabled = res
                    return {
                        "enrolled": bool(is_enrolled),
                        "sample_count": int(sample_count),
                        "enabled": bool(enabled),
                        "threshold": float(threshold),
                        "challenge_enabled": bool(challenge_enabled),
                        "daemon_running": True,
                    }
            except Exception as error:
                logger.debug("GetStatus D-Bus call failed: %s", error)

        # Fallback to local files if daemon is not running
        enrolled = self._enrollment_path.is_file()
        samples = 0
        if enrolled:
            try:
                import numpy as np

                data = np.load(self._enrollment_path, allow_pickle=False)
                samples = len(data)
            except Exception:
                samples = 0
        return {
            "enrolled": enrolled,
            "sample_count": samples,
            "enabled": True,
            "threshold": DEFAULT_THRESHOLD,
            "challenge_enabled": False,
            "daemon_running": False,
        }

    def set_threshold(self, threshold: float) -> bool:
        if self.is_available():
            try:
                self._call("SetThreshold", GLib.Variant("(d)", (float(threshold),)))
                return True
            except Exception as error:
                logger.error("SetThreshold failed: %s", error)
        return False

    def set_enabled(self, enabled: bool) -> bool:
        if self.is_available():
            try:
                self._call("SetEnabled", GLib.Variant("(b)", (bool(enabled),)))
                return True
            except Exception as error:
                logger.error("SetEnabled failed: %s", error)
        return False

    def set_challenge(self, enabled: bool) -> bool:
        if self.is_available():
            try:
                self._call("SetChallenge", GLib.Variant("(b)", (bool(enabled),)))
                return True
            except Exception as error:
                logger.error("SetChallenge failed: %s", error)
        return False

    def reset(self) -> bool:
        if self.is_available():
            try:
                res = self._call("Reset", return_type="(b)")
                return bool(res and res[0])
            except Exception as error:
                logger.error("Reset failed over D-Bus: %s", error)
        # Local fallback reset
        if self._enrollment_path.exists():
            try:
                self._enrollment_path.unlink()
                return True
            except OSError as error:
                logger.error("Local reset failed: %s", error)
                return False
        return True

    def start_test_scan(self) -> bool:
        if not self.is_available():
            raise RuntimeError("Face Daemon is not running. Start it with `linux-notch-face-daemon`.")
        self._call("TestScan")
        return True

    def start_enroll(self) -> bool:
        if not self.is_available():
            raise RuntimeError("Face Daemon is not running. Start it with `linux-notch-face-daemon`.")
        self._call("StartEnroll")
        return True

    def stop_scan(self) -> bool:
        if self.is_available():
            try:
                self._call("StopScan")
                return True
            except Exception:
                pass
        return False

    def close(self) -> None:
        if self._connection is not None:
            for sub in self._subscriptions:
                self._connection.signal_unsubscribe(sub)
            self._subscriptions.clear()
            self._connection = None
