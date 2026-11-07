import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from linux_notch.services import sounds


class SoundTests(unittest.TestCase):
    def test_all_named_sound_assets_are_bundled(self):
        files = {path.stem for path in sounds._SOUND_DIR.glob("*.wav")}
        self.assertEqual(files, set(sounds.SOUND_NAMES))
        self.assertEqual(len(files), 29)

    @patch("linux_notch.services.sounds.subprocess.Popen")
    def test_plays_sound_with_configured_volume(self, popen):
        played = sounds.play_sound(
            "finish",
            {"sound_enabled": True, "sound_volume": 0.25},
            player="/usr/bin/paplay",
        )
        self.assertTrue(played)
        args, kwargs = popen.call_args
        self.assertEqual(args[0][:3], ["/usr/bin/paplay", "--volume", "16384"])
        self.assertEqual(Path(args[0][3]).name, "finish.wav")
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    @patch("linux_notch.services.sounds.subprocess.Popen")
    def test_disabled_or_silent_effects_do_not_spawn_a_player(self, popen):
        self.assertFalse(sounds.play_sound(
            "pop", {"sound_enabled": False}, player="/usr/bin/paplay"))
        self.assertFalse(sounds.play_sound(
            "pop", {"sound_enabled": True, "sound_volume": 0}, player="/usr/bin/paplay"))
        popen.assert_not_called()

    def test_unknown_sound_name_is_rejected(self):
        with self.assertRaises(ValueError):
            sounds.play_sound("not-a-sound", {})


if __name__ == "__main__":
    unittest.main()
