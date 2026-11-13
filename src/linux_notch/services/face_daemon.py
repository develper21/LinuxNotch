"""Session-bus bridge and bounded, on-demand face scanning."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from linux_notch.services.face_engine import (
    DEFAULT_THRESHOLD,
    EMBEDDINGS_PATH,
    FaceEngine,
    FaceEngineError,
)

BUS_NAME = "org.linuxnotch.FaceDaemon"
OBJECT_PATH = "/org/linuxnotch/FaceDaemon"
INTERFACE = "org.linuxnotch.FaceDaemon"
MAX_SCAN_SECONDS = 8.0
MAX_ATTEMPTS_PER_LOCK = 3
MATCH_STREAK_REQUIRED = 3
FRAME_SIGNAL_INTERVAL = 1 / 15
MIN_FACE_HEIGHT = 0.16

INTROSPECTION_XML = """
<node>
  <interface name="org.linuxnotch.FaceDaemon">
    <method name="StartScan"/>
    <method name="StopScan"/>
    <method name="TestScan"/>
    <method name="StartEnroll"/>
    <method name="Reset">
      <arg type="b" name="success" direction="out"/>
    </method>
    <method name="GetStatus">
      <arg type="b" name="is_enrolled" direction="out"/>
      <arg type="i" name="sample_count" direction="out"/>
      <arg type="b" name="enabled" direction="out"/>
      <arg type="d" name="threshold" direction="out"/>
      <arg type="b" name="challenge_enabled" direction="out"/>
    </method>
    <method name="SetThreshold">
      <arg type="d" name="threshold" direction="in"/>
    </method>
    <method name="SetEnabled">
      <arg type="b" name="enabled" direction="in"/>
    </method>
    <method name="SetChallenge">
      <arg type="b" name="enabled" direction="in"/>
    </method>
    <method name="SetLocked">
      <arg type="b" name="locked" direction="in"/>
    </method>
    <method name="UserActivity"/>
    <signal name="ScanState">
      <arg type="s" name="state"/>
      <arg type="s" name="message"/>
    </signal>
    <signal name="ScanFrame">
      <arg type="d" name="x"/>
      <arg type="d" name="y"/>
      <arg type="d" name="width"/>
      <arg type="d" name="height"/>
      <arg type="a(dd)" name="landmarks"/>
    </signal>
    <signal name="ScanResult">
      <arg type="b" name="success"/>
      <arg type="d" name="score"/>
    </signal>
    <signal name="EnrollProgress">
      <arg type="i" name="step"/>
      <arg type="i" name="total"/>
      <arg type="s" name="pose"/>
    </signal>
    <signal name="EnrollComplete">
      <arg type="b" name="success"/>
      <arg type="s" name="message"/>
    </signal>
  </interface>
</node>
"""

logger = logging.getLogger(__name__)


class FaceDaemonError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _open_camera():
    try:
        import cv2
    except ImportError as error:
        raise FaceEngineError(
            "OpenCV is missing; install the optional face dependencies."
        ) from error
    try:
        camera = cv2.VideoCapture(0, cv2.CAP_V4L2)
    except cv2.error as error:
        raise FaceEngineError(f"Could not initialize camera 0: {error}") from error
    if not camera.isOpened():
        camera.release()
        raise FaceEngineError(
            "Could not open camera 0. Check camera permissions or configure "
            "a working V4L2 camera before scanning.")
    return camera


def _unit_coordinate(value: float) -> float:
    if not math.isfinite(value):
        raise FaceEngineError("Face detector returned invalid coordinates.")
    return min(1.0, max(0.0, value))


def _normalized_frame(observation, frame):
    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        raise FaceEngineError("Camera returned an invalid frame size.")
    x, y, box_width, box_height = observation.box
    left = _unit_coordinate(x / width)
    top = _unit_coordinate(y / height)
    right = _unit_coordinate((x + box_width) / width)
    bottom = _unit_coordinate((y + box_height) / height)
    landmarks = tuple(
        (_unit_coordinate(point_x / width), _unit_coordinate(point_y / height))
        for point_x, point_y in observation.landmarks
    )
    return left, top, max(0.0, right - left), max(0.0, bottom - top), landmarks


def _detect_turn_left(landmarks) -> bool:
    if len(landmarks) < 5:
        return False
    r_eye, l_eye, nose = landmarks[0], landmarks[1], landmarks[2]
    dx = abs(l_eye[0] - r_eye[0])
    if dx < 1e-4:
        return False
    mid_x = (r_eye[0] + l_eye[0]) / 2.0
    offset = (nose[0] - mid_x) / dx
    return abs(offset) > 0.18


class FaceScanController:
    def __init__(
        self,
        emit: Callable[[str, tuple[Any, ...]], None],
        *,
        engine_factory: Callable[[], Any] = FaceEngine,
        camera_factory: Callable[[], Any] = _open_camera,
        enrollment_path: Path = EMBEDDINGS_PATH,
        threshold: float = DEFAULT_THRESHOLD,
        clock: Callable[[], float] = time.monotonic,
        thread_factory=threading.Thread,
        enabled: bool = True,
        challenge_enabled: bool = False,
    ):
        self._emit = emit
        self._engine_factory = engine_factory
        self._camera_factory = camera_factory
        self._enrollment_path = enrollment_path
        self._threshold = threshold
        self._clock = clock
        self._thread_factory = thread_factory
        self._enabled = enabled
        self._challenge_enabled = challenge_enabled
        self._lock = threading.Lock()
        self._locked = False
        self._attempts = 0
        self._active = False
        self._cancel: threading.Event | None = None
        self._thread = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def set_locked(self, locked: bool) -> None:
        with self._lock:
            if self._locked == locked:
                return
            self._locked = locked
            self._attempts = 0
            if not locked and self._cancel is not None:
                self._cancel.set()

    def user_activity(self) -> None:
        with self._lock:
            if not self._locked:
                raise FaceDaemonError(
                    "NotLocked", "User activity can re-arm scans only while locked.")
            if not self._active:
                self._attempts = 0

    def get_status(self) -> tuple[bool, int, bool, float, bool]:
        with self._lock:
            is_enrolled = self._enrollment_path.is_file()
            sample_count = 0
            if is_enrolled:
                try:
                    engine = self._engine_factory()
                    enrolled = engine.load_enrollment(self._enrollment_path)
                    sample_count = len(enrolled)
                except Exception:
                    sample_count = 0
            return (
                is_enrolled,
                sample_count,
                self._enabled,
                self._threshold,
                self._challenge_enabled,
            )

    def set_threshold(self, threshold: float) -> None:
        with self._lock:
            if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
                raise FaceDaemonError(
                    "InvalidThreshold", "Threshold must be between 0.0 and 1.0.")
            self._threshold = float(threshold)

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    def set_challenge(self, enabled: bool) -> None:
        with self._lock:
            self._challenge_enabled = bool(enabled)

    def reset(self) -> bool:
        with self._lock:
            if self._active and self._cancel is not None:
                self._cancel.set()
            if self._enrollment_path.exists():
                try:
                    self._enrollment_path.unlink()
                except OSError as error:
                    raise FaceDaemonError("ResetFailed", f"Could not reset face data: {error}")
            return True

    def start_scan(self) -> None:
        with self._lock:
            if not self._locked:
                raise FaceDaemonError(
                    "NotLocked", "Face scanning is allowed only on the lock screen.")
            if not self._enabled:
                raise FaceDaemonError(
                    "Disabled", "Face scanning is disabled in settings.")
            if self._active:
                raise FaceDaemonError("Busy", "A face scan is already running.")
            if self._attempts >= MAX_ATTEMPTS_PER_LOCK:
                raise FaceDaemonError(
                    "AttemptLimit",
                    "Three scan attempts were used. User activity is required "
                    "before trying again.",
                )
            if not self._enrollment_path.is_file():
                raise FaceDaemonError(
                    "NotEnrolled", "No face enrollment is available.")
            self._attempts += 1
            cancel = threading.Event()
            self._cancel = cancel
            self._active = True
            self._emit("ScanState", ("scanning", "Starting face scan"))
            self._thread = self._thread_factory(
                target=self._scan_worker,
                args=(cancel, False),
                name="linux-notch-face-scan",
                daemon=True,
            )
            self._thread.start()

    def start_test_scan(self) -> None:
        with self._lock:
            if self._active:
                raise FaceDaemonError("Busy", "A face scan or test is already running.")
            cancel = threading.Event()
            self._cancel = cancel
            self._active = True
            self._emit("ScanState", ("scanning", "Starting test scan"))
            self._thread = self._thread_factory(
                target=self._scan_worker,
                args=(cancel, True),
                name="linux-notch-face-test-scan",
                daemon=True,
            )
            self._thread.start()

    def start_enroll(self) -> None:
        with self._lock:
            if self._active:
                raise FaceDaemonError("Busy", "Camera is already in use.")
            cancel = threading.Event()
            self._cancel = cancel
            self._active = True
            self._emit("ScanState", ("enrolling", "Starting enrollment"))
            self._thread = self._thread_factory(
                target=self._enroll_worker,
                args=(cancel,),
                name="linux-notch-face-enroll",
                daemon=True,
            )
            self._thread.start()

    def stop_scan(self) -> None:
        with self._lock:
            if self._cancel is not None:
                self._cancel.set()

    def close(self) -> None:
        with self._lock:
            self._locked = False
            if self._cancel is not None:
                self._cancel.set()

    def _enroll_worker(self, cancel: threading.Event) -> None:
        camera = None
        collected = []
        target_samples = 8
        poses = (
            "Look straight ahead",
            "Turn slightly left",
            "Turn slightly right",
            "Tilt slightly up",
            "Tilt slightly down",
            "Smile slightly",
            "Look straight ahead",
            "Look straight ahead",
        )
        started = self._clock()
        deadline = started + 30.0
        try:
            engine = self._engine_factory()
            camera = self._camera_factory()
            self._emit("ScanState", ("enrolling", "Look at the camera"))
            last_capture = 0.0

            while not cancel.is_set() and self._clock() < deadline and len(collected) < target_samples:
                ok, frame = camera.read()
                if not ok:
                    raise FaceEngineError("Camera stopped returning frames.")
                observations = engine.observe(frame)
                now = self._clock()
                if len(observations) != 1:
                    self._emit("ScanState", ("enrolling", "Ensure single face is centered"))
                    time.sleep(0.06)
                    continue

                obs = observations[0]
                box = _normalized_frame(obs, frame)
                self._emit("ScanFrame", box)

                idx = len(collected)
                pose_text = poses[idx] if idx < len(poses) else "Look straight ahead"
                self._emit("EnrollProgress", (idx, target_samples, pose_text))
                self._emit("ScanState", ("enrolling", f"Step {idx + 1}/{target_samples}: {pose_text}"))

                if now - last_capture >= 0.5:
                    collected.append(obs.embedding)
                    last_capture = now
                    self._emit("EnrollProgress", (len(collected), target_samples, "Captured"))

                time.sleep(0.04)

            if cancel.is_set():
                self._emit("EnrollComplete", (False, "Enrollment cancelled."))
            elif len(collected) >= target_samples:
                engine.save_enrollment(
                    collected,
                    path=self._enrollment_path,
                    replace=True,
                )
                self._emit("EnrollComplete", (True, f"Enrolled {target_samples} samples successfully."))
                self._emit("ScanState", ("matched", "Face enrollment saved!"))
            else:
                self._emit("EnrollComplete", (False, "Enrollment timed out."))
                self._emit("ScanState", ("not_recognized", "Enrollment timed out."))
        except Exception as error:
            logger.error("Enrollment error: %s", error)
            self._emit("EnrollComplete", (False, f"Enrollment error: {error}"))
            self._emit("ScanState", ("not_recognized", str(error)))
        finally:
            if camera is not None:
                camera.release()
            with self._lock:
                if self._cancel is cancel:
                    self._active = False
                    self._cancel = None
                    self._thread = None

    def _scan_worker(self, cancel: threading.Event, is_test: bool = False) -> None:
        started = self._clock()
        deadline = started + MAX_SCAN_SECONDS
        camera = None
        success = False
        message = "Face not recognized."
        best_score = 0.0
        streak = 0
        challenge_passed = not (self._challenge_enabled and not is_test)
        next_frame_signal = started
        last_state: tuple[str, str] | None = None

        def emit_state(state: str, text: str) -> None:
            nonlocal last_state
            value = (state, text)
            if value != last_state:
                self._emit("ScanState", value)
                last_state = value

        try:
            engine = self._engine_factory()
            enrolled = None
            if self._enrollment_path.is_file():
                enrolled = engine.load_enrollment(self._enrollment_path)
            elif not is_test:
                raise FaceEngineError("No face enrollment exists.")

            if cancel.is_set():
                message = "Scan stopped."
            elif self._clock() >= deadline:
                message = "Face not recognized. Enter your password." if not is_test else "Test scan timed out."
            else:
                camera = self._camera_factory()
                emit_state("scanning", "Look toward the camera")
                while not cancel.is_set() and self._clock() < deadline:
                    ok, frame = camera.read()
                    if not ok:
                        raise FaceEngineError("Camera stopped returning frames.")
                    if self._clock() >= deadline:
                        break
                    observations = engine.observe(frame)
                    if len(observations) != 1:
                        streak = 0
                        emit_state(
                            "no_face",
                            "No single face detected; look toward the camera.",
                        )
                        continue

                    observation = observations[0]
                    box = _normalized_frame(observation, frame)
                    accepted_match = False
                    if box[3] < MIN_FACE_HEIGHT:
                        streak = 0
                        emit_state("move_closer", "Move closer to the camera.")
                    elif not challenge_passed:
                        streak = 0
                        if _detect_turn_left(box[4]):
                            challenge_passed = True
                            emit_state("scanning", "Challenge verified. Look forward.")
                        else:
                            emit_state("challenge", "Turn head slightly to the left.")
                    else:
                        if enrolled is not None:
                            matched, score = engine.match(
                                observation.embedding, enrolled, self._threshold)
                            best_score = max(best_score, score)
                            if matched:
                                streak += 1
                            else:
                                streak = 0
                            emit_state("scanning", "Keep still while your face is checked.")
                            accepted_match = streak >= MATCH_STREAK_REQUIRED
                        else:
                            # Test scan with no enrollment
                            streak += 1
                            best_score = 1.0
                            accepted_match = streak >= MATCH_STREAK_REQUIRED
                            emit_state("scanning", "Face detected (no enrollment saved).")

                    now = self._clock()
                    if now >= deadline:
                        break
                    if accepted_match:
                        with self._lock:
                            if is_test:
                                success = not cancel.is_set()
                            else:
                                success = self._locked and not cancel.is_set()
                    if success:
                        message = "Face recognized." if (enrolled is not None or not is_test) else "Camera and face detection working."
                        break
                    if now >= next_frame_signal:
                        self._emit("ScanFrame", box)
                        next_frame_signal = now + FRAME_SIGNAL_INTERVAL

                if cancel.is_set():
                    message = "Scan stopped."
                elif not success:
                    message = "Face not recognized. Enter your password." if not is_test else "Test scan: face not recognized."
        except (FaceEngineError, OSError) as error:
            message = f"Face scan unavailable: {error}"
            emit_state("not_recognized", message)
        finally:
            if camera is not None:
                camera.release()
            if success:
                emit_state("matched", message)
            else:
                emit_state("not_recognized", message)
            self._emit("ScanResult", (success, best_score))
            with self._lock:
                if self._cancel is cancel:
                    self._active = False
                    self._cancel = None
                    self._thread = None


class FaceScanDBusService:
    def __init__(self, controller: FaceScanController | None = None):
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        self._gio = Gio
        self._glib = GLib
        self._connection = None
        self._owner_id = 0
        self._registration_id = 0
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        self.controller = (
            controller if controller is not None
            else FaceScanController(self._queue_signal)
        )

    def start(self) -> None:
        if self._owner_id:
            return
        self._owner_id = self._gio.bus_own_name(
            self._gio.BusType.SESSION,
            BUS_NAME,
            self._gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            self._on_name_acquired,
            self._on_name_lost,
        )

    def _on_bus_acquired(self, connection, _name: str) -> None:
        self._connection = connection
        self._registration_id = connection.register_object(
            OBJECT_PATH,
            self._node_info.interfaces[0],
            self._on_method_call,
            None,
            None,
        )

    def _on_name_acquired(self, _connection, _name: str) -> None:
        logger.info("Face scan D-Bus service acquired %s", BUS_NAME)

    def _on_name_lost(self, _connection, name: str) -> None:
        logger.error("Could not own face scan D-Bus name %s", name)

    def _on_method_call(
        self,
        _connection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        parameters,
        invocation,
    ) -> None:
        try:
            if method_name == "StartScan":
                self.controller.start_scan()
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "StopScan":
                self.controller.stop_scan()
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "TestScan":
                self.controller.start_test_scan()
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "StartEnroll":
                self.controller.start_enroll()
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "Reset":
                result = self.controller.reset()
                invocation.return_value(self._glib.Variant("(b)", (result,)))
            elif method_name == "GetStatus":
                status = self.controller.get_status()
                invocation.return_value(self._glib.Variant("(bibdb)", status))
            elif method_name == "SetThreshold":
                (threshold,) = parameters.unpack()
                self.controller.set_threshold(threshold)
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "SetEnabled":
                (enabled,) = parameters.unpack()
                self.controller.set_enabled(enabled)
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "SetChallenge":
                (enabled,) = parameters.unpack()
                self.controller.set_challenge(enabled)
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "SetLocked":
                (locked,) = parameters.unpack()
                self.controller.set_locked(locked)
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "UserActivity":
                self.controller.user_activity()
                invocation.return_value(self._glib.Variant("()", ()))
            else:
                invocation.return_dbus_error(
                    "org.linuxnotch.FaceDaemon.Error.UnknownMethod",
                    f"Unknown method {method_name}",
                )
                return
        except FaceDaemonError as error:
            invocation.return_dbus_error(
                f"org.linuxnotch.FaceDaemon.Error.{error.code}", str(error))

    def _queue_signal(self, name: str, values: tuple[Any, ...]) -> None:
        self._glib.idle_add(self._emit_signal, name, values)

    def _emit_signal(self, name: str, values: tuple[Any, ...]) -> bool:
        if self._connection is None:
            return self._glib.SOURCE_REMOVE
        signatures = {
            "ScanState": "(ss)",
            "ScanFrame": "(dddda(dd))",
            "ScanResult": "(bd)",
            "EnrollProgress": "(iis)",
            "EnrollComplete": "(bs)",
        }
        try:
            self._connection.emit_signal(
                None,
                OBJECT_PATH,
                INTERFACE,
                name,
                self._glib.Variant(signatures[name], values),
            )
        except (KeyError, self._glib.Error) as error:
            logger.error("Could not emit face scan signal %s: %s", name, error)
        return self._glib.SOURCE_REMOVE

    def stop(self) -> None:
        self.controller.close()
        if self._connection is not None and self._registration_id:
            self._connection.unregister_object(self._registration_id)
        self._registration_id = 0
        self._connection = None
        if self._owner_id:
            self._gio.bus_unown_name(self._owner_id)
            self._owner_id = 0


def run_daemon() -> None:
    import signal

    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    service = FaceScanDBusService()
    loop = GLib.MainLoop()
    service.start()
    signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(loop.quit))
    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(loop.quit))
    try:
        loop.run()
    finally:
        service.stop()
