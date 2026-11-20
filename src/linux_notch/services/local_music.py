"""Local music library scanning and playback through GStreamer's playbin."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass

import gi

from linux_notch import config

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gio, GLib, GObject, Gst  # noqa: E402
except (ImportError, ValueError):
    from gi.repository import Gio, GLib, GObject  # noqa: E402

    Gst = None

SUPPORTED_AUDIO_EXTENSIONS = frozenset({
    ".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav",
})
ARTWORK_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
logger = logging.getLogger(__name__)


@dataclass
class MusicTrack:
    path: str
    title: str
    artist: str = ""
    album: str = ""
    art_path: str = ""
    length_us: int = 0
    status: str = "Stopped"
    can_next: bool = False
    can_prev: bool = False
    track_id: str = ""


def scan_music_directory(directory: str) -> list[MusicTrack]:
    root = os.path.abspath(os.path.expanduser(directory))
    if not os.path.isdir(root):
        raise NotADirectoryError(f"Music folder does not exist: {root}")

    tracks = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    for current, _directories, filenames in os.walk(
        root, onerror=raise_walk_error
    ):
        filenames_by_name = {
            filename.casefold(): filename for filename in filenames
        }
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                continue
            path = os.path.join(current, filename)
            title = os.path.splitext(filename)[0]
            art_path = _find_external_artwork(
                current, title, filenames_by_name)
            tracks.append(MusicTrack(
                path=path, title=title, art_path=art_path))

    tracks.sort(key=lambda track: (track.title.casefold(), track.path.casefold()))
    return tracks


def _find_external_artwork(
    directory: str,
    title: str,
    filenames_by_name: dict[str, str],
) -> str:
    candidates = [
        f"{title}{extension}" for extension in ARTWORK_EXTENSIONS
    ] + [
        f"{name}{extension}"
        for name in ("cover", "folder", "front", "album", "artwork")
        for extension in ARTWORK_EXTENSIONS
    ]
    for candidate in candidates:
        filename = filenames_by_name.get(candidate.casefold())
        if filename is not None:
            return os.path.join(directory, filename)
    return ""


def _save_embedded_artwork(track_path: str, tags) -> str:
    if Gst is None:
        return ""
    suffixes = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/x-jpeg": ".jpg",
    }
    for tag_name in (Gst.TAG_IMAGE, Gst.TAG_PREVIEW_IMAGE):
        found, sample = tags.get_sample(tag_name)
        if not found or sample is None:
            continue
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        if buffer is None or caps is None or caps.get_size() == 0:
            continue
        suffix = suffixes.get(caps.get_structure(0).get_name())
        if suffix is None:
            continue
        image_data = buffer.extract_dup(0, buffer.get_size())
        if not image_data:
            continue
        digest = hashlib.sha256(
            track_path.encode("utf-8") + image_data).hexdigest()
        artwork_dir = os.path.join(config.CACHE_DIR, "artwork")
        artwork_path = os.path.join(artwork_dir, f"{digest}{suffix}")
        if os.path.isfile(artwork_path):
            return artwork_path
        try:
            os.makedirs(artwork_dir, exist_ok=True)
            with open(artwork_path, "wb") as artwork_file:
                artwork_file.write(image_data)
        except OSError as error:
            logger.warning("Could not cache artwork for %s: %s", track_path, error)
            continue
        return artwork_path
    return ""


class LocalMusicPlayer(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "library-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "art-ready": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, directory: str):
        super().__init__()
        self.directory = os.path.abspath(os.path.expanduser(directory))
        self.tracks: list[MusicTrack] = []
        self.active_index = -1
        self._closed = False
        self._scan_generation = 0
        self._scan_thread: threading.Thread | None = None
        self._bus = None
        self.error_message = ""

        if Gst is None:
            self._player = None
            self.error_message = (
                "GStreamer is missing. Install GStreamer and its "
                "base/good audio plugins."
            )
            self.emit("error", self.error_message)
        else:
            Gst.init(None)
            self._player = Gst.ElementFactory.make(
                "playbin", "linux-notch-player")
            if self._player is None:
                self.error_message = (
                    "GStreamer playback is unavailable. Install GStreamer "
                    "and its base/good audio plugins."
                )
                self.emit("error", self.error_message)
            else:
                self._bus = self._player.get_bus()
                self._bus.add_signal_watch()
                self._bus.connect("message", self._on_bus_message)

        self.refresh_library()

    @property
    def active(self) -> MusicTrack | None:
        if 0 <= self.active_index < len(self.tracks):
            return self.tracks[self.active_index]
        return None

    def refresh_library(self) -> None:
        self._scan_generation += 1
        generation = self._scan_generation
        directory = self.directory

        def scan() -> None:
            try:
                tracks = scan_music_directory(directory)
                error = ""
            except OSError as exc:
                tracks = []
                error = str(exc)
            GLib.idle_add(self._finish_scan, generation, tracks, error)

        self._scan_thread = threading.Thread(target=scan, daemon=True)
        self._scan_thread.start()

    def _finish_scan(
        self,
        generation: int,
        tracks: list[MusicTrack],
        error: str,
    ) -> bool:
        if self._closed or generation != self._scan_generation:
            return GLib.SOURCE_REMOVE
        previous_path = self.active.path if self.active is not None else None
        self.tracks = tracks
        self.active_index = next(
            (index for index, track in enumerate(tracks)
             if track.path == previous_path),
            -1,
        )
        if not error and self._player is not None:
            self.error_message = ""
        elif error:
            self.error_message = error
        if error:
            self.emit("error", error)
        self.emit("library-changed")
        self.emit("changed")
        return GLib.SOURCE_REMOVE

    def play_index(self, index: int) -> None:
        if not 0 <= index < len(self.tracks):
            raise IndexError(f"Music track index out of range: {index}")
        if self._player is None:
            self.emit("error", self.error_message)
            return

        if self.active_index != index:
            if self.active is not None:
                self.active.status = "Stopped"
            self._player.set_state(Gst.State.NULL)
            self.active_index = index
        track = self.tracks[index]
        track.status = "Playing"
        track.can_prev = index > 0
        track.can_next = index < len(self.tracks) - 1
        track.track_id = track.path
        self._player.set_property(
            "uri", Gio.File.new_for_path(track.path).get_uri())
        result = self._player.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            track.status = "Stopped"
            self._report_error(f"Could not play {track.title}.")
        self.emit("changed")

    def play_pause(self) -> None:
        if self.active is None:
            if self.tracks:
                self.play_index(0)
            return
        if self.active.status == "Playing":
            self.pause()
        else:
            self.play_index(self.active_index)

    def pause(self) -> None:
        if self.active is None or self._player is None:
            return
        if self._player.set_state(Gst.State.PAUSED) == Gst.StateChangeReturn.FAILURE:
            self._report_error(f"Could not pause {self.active.title}.")
            return
        self.active.status = "Paused"
        self.emit("changed")

    def previous(self) -> None:
        if self.active_index > 0:
            self.play_index(self.active_index - 1)

    def next(self) -> None:
        if self.active_index + 1 < len(self.tracks):
            self.play_index(self.active_index + 1)

    def seek_to(self, position_us: int) -> None:
        if self._player is None or self.active is None:
            return
        success = self._player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            max(0, position_us) * Gst.USECOND,
        )
        if not success:
            self._report_error(f"Could not seek in {self.active.title}.")

    def get_position(self, callback) -> None:
        if self._player is None or self.active is None:
            return
        success, position = self._player.query_position(Gst.Format.TIME)
        if success:
            callback(int(position // Gst.USECOND))

    def _on_bus_message(self, _bus, message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            if self.active is not None:
                self.active.status = "Stopped"
            self._report_error(str(error))
            self.emit("changed")
        elif message.type == Gst.MessageType.EOS:
            if self.active_index + 1 < len(self.tracks):
                self.next()
            elif self.active is not None:
                self.active.status = "Stopped"
                self.emit("changed")
        elif message.type == Gst.MessageType.DURATION_CHANGED:
            self._refresh_duration()
        elif message.type == Gst.MessageType.TAG:
            self._apply_tags(message.parse_tag())
        elif message.type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._player:
                _old, new, _pending = message.parse_state_changed()
                if self.active is not None and new == Gst.State.PLAYING:
                    self.active.status = "Playing"
                    self._refresh_duration()
                    self.emit("changed")

    def _refresh_duration(self) -> None:
        if self.active is None or self._player is None:
            return
        success, duration = self._player.query_duration(Gst.Format.TIME)
        if success:
            self.active.length_us = int(duration // Gst.USECOND)

    def _apply_tags(self, tags) -> None:
        if self.active is None:
            return
        previous_art = self.active.art_path
        for tag_name, attribute in (
            (Gst.TAG_TITLE, "title"),
            (Gst.TAG_ARTIST, "artist"),
            (Gst.TAG_ALBUM, "album"),
        ):
            success, value = tags.get_string(tag_name)
            if success and value:
                setattr(self.active, attribute, value)
        embedded_art = _save_embedded_artwork(self.active.path, tags)
        if embedded_art:
            self.active.art_path = embedded_art
        if self.active.art_path != previous_art:
            self.emit("art-ready")
        self.emit("changed")

    def _report_error(self, message: str) -> None:
        self.error_message = message
        self.emit("error", message)

    def stop(self) -> None:
        self._closed = True
        self._scan_generation += 1
        if self._player is not None:
            self._player.set_state(Gst.State.NULL)
        if self._bus is not None:
            self._bus.remove_signal_watch()
            self._bus = None
