import unittest
from unittest.mock import Mock

from gi.repository import GObject

from linux_notch.services.mpris import (
    OBJECT_PATH,
    PLAYER_IFACE,
    SPOTIFY_BUS_NAME,
    MprisService,
    Player,
)


class SpotifyMprisTests(unittest.TestCase):
    def setUp(self):
        self.service = MprisService.__new__(MprisService)
        GObject.Object.__init__(self.service)
        self.service._players = {
            SPOTIFY_BUS_NAME: Player(SPOTIFY_BUS_NAME),
        }
        self.service._bus = Mock()

    def test_spotify_controls_target_its_mpris_name(self):
        self.service.play_pause_for(SPOTIFY_BUS_NAME)
        self.service.next_for(SPOTIFY_BUS_NAME)
        self.service.previous_for(SPOTIFY_BUS_NAME)

        calls = self.service._bus.call.call_args_list
        self.assertEqual([call.args[0] for call in calls],
                         [SPOTIFY_BUS_NAME] * 3)
        self.assertEqual([call.args[1] for call in calls],
                         [OBJECT_PATH] * 3)
        self.assertEqual([call.args[2] for call in calls],
                         [PLAYER_IFACE] * 3)
        self.assertEqual([call.args[3] for call in calls],
                         ["PlayPause", "Next", "Previous"])
        self.assertTrue(all(call.args[9] for call in calls))

    def test_spotify_player_lookup_is_independent_of_active_player(self):
        other = Player("org.mpris.MediaPlayer2.vlc")
        self.service.active = other

        self.assertIs(
            self.service.spotify_player,
            self.service._players[SPOTIFY_BUS_NAME],
        )


if __name__ == "__main__":
    unittest.main()
