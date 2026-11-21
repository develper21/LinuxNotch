Name:           linux-notch
Version:        0.1.0
Release:        1%{?dist}
Summary:        A native GTK island for Linux desktops
License:        MIT AND GPL-2.0-or-later
URL:            https://github.com/develper21/LinuxNotch
Source0:        linux-notch-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.11, python3-gobject, python3-cairo, gtk4, libadwaita, libsecret, pulseaudio-utils, gstreamer1, gstreamer1-plugins-base, gstreamer1-plugins-good
Recommends:     gnome-keyring, gtk4-layer-shell, NetworkManager, upower, vte291-gtk4

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
install -Dm644 NOTICE COPYRIGHT.md THIRD-PARTY-NOTICES.md \
  -t %{buildroot}%{_datadir}/licenses/linux-notch/

%files
/usr/lib/linux-notch
%{_bindir}/linux-notch
%{_bindir}/notchctl
%{_datadir}/applications/linux-notch.desktop
/usr/lib/systemd/user/linux-notch.service
%{_datadir}/gnome-shell/extensions/linux-notch@linuxnotch.org
%doc %{_docdir}/linux-notch/linux-notch-autostart.desktop
%license LICENSE
%license NOTICE
%license COPYRIGHT.md
%license THIRD-PARTY-NOTICES.md
%license ASSET-ATTRIBUTION.md
