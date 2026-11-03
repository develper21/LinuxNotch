# ADR 0002: X11 integration

- Status: implemented, runtime verification pending.
- Date: 2026-11-07.

## Decision

Use Xlib to set EWMH dock, above, sticky, skip-taskbar and skip-pager window
properties. Use XShape input rectangles when libXext is available. Keep a
normal GTK fallback when no usable X11 display exists.

## Rationale

GTK4 no longer exposes the legacy window-type hints needed for this overlay.
Using Xlib avoids adding a Python X11 package dependency and confines the
window-manager-specific behavior to `desktop/x11.py`.

## Consequences and verification

Window managers may ignore EWMH hints. Transparency depends on an active
compositor; fullscreen stacking and fractional scaling are not guaranteed.
The XFCE and Cinnamon smoke tests, compositing-off check, and click-through
check remain required before advertising X11 as verified.
