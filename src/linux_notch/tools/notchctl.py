from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from linux_notch.activity.dbus_service import BUS_NAME, INTERFACE, OBJECT_PATH
from linux_notch.activity.schema import ActivityValidationError, decode_json


def _dbus_call(method: str, signature: str, values: tuple[Any, ...], result_type: str) -> Any:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            method,
            GLib.Variant(signature, values),
            GLib.VariantType.new(result_type),
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
    except GLib.Error as error:
        raise RuntimeError(error.message) from error
    return result.unpack()


def _read_json(path: str) -> dict[str, Any]:
    try:
        payload = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ActivityValidationError(f"Cannot read {path}: {error}") from error
    return decode_json(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notchctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("toggle", help="Toggle the Linux Notch island")

    activity = subparsers.add_parser("activity", help="Manage live activities")
    actions = activity.add_subparsers(dest="action", required=True)
    start = actions.add_parser("start", help="Start a live activity")
    start.add_argument("--file", required=True, help="JSON activity document")
    update = actions.add_parser("update", help="Update a live activity")
    update.add_argument("activity_id")
    update.add_argument("--file", help="JSON patch file")
    update.add_argument("--title")
    update.add_argument("--state")
    update.add_argument("--progress", help="Progress as completed/total")
    end = actions.add_parser("end", help="End a live activity")
    end.add_argument("activity_id")
    end.add_argument("--state", required=True, help="Final activity state")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "toggle":
            subprocess.run(["linux-notch", "--toggle"], check=True)
            return 0
        if args.action == "start":
            payload = json.dumps(_read_json(args.file), ensure_ascii=False, separators=(",", ":"))
            (activity_id,) = _dbus_call("StartActivity", "(s)", (payload,), "(s)")
            print(activity_id)
            return 0
        if args.action == "update":
            patch = _read_json(args.file) if args.file else {}
            for key in ("title", "state"):
                value = getattr(args, key)
                if value is not None:
                    patch[key] = value
            if args.progress:
                try:
                    done_text, total_text = args.progress.split("/", 1)
                    patch["progress"] = {"done": int(done_text), "total": int(total_text)}
                except (ValueError, TypeError) as error:
                    raise ActivityValidationError("progress must be completed/total") from error
            if not patch:
                raise ActivityValidationError("Provide --file, --title, --state, or --progress")
            payload = json.dumps(patch, ensure_ascii=False, separators=(",", ":"))
            _dbus_call("UpdateActivity", "(ss)", (args.activity_id, payload), "()")
            return 0
        _dbus_call("EndActivity", "(ss)", (args.activity_id, args.state), "()")
        return 0
    except (ActivityValidationError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"notchctl: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
