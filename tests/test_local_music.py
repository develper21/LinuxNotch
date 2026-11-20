import os
import tempfile
import unittest
from unittest.mock import patch

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from linux_notch.services import local_music  # noqa: E402
from linux_notch.services.local_music import (  # noqa: E402
    SUPPORTED_AUDIO_EXTENSIONS,
    scan_music_directory,
)


class LocalMusicLibraryTests(unittest.TestCase):
    def test_scans_supported_audio_recursively_in_case_insensitive_order(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "Album"))
            for name in ("zeta.MP3", "Album/alpha.flac", "notes.txt"):
                with open(os.path.join(directory, name), "wb"):
                    pass

            tracks = scan_music_directory(directory)

        self.assertEqual(
            [track.title for track in tracks],
            ["alpha", "zeta"],
        )
        self.assertTrue(all(track.path.startswith(directory) for track in tracks))

    def test_missing_music_directory_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing")

            with self.assertRaises(NotADirectoryError):
                scan_music_directory(missing)

    def test_scanner_finds_case_insensitive_sibling_cover_art(self):
        with tempfile.TemporaryDirectory() as directory:
            track_path = os.path.join(directory, "song.mp3")
            cover_path = os.path.join(directory, "COVER.JPG")
            for path in (track_path, cover_path):
                with open(path, "wb"):
                    pass

            tracks = scan_music_directory(directory)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].art_path, cover_path)

    def test_embedded_artwork_is_cached_from_gstreamer_tags(self):
        if local_music.Gst is None:
            self.skipTest("GStreamer is not installed")
        Gst.init(None)
        payload = b"embedded image payload"
        buffer = Gst.Buffer.new_allocate(None, len(payload), None)
        buffer.fill(0, payload)
        sample = Gst.Sample.new(
            buffer, Gst.Caps.from_string("image/png"), None, None)
        tags = Gst.TagList.new_empty()
        tags.add_value(Gst.TagMergeMode.REPLACE, Gst.TAG_IMAGE, sample)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(local_music.config, "CACHE_DIR", directory):
                artwork_path = local_music._save_embedded_artwork(
                    "/music/song.mp3", tags)
            with open(artwork_path, "rb") as artwork:
                cached_payload = artwork.read()

        self.assertTrue(artwork_path.endswith(".png"))
        self.assertEqual(cached_payload, payload)

    def test_supported_audio_extensions_include_common_local_formats(self):
        self.assertTrue({".mp3", ".flac", ".ogg", ".wav"}.issubset(
            SUPPORTED_AUDIO_EXTENSIONS))


if __name__ == "__main__":
    unittest.main()
