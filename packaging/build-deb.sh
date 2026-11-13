#!/bin/bash
# Builds linux-notch_<ver>_all.deb into dist/. Needs dpkg-deb only.
set -euo pipefail

cd "$(dirname "$0")/.."
VER=$(sed -n '/^\[project\]/,/^\[/s/^version = "\(.*\)"/\1/p' pyproject.toml | head -n1)
ROOT="dist/deb/linux-notch_${VER}_all"
rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" dist

mkdir -p "$ROOT/usr/lib/linux-notch" "$ROOT/usr/bin" \
  "$ROOT/usr/share/applications" \
  "$ROOT/usr/share/icons/hicolor/scalable/apps" \
  "$ROOT/usr/lib/systemd/user" \
  "$ROOT/usr/share/doc/linux-notch" \
  "$ROOT/usr/share/gnome-shell/extensions/linux-notch@linuxnotch.org"

cp -r src/linux_notch "$ROOT/usr/lib/linux-notch/"
find "$ROOT" -name __pycache__ -type d -exec rm -rf {} +

cat > "$ROOT/usr/bin/linux-notch" <<'EOF'
#!/bin/sh
PYTHONPATH=/usr/lib/linux-notch exec python3 -m linux_notch "$@"
EOF
chmod 755 "$ROOT/usr/bin/linux-notch"

cat > "$ROOT/usr/bin/notchctl" <<'EOF'
#!/bin/sh
PYTHONPATH=/usr/lib/linux-notch exec python3 -m linux_notch.tools.notchctl "$@"
EOF
chmod 755 "$ROOT/usr/bin/notchctl"

cat > "$ROOT/usr/bin/linux-notch-face-daemon" <<'EOF'
#!/bin/sh
PYTHONPATH=/usr/lib/linux-notch exec python3 -m linux_notch.tools.face_daemon "$@"
EOF
chmod 755 "$ROOT/usr/bin/linux-notch-face-daemon"

cp data/linux-notch.desktop "$ROOT/usr/share/applications/"
cp data/linux-notch.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
cp data/linux-notch.service "$ROOT/usr/lib/systemd/user/"
cp data/linux-notch-face.service "$ROOT/usr/lib/systemd/user/"
cp data/linux-notch-autostart.desktop "$ROOT/usr/share/doc/linux-notch/"
cp -r gnome-extension/linux-notch@linuxnotch.org/. \
  "$ROOT/usr/share/gnome-shell/extensions/linux-notch@linuxnotch.org/"
cp LICENSE "$ROOT/usr/share/doc/linux-notch/copyright"
cp ASSET-ATTRIBUTION.md "$ROOT/usr/share/doc/linux-notch/"
cp gnome-extension/linux-notch@linuxnotch.org/LICENSE \
  "$ROOT/usr/share/doc/linux-notch/gnome-extension-license"

cat > "$ROOT/DEBIAN/control" <<EOF
Package: linux-notch
Version: $VER
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, pulseaudio-utils
Recommends: libgtk4-layer-shell0, network-manager, upower, python3-opencv, python3-numpy
Maintainer: Linux Notch contributors
Homepage: https://github.com/MarcoZorn/lost-island
Description: Native island overlay for Linux desktops
 GTK4 island UI with media, notifications, system indicators, and a
 versioned D-Bus API for live activities.
EOF

dpkg-deb --build --root-owner-group "$ROOT" "dist/linux-notch_${VER}_all.deb"
echo "built dist/linux-notch_${VER}_all.deb"
