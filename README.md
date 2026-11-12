# Linux Notch

Linux Notch is a GTK4 desktop island, based on the MIT-licensed Lost Island
v1.7.2 UI and services, with a Linux desktop backend layer and a versioned
session-bus API for live activities. It is an independent Linux-only project;
the original Lost Island copyright and MIT license are retained.

## What works today

- The existing island UI and event-driven desktop services from the pinned
  upstream release.
- Runtime desktop backend selection: gtk4-layer-shell, GNOME Shell helper,
  X11/EWMH, or a documented floating-window fallback.
- Activity API schema 1 over D-Bus (`org.linuxnotch.Notch1`) and the `notchctl`
  client. Activities are per-D-Bus-client, bounded, plain-text data with
  quotas and expiration.
- Animated Mochi character moods, seasonal outfits, and 29 bundled sound
  effects. The collapsed island shows Mochi only; choose his outfit from the
  expanded Mochi feature, and configure sound volume and previews in Settings.
  The expanded island also includes clipboard history, Spotify, and a local
  ToDo list with task completion and deletion.
- Clipboard history is opt-in, local-only, and paused by default; text and
  bounded image history can be pinned, copied back, or cleared. GTK clipboard
  access depends on desktop permissions, so Wayland monitoring may be limited.
- Spotify controls use the existing MPRIS session-bus integration and need no
  Spotify developer credentials. When it is not installed, the feature links
  to Flathub.
- `systemd --user` autostart, desktop entry, Debian package build, and an Arch
  local PKGBUILD.
- Claude usage access is opt-in; its credential/API path is not started by
  default.

Desktop support claims are intentionally tiered; see
[`docs/platform-support.md`](docs/platform-support.md). GNOME and X11 require
their separate integration paths and remain unverified on this machine.

## Requirements

- Linux, Python 3.11+, PyGObject, GTK 4, libadwaita, and PulseAudio utilities.
- Pycairo/PyGObject Cairo bindings and `paplay` (provided by
  `pulseaudio-utils`) for Mochi rendering and sound effects.
- `gtk4-layer-shell` is optional but required for native top-edge placement on
  KDE Wayland and wlroots compositors.
- GNOME Wayland placement requires the included Shell extension. X11 EWMH
  behavior requires an X11 session; a compositor is needed for transparency.

Arch dependencies:

```sh
sudo pacman -S python python-gobject python-cairo gtk4 libadwaita libpulse
sudo pacman -S gtk4-layer-shell  # optional, for layer-shell placement
```

Debian/Ubuntu dependencies:

```sh
sudo apt install python3 python3-gi python3-gi-cairo \
  python3-cairo   python3-cairo gir1.2-gtk-4.0 gir1.2-adw-1 pulseaudio-utils
sudo apt install libgtk4-layer-shell0  # optional, when available
```

Run from the checkout:

```sh
PYTHONPATH=src python3 -m linux_notch
PYTHONPATH=src python3 -m linux_notch --version
```

Or install using `sudo packaging/install.sh`. The app uses
`~/.config/linux-notch/` and `~/.cache/linux-notch/`; it does not migrate or
modify Lost Island configuration.

### GNOME Shell

Install the extension to
`~/.local/share/gnome-shell/extensions/linux-notch@linuxnotch.org/` or use the
system installer, then enable it with GNOME Extensions. Log out and back in
when GNOME requires it. The extension's GTK-window positioning relies on
private Mutter APIs; test every GNOME Shell release before treating it as
supported.

As a temporary XWayland alternative, run `GDK_BACKEND=x11 linux-notch`. This
uses the X11 backend for top-center placement when an XWayland display is
available; GNOME Shell helper remains the native Wayland path.

### Login autostart

```sh
systemctl --user enable --now linux-notch.service
```

For desktops without systemd user services, copy the XDG autostart entry:

```sh
mkdir -p ~/.config/autostart
cp data/linux-notch-autostart.desktop ~/.config/autostart/
```

## Live Activity API

Activity producers run as separate processes and call `notchctl`; the app
never imports plugins into its process. See
[`docs/plugins/activity-api.md`](docs/plugins/activity-api.md).

```json
{
  "schema": 1,
  "app": "github-actions",
  "title": "deploy-prod",
  "state": "running",
  "progress": {"done": 18, "total": 20},
  "lines": [["Build", "Running"], ["Tests", "18/20"], ["Deploy", "Pending"]],
  "priority": "normal",
  "ttl_seconds": 3600
}
```

```sh
notchctl activity start --file run.json
notchctl activity update ACTIVITY_ID --progress 19/20
notchctl activity end ACTIVITY_ID --state success
```

The start command prints the activity ID. The activity ID is a random bearer token so separate `notchctl` invocations can
update the same activity; keep it private. Activities are grouped and quota-
limited by the declared app ID, with an additional per-D-Bus-client activity
limit. Clients are limited to 20 starts/minute and 120 updates/minute.
Payloads are limited to 16 KiB, strings are length-bounded, markup is not
interpreted, and TTL is capped at 24 hours.

## Development and verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m linux_notch --version
./packaging/build-deb.sh
```

Tests for backend selection, capability reporting, event delivery, activity
validation, bearer-token updates, quotas, and expiration run without a display server.
The GTK app itself needs the native GTK introspection packages and a logged-in
desktop session. Compositor-specific acceptance checks and current test gaps
are recorded in the platform support table and ADRs.

The PKGBUILD builds a local source archive. Do not publish it to AUR or build
the RPM spec until a Linux Notch repository/release URL and matching source
archive are configured. To package the current checkout, create the
`linux-notch-0.1.0.tar.gz` source archive in the project root (with a
`linux-notch-0.1.0/` top-level directory) and run `makepkg --nodeps`. The
dependency/license inventory is in
[`packaging/sbom.spdx.json`](packaging/sbom.spdx.json); release builds should
record actual system-library versions for the target distro.

## License and attribution

The main application is MIT-licensed. It reuses Lost Island v1.7.2, so the
original MIT notice in [`LICENSE`](LICENSE) is preserved. The GNOME Shell
extension is separately licensed GPL-2.0-or-later; see its
[`LICENSE`](gnome-extension/linux-notch@linuxnotch.org/LICENSE). Kasual
Desktop was used only as an architecture reference; no Kasual code is copied.
The Mochi character and sound effects are separate copyrighted assets included
under separate permission; see [`ASSET-ATTRIBUTION.md`](ASSET-ATTRIBUTION.md).
