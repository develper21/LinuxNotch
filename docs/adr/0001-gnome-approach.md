# ADR 0001: GNOME integration approach

- Status: provisional; runtime spike and screenshot comparison are pending.
- Date: 2026-11-07.

## Decision

Use the plan's GTK-window-plus-GNOME-Shell-helper design as the initial
implementation. The extension owns `org.linuxnotch.GnomeHelper`, positions
the application window and handles fullscreen policy; the GTK UI remains
shared with other backends.

## Rationale

This keeps a single GTK UI implementation and confines GNOME-specific work
to the desktop compatibility layer. The D-Bus service is private to Linux
Notch and does not reuse another project's bus name or implementation.

## Consequences and verification

Mutter window-management methods are not a stable extension API. The helper
is therefore not a support claim until it passes the GNOME 45+ VM/live-session
spike for top-center placement, fullscreen, lock/unlock, monitor changes, and
Shell restart. If those checks fail, compare the separate St-widget UI design
before enabling the backend by default.
