#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/usr/local}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '[linux-notch] %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  say "run this installer with sudo"
  exit 1
fi

if [ ! -f "$ROOT/pyproject.toml" ] || [ ! -d "$ROOT/src/linux_notch" ]; then
  say "run packaging/install.sh from a Linux Notch source checkout"
  exit 1
fi

if command -v pacman >/dev/null; then
  pacman -S --noconfirm --needed python python-gobject python-cairo gtk4 \
    libadwaita libpulse gstreamer gst-plugins-base gst-plugins-good \
    gst-plugin-pulse libsecret gnome-keyring gtk4-layer-shell vte4
elif command -v apt-get >/dev/null; then
  apt-get install -y python3 python3-gi python3-gi-cairo python3-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1 gnome-keyring \
    pulseaudio-utils libgtk4-layer-shell0 \
    gir1.2-vte-3.91 libvte-2.91-gtk4-0 gir1.2-gstreamer-1.0 \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-pulseaudio
elif command -v dnf >/dev/null; then
  dnf install -y python3 python3-gobject python3-cairo gtk4 libadwaita \
    libsecret gnome-keyring pulseaudio-utils gstreamer1 \
    gstreamer1-plugins-base \
    gstreamer1-plugins-good gtk4-layer-shell vte291-gtk4
else
  say "install Python 3.11+, PyGObject, GTK4, libadwaita, VTE GTK4, and PulseAudio utilities first"
fi

say "installing Linux Notch to $PREFIX"
install -d "$PREFIX/lib/linux-notch" "$PREFIX/bin"
rm -rf "$PREFIX/lib/linux-notch/linux_notch"
cp -r "$ROOT/src/linux_notch" "$PREFIX/lib/linux-notch/"
find "$PREFIX/lib/linux-notch" -name __pycache__ -type d -exec rm -rf {} +

cat > "$PREFIX/bin/linux-notch" <<EOF
#!/bin/sh
PYTHONPATH=$PREFIX/lib/linux-notch exec python3 -m linux_notch "\$@"
EOF
cat > "$PREFIX/bin/notchctl" <<EOF
#!/bin/sh
PYTHONPATH=$PREFIX/lib/linux-notch exec python3 -m linux_notch.tools.notchctl "\$@"
EOF
cat > "$PREFIX/bin/linux-notch-face-daemon" <<EOF
#!/bin/sh
PYTHONPATH=$PREFIX/lib/linux-notch exec python3 -m linux_notch.tools.face_daemon "\$@"
EOF
chmod 755 "$PREFIX/bin/linux-notch" "$PREFIX/bin/notchctl" \
  "$PREFIX/bin/linux-notch-face-daemon"

sed "s|^Exec=linux-notch$|Exec=$PREFIX/bin/linux-notch|" \
  "$ROOT/data/linux-notch.desktop" \
  > /usr/share/applications/linux-notch.desktop
install -Dm644 "$ROOT/data/linux-notch.svg" \
  /usr/share/icons/hicolor/scalable/apps/linux-notch.svg
sed "s|^ExecStart=/usr/bin/linux-notch$|ExecStart=$PREFIX/bin/linux-notch|" \
  "$ROOT/data/linux-notch.service" \
  > /usr/lib/systemd/user/linux-notch.service
sed "s|^ExecStart=/usr/bin/linux-notch-face-daemon$|ExecStart=$PREFIX/bin/linux-notch-face-daemon|" \
  "$ROOT/data/linux-notch-face.service" \
  > /usr/lib/systemd/user/linux-notch-face.service
install -Dm644 "$ROOT/gnome-extension/linux-notch@linuxnotch.org/metadata.json" \
  /usr/share/gnome-shell/extensions/linux-notch@linuxnotch.org/metadata.json
install -Dm644 "$ROOT/gnome-extension/linux-notch@linuxnotch.org/extension.js" \
  /usr/share/gnome-shell/extensions/linux-notch@linuxnotch.org/extension.js
install -Dm644 "$ROOT/gnome-extension/linux-notch@linuxnotch.org/LICENSE" \
  /usr/share/gnome-shell/extensions/linux-notch@linuxnotch.org/LICENSE
install -Dm644 "$ROOT/ASSET-ATTRIBUTION.md" \
  /usr/share/doc/linux-notch/ASSET-ATTRIBUTION.md

say "installed. Run: linux-notch"
say "Enable login autostart with: systemctl --user enable --now linux-notch.service"
