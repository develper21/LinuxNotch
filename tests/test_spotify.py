import subprocess
import unittest
from unittest.mock import patch

from linux_notch.services.spotify import spotify_installed


class SpotifyDetectionTests(unittest.TestCase):
    @patch("linux_notch.services.spotify.subprocess.run")
    @patch("linux_notch.services.spotify.shutil.which")
    def test_native_command_is_checked_first(self, which, run):
        which.side_effect = lambda name: "/usr/bin/spotify" if name == "spotify" else None

        self.assertTrue(spotify_installed())
        run.assert_not_called()

    @patch("linux_notch.services.spotify.subprocess.run")
    @patch("linux_notch.services.spotify.shutil.which")
    def test_flatpak_and_snap_installations_are_detected(self, _which, run):
        _which.side_effect = lambda name: None if name == "spotify" else "/usr/bin/tool"
        run.side_effect = [
            subprocess.CompletedProcess([], 1),
            subprocess.CompletedProcess([], 0),
        ]

        self.assertTrue(spotify_installed())
        self.assertEqual(run.call_args_list[0].args[0],
                         ["flatpak", "info", "com.spotify.Client"])
        self.assertEqual(run.call_args_list[1].args[0],
                         ["snap", "list", "spotify"])

    @patch("linux_notch.services.spotify.subprocess.run")
    @patch("linux_notch.services.spotify.shutil.which", return_value=None)
    def test_missing_installers_report_not_installed(self, _which, run):
        self.assertFalse(spotify_installed())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
