"""Local clipboard history backed by SQLite and bounded PNG files."""

from __future__ import annotations

import os
import hashlib
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Iterator

from gi.repository import Gdk, GLib, GObject

MAX_ITEMS = 50
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TEXT_BYTES = 1024 * 1024
DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "linux-notch",
    "clipboard",
)


@dataclass(frozen=True)
class ClipboardItem:
    id: int
    kind: str
    content: str
    created: float
    pinned: bool


class ClipboardHistoryService(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, clipboard=None, storage_dir: str = DATA_DIR,
                 max_items: int = MAX_ITEMS,
                 max_image_bytes: int = MAX_IMAGE_BYTES):
        super().__init__()
        self.clipboard = clipboard
        self.storage_dir = storage_dir
        self.max_items = max_items
        self.max_image_bytes = max_image_bytes
        self._changed_handler = 0
        self._change_serial = 0

    @property
    def recording(self) -> bool:
        return bool(self._changed_handler)

    def set_recording(self, enabled: bool):
        if enabled == self.recording:
            return
        if enabled:
            if self.clipboard is None:
                raise RuntimeError("Clipboard is unavailable on this display")
            self._ensure_schema()
            self._changed_handler = self.clipboard.connect(
                "changed", self._on_clipboard_changed)
        else:
            self.clipboard.disconnect(self._changed_handler)
            self._changed_handler = 0
            self._change_serial += 1

    def list_items(self) -> list[ClipboardItem]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, kind, content, created, pinned "
                "FROM items ORDER BY pinned DESC, created DESC, id DESC"
            ).fetchall()
        return [ClipboardItem(
            id=row[0], kind=row[1], content=row[2],
            created=row[3], pinned=bool(row[4]),
        ) for row in rows]

    def record_text(self, text: str) -> bool:
        if not text:
            return False
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            self.emit("error", "Clipboard text exceeds the 1 MiB limit.")
            return False
        return self._insert("text", text)

    def record_texture(self, texture: Gdk.Texture) -> bool:
        byte_size = texture.get_width() * texture.get_height() * 4
        if byte_size > self.max_image_bytes:
            self.emit("error", "Clipboard image exceeds the size limit.")
            return False
        os.makedirs(self.storage_dir, mode=0o700, exist_ok=True)
        os.chmod(self.storage_dir, 0o700)
        path = os.path.join(self.storage_dir, f"{uuid.uuid4().hex}.png")
        if not texture.save_to_png(path):
            if os.path.exists(path):
                os.unlink(path)
            self.emit("error", "Could not save clipboard image.")
            return False
        try:
            os.chmod(path, 0o600)
            if os.path.getsize(path) > self.max_image_bytes:
                os.unlink(path)
                self.emit("error", "Clipboard image exceeds the size limit.")
                return False
            with open(path, "rb") as image_file:
                fingerprint = hashlib.sha256(image_file.read()).hexdigest()
            inserted = self._insert("image", path, fingerprint)
        except (OSError, sqlite3.Error):
            if os.path.exists(path):
                os.unlink(path)
            raise
        if not inserted:
            os.unlink(path)
        return inserted

    def set_pinned(self, item_id: int, pinned: bool):
        with self._connect() as db:
            db.execute(
                "UPDATE items SET pinned = ? WHERE id = ?",
                (int(pinned), item_id),
            )
        self.emit("changed")

    def clear(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT content FROM items WHERE kind = 'image'"
            ).fetchall()
            db.execute("DELETE FROM items")
        self.emit("changed")
        db_path = os.path.join(self.storage_dir, "history.sqlite3")
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("VACUUM")
        for (path,) in rows:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError as error:
                self.emit("error", str(error))

    def _insert(self, kind: str, content: str,
                fingerprint: str | None = None) -> bool:
        fingerprint = fingerprint or content
        now = time.time()
        stale_images = []
        with self._connect() as db:
            previous = db.execute(
                "SELECT kind, fingerprint FROM items "
                "ORDER BY created DESC, id DESC LIMIT 1"
            ).fetchone()
            if previous == (kind, fingerprint):
                return False
            cursor = db.execute(
                "INSERT INTO items "
                "(kind, content, fingerprint, created, pinned) "
                "VALUES (?, ?, ?, ?, 0)",
                (kind, content, fingerprint, now),
            )
            item_id = cursor.lastrowid
            stale = db.execute(
                "SELECT id, kind, content FROM items "
                "WHERE id NOT IN ("
                "  SELECT id FROM items "
                "  ORDER BY pinned DESC, created DESC, id DESC LIMIT ?"
                ")",
                (self.max_items,),
            ).fetchall()
            for old_id, old_kind, old_content in stale:
                db.execute("DELETE FROM items WHERE id = ?", (old_id,))
                if old_kind == "image":
                    stale_images.append(old_content)
        for path in stale_images:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError as error:
                self.emit("error", str(error))
        self.emit("changed")
        return item_id is not None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._ensure_schema()
        db = sqlite3.connect(os.path.join(self.storage_dir, "history.sqlite3"))
        try:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA secure_delete = ON")
            yield db
            db.commit()
        except sqlite3.Error:
            db.rollback()
            raise
        finally:
            db.close()

    def _ensure_schema(self):
        os.makedirs(self.storage_dir, mode=0o700, exist_ok=True)
        os.chmod(self.storage_dir, 0o700)
        path = os.path.join(self.storage_dir, "history.sqlite3")
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS items ("
                "id INTEGER PRIMARY KEY, "
                "kind TEXT NOT NULL CHECK(kind IN ('text', 'image')), "
                "content TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, "
                "created REAL NOT NULL, "
                "pinned INTEGER NOT NULL DEFAULT 0)"
            )
            db.commit()
        os.chmod(path, 0o600)

    def _on_clipboard_changed(self, clipboard):
        if not self.recording:
            return
        self._change_serial += 1
        try:
            clipboard.read_text_async(
                None, self._on_text_read, self._change_serial)
        except GLib.Error as error:
            self.emit("error", str(error))

    def _on_text_read(self, clipboard, result, serial):
        if serial != self._change_serial or not self.recording:
            return
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            text = None
        if text is not None:
            try:
                if self.record_text(text):
                    return
                if text:
                    return
            except (OSError, sqlite3.Error) as error:
                self.emit("error", str(error))
                return
        try:
            clipboard.read_texture_async(
                None, self._on_texture_read, serial)
        except GLib.Error as error:
            self.emit("error", str(error))

    def _on_texture_read(self, clipboard, result, serial):
        if serial != self._change_serial or not self.recording:
            return
        try:
            texture = clipboard.read_texture_finish(result)
            if texture is not None:
                self.record_texture(texture)
        except (GLib.Error, OSError, sqlite3.Error) as error:
            self.emit("error", str(error))
