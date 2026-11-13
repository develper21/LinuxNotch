"""Entrypoint for the user-session face-scan D-Bus daemon."""

from __future__ import annotations

from linux_notch.services.face_daemon import run_daemon


def main() -> int:
    run_daemon()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
