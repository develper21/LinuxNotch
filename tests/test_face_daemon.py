import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from linux_notch.services.face_daemon import (  # noqa: E402
    INTROSPECTION_XML,
    FaceDaemonError,
    FaceScanController,
)


class FakeFrame:
    shape = (720, 1280, 3)

    def __init__(self, faces):
        self.faces = faces


class FakeCamera:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.released = False
        self.read_count = 0

    def read(self):
        self.read_count += 1
        try:
            return True, next(self.frames)
        except StopIteration:
            return False, None

    def release(self):
        self.released = True


class DeferredThread:
    def __init__(self, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        return None

    def run(self):
        self.target(*self.args)


class FakeEngine:
    def load_enrollment(self, _path):
        return ["enrolled"]

    def observe(self, frame):
        return frame.faces

    def match(self, embedding, _enrolled, _threshold):
        return embedding, 0.8 if embedding else 0.2


def observation(matched=True):
    return SimpleNamespace(
        embedding=matched,
        box=(128.0, 72.0, 320.0, 360.0),
        landmarks=((180.0, 180.0), (300.0, 180.0), (240.0, 240.0),
                   (190.0, 300.0), (290.0, 300.0)),
    )


def make_controller(frames, *, enrollment_exists=True, clock=lambda: 0.0):
    directory = tempfile.TemporaryDirectory()
    enrollment = Path(directory.name) / "embeddings.npy"
    if enrollment_exists:
        enrollment.touch()
    cameras = []
    events = []

    def open_camera():
        camera = FakeCamera(frames)
        cameras.append(camera)
        return camera

    controller = FaceScanController(
        lambda name, values: events.append((name, values)),
        engine_factory=FakeEngine,
        camera_factory=open_camera,
        enrollment_path=enrollment,
        clock=clock,
        thread_factory=DeferredThread,
    )
    return directory, controller, cameras, events


class FaceScanControllerTests(unittest.TestCase):
    def test_scanning_requires_lock_and_enrollment_before_camera_access(self):
        directory, controller, cameras, _events = make_controller(
            [], enrollment_exists=False)
        self.addCleanup(directory.cleanup)
        with self.assertRaisesRegex(FaceDaemonError, "only on the lock screen"):
            controller.start_scan()
        controller.set_locked(True)
        with self.assertRaisesRegex(FaceDaemonError, "No face enrollment"):
            controller.start_scan()
        self.assertEqual(cameras, [])

    def test_success_requires_three_consecutive_matching_frames(self):
        frames = [
            FakeFrame([observation(True)]),
            FakeFrame([observation(True)]),
            FakeFrame([observation(False)]),
            FakeFrame([observation(True)]),
            FakeFrame([observation(True)]),
            FakeFrame([observation(True)]),
        ]
        directory, controller, cameras, events = make_controller(frames)
        self.addCleanup(directory.cleanup)
        controller.set_locked(True)
        controller.start_scan()
        self.assertEqual(cameras, [])
        controller._thread.run()

        results = [values for name, values in events if name == "ScanResult"]
        self.assertEqual(results, [(True, 0.8)])
        self.assertEqual(cameras[0].read_count, 6)
        self.assertTrue(cameras[0].released)
        scan_frame = next(values for name, values in events if name == "ScanFrame")
        for actual, expected in zip(scan_frame[:4], (0.1, 0.1, 0.25, 0.5)):
            self.assertAlmostEqual(actual, expected)
        expected_landmarks = (
            (180 / 1280, 180 / 720), (300 / 1280, 180 / 720),
            (240 / 1280, 240 / 720), (190 / 1280, 300 / 720),
            (290 / 1280, 300 / 720),
        )
        for actual, expected in zip(scan_frame[4], expected_landmarks):
            self.assertAlmostEqual(actual[0], expected[0])
            self.assertAlmostEqual(actual[1], expected[1])
        self.assertEqual(events[-2], ("ScanState", ("matched", "Face recognized.")))

    def test_three_attempts_need_explicit_user_activity_to_rearm(self):
        frames = [FakeFrame([])]
        directory, controller, cameras, events = make_controller(frames)
        self.addCleanup(directory.cleanup)
        controller.set_locked(True)

        for _ in range(3):
            controller.start_scan()
            controller._thread.run()
        with self.assertRaisesRegex(FaceDaemonError, "Three scan attempts"):
            controller.start_scan()

        controller.user_activity()
        controller.start_scan()
        controller._thread.run()
        self.assertEqual(len(cameras), 4)
        self.assertTrue(all(camera.released for camera in cameras))
        self.assertEqual(
            sum(name == "ScanResult" for name, _values in events), 4)

    def test_unlock_cancels_scan_before_opening_camera(self):
        directory, controller, cameras, events = make_controller(
            [FakeFrame([observation()])])
        self.addCleanup(directory.cleanup)
        controller.set_locked(True)
        controller.start_scan()
        controller.set_locked(False)
        controller._thread.run()

        self.assertEqual(cameras, [])
        self.assertFalse(controller.active)
        self.assertEqual(events[-1], ("ScanResult", (False, 0.0)))

    def test_scan_window_expires_without_extending_past_deadline(self):
        times = iter((0.0, 0.0, 0.0, 8.1))
        directory, controller, cameras, events = make_controller(
            [FakeFrame([]), FakeFrame([])],
            clock=lambda: next(times),
        )
        self.addCleanup(directory.cleanup)
        controller.set_locked(True)
        controller.start_scan()
        controller._thread.run()

        self.assertEqual(cameras[0].read_count, 1)
        self.assertEqual(events[-1], ("ScanResult", (False, 0.0)))

    def test_test_scan_succeeds_without_screen_lock(self):
        frames = [
            FakeFrame([observation(True)]),
            FakeFrame([observation(True)]),
            FakeFrame([observation(True)]),
        ]
        directory, controller, cameras, events = make_controller(frames)
        self.addCleanup(directory.cleanup)
        # Verify controller is not locked
        self.assertFalse(controller._locked)
        controller.start_test_scan()
        controller._thread.run()

        results = [values for name, values in events if name == "ScanResult"]
        self.assertEqual(results, [(True, 0.8)])
        self.assertTrue(cameras[0].released)

    def test_get_status_and_setters(self):
        directory, controller, _cameras, _events = make_controller([])
        self.addCleanup(directory.cleanup)

        is_enrolled, count, enabled, threshold, challenge = controller.get_status()
        self.assertTrue(is_enrolled)
        self.assertTrue(enabled)
        self.assertEqual(threshold, 0.45)
        self.assertFalse(challenge)

        controller.set_threshold(0.60)
        controller.set_enabled(False)
        controller.set_challenge(True)
        status = controller.get_status()
        self.assertEqual(status[2], False)
        self.assertEqual(status[3], 0.60)
        self.assertEqual(status[4], True)

        with self.assertRaises(FaceDaemonError):
            controller.set_threshold(1.5)

    def test_reset_unlinks_enrollment(self):
        directory, controller, _cameras, _events = make_controller([])
        self.addCleanup(directory.cleanup)
        self.assertTrue(controller._enrollment_path.exists())

        res = controller.reset()
        self.assertTrue(res)
        self.assertFalse(controller._enrollment_path.exists())
        self.assertFalse(controller.get_status()[0])

    def test_challenge_requires_head_turn_before_match(self):
        # Normal observation: eyes at 180, 300, nose at 240 (midpoint is 240, offset is 0)
        # Turned observation: eyes at 180, 300, nose at 285 (offset > 0.2)
        turned_obs = SimpleNamespace(
            embedding=True,
            box=(128.0, 72.0, 320.0, 360.0),
            landmarks=((180.0, 180.0), (300.0, 180.0), (285.0, 240.0),
                       (190.0, 300.0), (290.0, 300.0)),
        )
        frames = [
            FakeFrame([observation(True)]),
            FakeFrame([turned_obs]),
            FakeFrame([observation(True)]),
            FakeFrame([observation(True)]),
            FakeFrame([observation(True)]),
        ]
        directory, controller, cameras, events = make_controller(frames)
        self.addCleanup(directory.cleanup)
        controller.set_locked(True)
        controller.set_challenge(True)
        controller.start_scan()
        controller._thread.run()

        results = [values for name, values in events if name == "ScanResult"]
        self.assertEqual(results, [(True, 0.8)])
        self.assertTrue(any(v == ("challenge", "Turn head slightly to the left.") for n, v in events if n == "ScanState"))
        self.assertTrue(any("Challenge verified" in v[1] for n, v in events if n == "ScanState"))


class FaceScanDBusSchemaTests(unittest.TestCase):
    def test_dbus_interface_has_methods_and_expected_signal_types(self):
        interface = Gio.DBusNodeInfo.new_for_xml(
            INTROSPECTION_XML).interfaces[0]
        self.assertIsNotNone(interface.lookup_method("StartScan"))
        self.assertIsNotNone(interface.lookup_method("StopScan"))
        self.assertIsNotNone(interface.lookup_method("TestScan"))
        self.assertIsNotNone(interface.lookup_method("StartEnroll"))
        self.assertIsNotNone(interface.lookup_method("Reset"))
        self.assertIsNotNone(interface.lookup_method("GetStatus"))
        self.assertIsNotNone(interface.lookup_method("SetThreshold"))
        self.assertIsNotNone(interface.lookup_method("SetEnabled"))
        self.assertIsNotNone(interface.lookup_method("SetChallenge"))
        self.assertIsNotNone(interface.lookup_method("SetLocked"))
        self.assertIsNotNone(interface.lookup_method("UserActivity"))
        self.assertEqual(
            interface.lookup_signal("ScanFrame").args[-1].signature,
            "a(dd)",
        )
        self.assertEqual(
            interface.lookup_signal("EnrollProgress").args[0].signature,
            "i",
        )
        self.assertEqual(
            interface.lookup_signal("EnrollComplete").args[0].signature,
            "b",
        )
        frame_variant = GLib.Variant(
            "(dddda(dd))",
            (0.1, 0.2, 0.3, 0.4, ((0.15, 0.25),) * 5),
        )
        self.assertEqual(frame_variant.get_type_string(), "(dddda(dd))")


if __name__ == "__main__":
    unittest.main()
