# Linux Notch

Linux Notch is a GTK4 desktop island, based on the MIT-licensed Lost Island
v1.7.2 UI and services, with a Linux desktop backend layer and a versioned
session-bus API for live activities. It is independently maintained; the
upstream Lost Island copyright and MIT notice are retained alongside Linux
Notch's own copyright.

Project policies: [Contributing](CONTRIBUTING.md) ·
[Security](SECURITY.md) · [Copyright](COPYRIGHT.md) ·
[Third-party notices](THIRD-PARTY-NOTICES.md)

## What works today

- The existing island UI and event-driven desktop services from the pinned
  upstream release.
- Runtime desktop backend selection: gtk4-layer-shell, GNOME Shell helper,
  X11/EWMH, or a documented floating-window fallback.
- Activity API schema 1 over D-Bus (`org.linuxnotch.Notch1`) and the `notchctl`
  client. Activities are per-D-Bus-client, bounded, plain-text data with
  quotas and expiration.
- Animated Mochi character moods, seasonal outfits, and 29 bundled sound
  effects. The collapsed island shows Mochi and a local-playback equalizer;
  choose his outfit from the expanded Mochi feature, and configure sound
  volume and previews in Settings. The Mochi character and bundled sounds are
  separately copyrighted assets; see
  [asset attribution](ASSET-ATTRIBUTION.md).
- Expanded features include a local music library, unread Gmail inbox,
  ToDo list, weekly Screen Time chart, stopwatch, and optional persistent VTE
  terminal page.
- Clipboard history is opt-in, local-only, and paused by default; text and
  bounded image history can be pinned, copied back, or cleared. GTK clipboard
  access depends on desktop permissions, so Wayland monitoring may be limited.
- Music scans the configured local folder recursively and plays audio through
  GStreamer. It displays embedded or nearby album art and does not use a
  streaming service or account. The collapsed island rotates through the
  clock, battery, weather, and separate CPU/RAM status values when available.
- The closed-notch equalizer defaults to Auto: it tries real FFT levels from
  the default audio-output monitor while local music plays, then falls back to
  synthetic motion if capture is unavailable. Real sync never uses the
  microphone or saves audio; choose Real (beta) or Synthetic in Settings.
- `systemd --user` autostart, desktop entry, Debian package build, and an Arch
  local PKGBUILD.
- Claude usage access is opt-in; its credential/API path is not started by
  default.

## Face engine experiment

The experimental face engine does not unlock the session. It stores only
locally captured face embeddings under
`~/.local/share/linux-notch/face/embeddings.npy`; raw camera frames are never
saved. The camera is opened only during an explicit face-test or locked-session
scan request.
Threshold `0.45` is a starting point, not a security guarantee, and ordinary
webcams do not provide liveness detection.

```sh
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -e '.[face]'
notch-face-test download-models
notch-face-test enroll
notch-face-test check
```

The YuNet and SFace ONNX models are downloaded from the pinned
[OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models)
revision and SHA-256 verified before use. Their model licenses are
[MIT (YuNet)](https://github.com/opencv/opencv_zoo/blob/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet/LICENSE)
and
[Apache-2.0 (SFace)](https://github.com/opencv/opencv_zoo/blob/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_recognition_sface/LICENSE).

The experimental user-session scanner can be started with
`linux-notch-face-daemon`; it exposes `org.linuxnotch.FaceDaemon` and opens the
camera only after a locked-session `StartScan` call. It does not unlock the
screen. See [`docs/face-auth.md`](docs/face-auth.md) for its D-Bus API.

Desktop support claims are intentionally tiered; see
[`docs/platform-support.md`](docs/platform-support.md). GNOME and X11 require
their separate integration paths and remain unverified on this machine.

## Requirements

- Linux, Python 3.11+, PyGObject, GTK 4, libadwaita, and PulseAudio utilities.
- Pycairo/PyGObject Cairo bindings and `paplay` (provided by
  `pulseaudio-utils`) for Mochi rendering and sound effects.
- `libsecret` and an unlocked Secret Service keyring for securely saving
  Gmail App Passwords used by the Mail feature.
- VTE GTK 4 bindings and library for the embedded terminal. The terminal
  feature displays installation instructions if VTE is absent.
- `gtk4-layer-shell` is optional but required for native top-edge placement on
  KDE Wayland and wlroots compositors.
- GNOME Wayland placement requires the included Shell extension. X11 EWMH
  behavior requires an X11 session; a compositor is needed for transparency.
- The default bottom margin slightly overlaps the display edge to compensate
  for transparent GTK surface padding; adjust the bottom margin in Settings
  if you want to move it back up.

Arch dependencies:

```sh
sudo pacman -S python python-gobject python-cairo gtk4 libadwaita libpulse \
  gstreamer gst-plugins-base gst-plugins-good libsecret
sudo pacman -S gnome-keyring  # keyring service, if your desktop has none
sudo pacman -S gst-plugin-pulse  # optional, for real audio-sync visualization
sudo pacman -S gtk4-layer-shell  # optional, for layer-shell placement
sudo pacman -S vte4  # embedded terminal
sudo pacman -S python-opencv python-numpy  # optional, for face scan
```

Debian/Ubuntu dependencies:

```sh
sudo apt install python3 python3-gi python3-gi-cairo \
  python3-cairo gir1.2-gtk-4.0 gir1.2-adw-1 pulseaudio-utils \
  gir1.2-secret-1 gnome-keyring \
  gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good
sudo apt install gstreamer1.0-pulseaudio  # optional, for real audio sync
sudo apt install libgtk4-layer-shell0  # optional, when available
sudo apt install gir1.2-vte-3.91 libvte-2.91-gtk4-0
sudo apt install python3-opencv python3-numpy  # optional, for face scan
sudo apt install xprintidle  # optional, for X11 screen-time idle detection
```

### Gmail Mail

The Mail button connects to one Gmail account using IMAP and SMTP over TLS.
Enable 2-Step Verification in your Google Account, then create an App Password
from **Security → 2-Step Verification → App passwords**. Enter your Gmail
address and that App Password in the Mail page; do not enter your regular
Google password. Linux Notch keeps the App Password in the desktop Secret
Service keyring and stores only the account address in its settings. The Mail
page lists unread messages; opening one marks it read. Remote images in HTML
mail are not loaded.

### Screen Time

Screen Time records only active desktop duration, grouped by local calendar
day; it does not record keyboard input, screenshots, or application names.
Tracking pauses after five minutes of inactivity and is stored locally in
`~/.local/state/linux-notch/screen-time.sqlite3` (or `$XDG_STATE_HOME`).
GNOME and compatible desktop idle-monitor interfaces are detected
automatically; X11 can use the optional `xprintidle` package.

Run from the checkout:

```sh
PYTHONPATH=src python3 -m linux_notch
PYTHONPATH=src python3 -m linux_notch --version
```

Or install using `sudo bash packaging/install.sh`. The app uses
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
uses the X11 backend for bottom-center placement when an XWayland display is
available; GNOME Shell helper remains the native Wayland path.

### Login autostart

```sh
systemctl --user enable --now linux-notch.service
```

### Terminal

The terminal starts a user shell the first time its feature page opens. Its VTE
widget and shell remain alive while the notch is hidden, so long-running
commands continue when you navigate Back or collapse the island. Keyboard
shortcuts are `Ctrl+Shift+C/V` for copy/paste and `Ctrl+Plus/Minus/0` for font
scaling. The app removes its `PYTHONPATH`, `PYTHONHOME`, `GDK_BACKEND`, virtual
environment marker, and matching virtualenv `bin` entry from the shell
environment.

On GNOME, a custom shortcut can toggle the terminal page from anywhere:

1. Open Settings → Keyboard → Custom Shortcuts.
2. Set the command to `gapplication action org.linuxnotch.LinuxNotch toggle-terminal`.
3. Assign a shortcut such as `Ctrl+grave`.

The application does not register a global shortcut itself. Esc is passed to
the shell (for example, to Vim); use the page Back button to navigate.
For GNOME Wayland keyboard focus, install/reload the included Shell extension
after updating Linux Notch so its `Focus` helper method is available.

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for native development dependencies,
setup, test commands, and the required DCO sign-off for pull requests.

```sh
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check src tests plugins/examples
python -m compileall -q src tests
dbus-run-session -- env PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m linux_notch --version
bash packaging/build-deb.sh
```

Tests for backend selection, capability reporting, event delivery, activity
validation, bearer-token updates, quotas, and expiration run without a display server.
The GTK app itself needs the native GTK introspection packages and a logged-in
desktop session. Compositor-specific acceptance checks and current test gaps
are recorded in the platform support table and ADRs.
CI runs tests/quality checks independently from the Debian package build; see
the [GitHub Actions workflows](.github/workflows/).

The PKGBUILD builds a local source archive. Do not publish it to AUR or build
the RPM spec until a Linux Notch repository/release URL and matching source
archive are configured. To package the current checkout, create the
`linux-notch-0.1.0.tar.gz` source archive in the project root (with a
`linux-notch-0.1.0/` top-level directory) and run `makepkg --nodeps`. The
dependency/license inventory is in
[`packaging/sbom.spdx.json`](packaging/sbom.spdx.json); release builds should
record actual system-library versions for the target distro.

## License and attribution

The main application code is MIT-licensed; see [`LICENSE`](LICENSE) and
[`COPYRIGHT.md`](COPYRIGHT.md). The GNOME Shell extension is separately
licensed GPL-2.0-or-later; see its
[`LICENSE`](gnome-extension/linux-notch@linuxnotch.org/LICENSE). The Mochi
character and sound effects are not covered by the application MIT license;
their separate attribution and permitted project use are documented in
[`ASSET-ATTRIBUTION.md`](ASSET-ATTRIBUTION.md). Third-party dependencies and
models are listed in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) and
the [SPDX inventory](packaging/sbom.spdx.json). Contributions retain their
authors' copyright and require DCO sign-off; see
[`CONTRIBUTING.md`](CONTRIBUTING.md).
