Name:           linux-notch
Version:        0.1.0
Release:        1%{?dist}
Summary:        A native GTK island for Linux desktops
License:        MIT
URL:            https://github.com/MarcoZorn/lost-island
Source0:        linux-notch-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.11, python3-gobject, python3-cairo, gtk4, libadwaita, pulseaudio-utils
Recommends:     gtk4-layer-shell, NetworkManager, upower

%description
A GTK4 desktop island with media, notifications, system indicators, and a
versioned D-Bus API for live activities.

%prep
%autosetup -n %{name}-%{version}

%install
install -d %{buildroot}/usr/lib/linux-notch
cp -r src/linux_notch %{buildroot}/usr/lib/linux-notch/
install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/linux-notch <<'EOF'
#!/bin/sh
PYTHONPATH=/usr/lib/linux-notch exec python3 -m linux_notch "$@"
EOF
cat > %{buildroot}%{_bindir}/notchctl <<'EOF'
#!/bin/sh
PYTHONPATH=/usr/lib/linux-notch exec python3 -m linux_notch.tools.notchctl "$@"
EOF
chmod 755 %{buildroot}%{_bindir}/linux-notch %{buildroot}%{_bindir}/notchctl
install -Dm644 data/linux-notch.desktop %{buildroot}%{_datadir}/applications/linux-notch.desktop
install -Dm644 data/linux-notch.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/linux-notch.svg
install -Dm644 data/linux-notch.service %{buildroot}/usr/lib/systemd/user/linux-notch.service
install -Dm644 data/linux-notch-autostart.desktop \
  %{buildroot}%{_docdir}/linux-notch/linux-notch-autostart.desktop
install -Dm644 gnome-extension/linux-notch@linuxnotch.org/metadata.json \
  %{buildroot}%{_datadir}/gnome-shell/extensions/linux-notch@linuxnotch.org/metadata.json
install -Dm644 gnome-extension/linux-notch@linuxnotch.org/extension.js \
  %{buildroot}%{_datadir}/gnome-shell/extensions/linux-notch@linuxnotch.org/extension.js
install -Dm644 gnome-extension/linux-notch@linuxnotch.org/LICENSE \
  %{buildroot}%{_datadir}/licenses/linux-notch/gnome-extension/LICENSE
install -Dm644 ASSET-ATTRIBUTION.md \
  %{buildroot}%{_datadir}/licenses/linux-notch/ASSET-ATTRIBUTION.md

%files
/usr/lib/linux-notch
%{_bindir}/linux-notch
%{_bindir}/notchctl
%{_datadir}/applications/linux-notch.desktop
%{_datadir}/icons/hicolor/scalable/apps/linux-notch.svg
/usr/lib/systemd/user/linux-notch.service
%{_datadir}/gnome-shell/extensions/linux-notch@linuxnotch.org
%doc %{_docdir}/linux-notch/linux-notch-autostart.desktop
%license LICENSE
%license ASSET-ATTRIBUTION.md
