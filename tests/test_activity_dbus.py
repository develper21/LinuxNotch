import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    Gio = GLib = None

from linux_notch.activity.dbus_service import BUS_NAME, ActivityDBusService


@unittest.skipUnless(
    Gio is not None and os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    "requires PyGObject and a session D-Bus",
)
class ActivityDBusTests(unittest.TestCase):
    def test_notchctl_start_update_end_across_processes(self):
        service = ActivityDBusService()
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        loop = GLib.MainLoop()
        errors = []
        activity_ids = []
        watch_id = 0
        timed_out = False

        def run_cli():
            try:
                with tempfile.TemporaryDirectory(prefix="linux-notch-test-") as directory:
                    activity_file = Path(directory) / "activity.json"
                    activity_file.write_text(
                        '{"schema":1,"app":"integration-test","title":"Build",'
                        '"state":"running","progress":{"done":1,"total":2}}',
                        encoding="utf-8",
                    )
                    start = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "linux_notch.tools.notchctl",
                            "activity",
                            "start",
                            "--file",
                            str(activity_file),
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    activity_id = start.stdout.strip()
                    activity_ids.append(activity_id)
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "linux_notch.tools.notchctl",
                            "activity",
                            "update",
                            activity_id,
                            "--progress",
                            "2/2",
                            "--state",
                            "complete",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "linux_notch.tools.notchctl",
                            "activity",
                            "end",
                            activity_id,
                            "--state",
                            "success",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
            finally:
                GLib.idle_add(lambda: (loop.quit(), False)[1])

        def on_name_appeared(_connection, _name, _owner):
            threading.Thread(target=run_cli, daemon=True).start()

        def on_timeout():
            nonlocal timed_out
            timed_out = True
            loop.quit()
            return False

        try:
            service.start()
            watch_id = Gio.bus_watch_name_on_connection(
                connection,
                BUS_NAME,
                Gio.BusNameWatcherFlags.NONE,
                on_name_appeared,
                lambda *_args: None,
            )
            GLib.timeout_add_seconds(8, on_timeout)
            loop.run()
        finally:
            if watch_id:
                Gio.bus_unwatch_name(watch_id)
            service.stop()

        self.assertFalse(timed_out, "Activity API CLI requests timed out")
        self.assertFalse(errors, "; ".join(errors))
        self.assertEqual(len(activity_ids), 1)
        self.assertEqual(service.store.list_active(), [])


if __name__ == "__main__":
    unittest.main()
