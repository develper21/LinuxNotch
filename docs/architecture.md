# Architecture

The Linux Notch UI and existing desktop services are derived from the
MIT-licensed Lost Island v1.7.2 release. The product package is renamed
`linux_notch`, uses the `src/` layout, and stores its configuration and cache
under Linux Notch-specific XDG directories.

```text
GTK4 UI
  ├─ existing media / notification / system services
  ├─ live-activity pill presentation
  └─ Activity API D-Bus service
Core
  ├─ activity validation, ownership, quotas, expiry
  ├─ event bus and state store
  └─ capability descriptions
Desktop compatibility
  ├─ gtk4-layer-shell (Wayland layer-shell compositors)
  ├─ GNOME Shell helper (GNOME Wayland)
  ├─ X11 EWMH + XShape
  └─ GTK floating fallback
```

`choose_backend()` probes capabilities instead of selecting only by desktop
name. It does not choose X11 for a Wayland session that also exports
`DISPLAY`. The application preloads `libgtk4-layer-shell` before GTK imports,
because loading order affects layer-shell protocol registration.

Third-party producers remain separate processes and call `notchctl`. The
session-bus API accepts schema-1 JSON only, limits payloads and active
activities, enforces per-client quotas, and uses the caller's unique D-Bus
name for rate limiting. Activity IDs are random bearer tokens so separate
CLI invocations can update an activity; app IDs and client connections have
separate quotas. UI code receives updates in-process from the service's store;
plugins are never imported into the application process.

No Kasual Desktop source is copied. Its role was limited to architectural
reference as directed in the implementation plan.
