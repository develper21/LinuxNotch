"""Optional VTE-backed interactive shell page."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte
except (ImportError, ValueError):
    Vte = None

from gi.repository import Gio, Gdk, GLib, Gtk, Pango  # noqa: E402

PALETTE = (
    "#1a1a1a", "#e06c75", "#98c379", "#e5c07b",
    "#61afef", "#c678dd", "#56b6c2", "#dcdfe4",
    "#5c6370", "#e06c75", "#98c379", "#e5c07b",
    "#61afef", "#c678dd", "#56b6c2", "#ffffff",
)


def _rgba(value: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    if not color.parse(value):
        raise ValueError(f"Invalid terminal color: {value}")
    return color


def clean_environment(environ: Mapping[str, str] | None = None) -> list[str]:
    """Keep the shell independent from the Python/GTK environment of the app."""
    env = dict(os.environ if environ is None else environ)
    virtual_env = env.pop("VIRTUAL_ENV", None)
    for key in ("PYTHONPATH", "PYTHONHOME", "GDK_BACKEND"):
        env.pop(key, None)

    if virtual_env:
        venv_bin = os.path.realpath(os.path.join(virtual_env, "bin"))
        env["PATH"] = os.pathsep.join(
            entry for entry in env.get("PATH", os.defpath).split(os.pathsep)
            if os.path.realpath(entry or os.curdir) != venv_bin
        )
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    return [f"{key}={value}" for key, value in env.items()]


class TerminalPage(Gtk.Box):
    """A persistent terminal page; its shell starts on first visit."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("terminal-page")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._pid: int | None = None
        self._last_spawn = 0.0
        self._spawned = False
        self._spawn_pending = False

        if Vte is None:
            label = Gtk.Label(
                label=(
                    "Terminal needs VTE for GTK 4.\n"
                    "Debian/Ubuntu: sudo apt install gir1.2-vte-3.91 "
                    "libvte-2.91-gtk4-0\n"
                    "Arch: sudo pacman -S vte4"
                ),
                wrap=True,
                justify=Gtk.Justification.CENTER,
            )
            label.add_css_class("terminal-unavailable")
            label.set_margin_top(24)
            label.set_margin_bottom(24)
            label.set_margin_start(24)
            label.set_margin_end(24)
            self.append(label)
            self.term = None
            return

        self.term = Vte.Terminal()
        self.term.set_scrollback_lines(5000)
        self.term.set_font(Pango.FontDescription("Monospace 11"))
        self.term.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
        self.term.set_colors(
            _rgba("#e6e6e6"),
            _rgba("#101114"),
            [_rgba(color) for color in PALETTE],
        )
        self.term.set_size_request(640, 320)
        self.term.set_hexpand(True)
        self.term.set_vexpand(True)
        self.term.connect("child-exited", self._on_exit)

        key = Gtk.EventControllerKey()
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", self._on_key)
        self.term.add_controller(key)
        self.append(self.term)

    def on_show(self) -> None:
        if self.term is None:
            return
        if not self._spawned:
            self._spawn()
        GLib.idle_add(self._grab_focus)

    def _grab_focus(self) -> bool:
        if self.term is not None:
            self.term.grab_focus()
        return GLib.SOURCE_REMOVE

    def _spawn(self) -> None:
        if self.term is None or self._spawned or self._spawn_pending:
            return
        self._last_spawn = time.monotonic()
        shell = os.environ.get("SHELL", "/bin/bash")
        self._spawn_pending = True
        try:
            self.term.spawn_async(
                pty_flags=Vte.PtyFlags.DEFAULT,
                working_directory=os.path.expanduser("~"),
                argv=[shell],
                envv=clean_environment(),
                spawn_flags=GLib.SpawnFlags.DEFAULT,
                child_setup=None,
                timeout=-1,
                cancellable=Gio.Cancellable(),
                callback=self._on_spawned,
                user_data=None,
            )
        except GLib.Error as error:
            self._spawn_pending = False
            self._write_message(f"Could not start shell: {error}")

    def _on_spawned(self, _term, pid, error, *_args) -> None:
        self._spawn_pending = False
        if error is not None:
            self._pid = None
            self._spawned = False
            self._write_message(f"Could not start shell: {error}")
            return
        self._pid = pid
        self._spawned = True

    def _on_exit(self, _term, _status) -> None:
        self._pid = None
        self._spawned = False
        self._spawn_pending = False
        if time.monotonic() - self._last_spawn < 1.0:
            self._write_message(
                "Shell exited immediately; automatic restart was skipped.")
            return
        self._write_message("Shell exited. Starting a new shell...")
        GLib.timeout_add(300, self._restart_shell)

    def _restart_shell(self) -> bool:
        self._spawn()
        return GLib.SOURCE_REMOVE

    def _write_message(self, message: str) -> None:
        if self.term is not None:
            self.term.feed(f"\r\n[Linux Notch: {message}]\r\n".encode())

    def _on_key(self, _controller, keyval, _keycode, state, *_args) -> bool:
        if self.term is None:
            return False
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and shift and keyval in (Gdk.KEY_C, Gdk.KEY_c):
            self.term.copy_clipboard_format(Vte.Format.TEXT)
            return True
        if ctrl and shift and keyval in (Gdk.KEY_V, Gdk.KEY_v):
            self.term.paste_clipboard()
            return True
        if ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
            self.term.set_font_scale(self.term.get_font_scale() + 0.1)
            return True
        if ctrl and keyval == Gdk.KEY_minus:
            self.term.set_font_scale(max(0.5, self.term.get_font_scale() - 0.1))
            return True
        if ctrl and keyval == Gdk.KEY_0:
            self.term.set_font_scale(1.0)
            return True
        return False
