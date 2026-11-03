# Linux desktop support

The support tier is a release promise only after the listed tests have run.
This checkout has been exercised in a KDE Wayland session for repository and
runtime detection only; it has not passed the visual acceptance checklist
because GTK4/libadwaita and gtk4-layer-shell are unavailable in that session.

| Tier | Desktop/session | Intended path | Verified here |
|---|---|---|---|
| 1 | KDE Plasma 6 Wayland | GTK4 layer-shell | No; required system libraries unavailable |
| 1 | Sway / Hyprland Wayland | GTK4 layer-shell | No; no compositor sessions available |
| 1 | GNOME 45+ Wayland | GNOME Shell extension + D-Bus | No; extension and shell versions untested |
| 1 | XFCE X11 | EWMH + optional XShape | No; X11 window manager unavailable |
| 2 | river / Wayfire / labwc | GTK4 layer-shell, if protocol works | No; best effort |
| 2 | KDE X11 / Cinnamon / MATE / i3 | X11 backend | No; best effort |
| 3 | Other sessions | Ordinary GTK floating window | Fallback logic unit-tested only |

## Known limitations

- The GNOME extension uses Mutter window methods that are not a stable
  cross-release API. It must be tested on every supported Shell release.
- GTK4 layer-shell behavior depends on the compositor and its fractional
  scaling implementation. Monitor hotplug, click-through and fullscreen
  behavior need live-session checks.
- X11 dock/above/sticky hints are window-manager policy, not guarantees.
  Transparency needs a compositing manager; XShape is optional.
- The floating fallback cannot promise top-center positioning, panel overlap,
  fullscreen behavior, or click-through.
- Background clipboard, privacy monitoring, downloads, calendar and workspace
  integrations are not enabled or implemented in this initial deliverable.
- User-configured media, notification, audio and weather services inherit the
  upstream implementation's dependency and capability limits.

Run the manual acceptance checklist from the implementation plan before
claiming a tier as verified: panel overlap, click-through, music, OSD,
notifications, Activity API, fullscreen, monitor hotplug, login recovery,
and HiDPI. No compatibility claim should be inferred from code paths alone.
