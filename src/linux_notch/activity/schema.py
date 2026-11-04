from __future__ import annotations

import json
import re
from typing import Any

SCHEMA_VERSION = 1
MAX_JSON_BYTES = 16 * 1024
MAX_ACTIVE_PER_CLIENT = 10
MAX_ACTIVE_PER_APP = 10
MAX_STARTS_PER_MINUTE = 20
MAX_UPDATES_PER_MINUTE = 120
MAX_TTL_SECONDS = 24 * 60 * 60
_APP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ICON_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ACTIVITY_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_PRIORITIES = {"low", "normal", "high", "urgent"}
_ALLOWED_FIELDS = {
    "schema",
    "app",
    "title",
    "state",
    "progress",
    "lines",
    "priority",
    "ttl_seconds",
    "icon",
}


class ActivityValidationError(ValueError):
    pass


def decode_json(payload: str) -> dict[str, Any]:
    if not isinstance(payload, str):
        raise ActivityValidationError("Activity payload must be a JSON string")
    try:
        payload_size = len(payload.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ActivityValidationError("Activity payload contains invalid Unicode") from error
    if payload_size > MAX_JSON_BYTES:
        raise ActivityValidationError("Activity JSON exceeds the 16 KiB limit")
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeEncodeError) as error:
        raise ActivityValidationError("Activity payload must be valid JSON") from error
    if not isinstance(value, dict):
        raise ActivityValidationError("Activity payload must be a JSON object")
    return value


def normalize_activity(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActivityValidationError("Activity must be a JSON object")
    schema = value.get("schema")
    if isinstance(schema, bool) or schema != SCHEMA_VERSION:
        raise ActivityValidationError(f"Only activity schema {SCHEMA_VERSION} is supported")

    app = _plain_string(value.get("app"), "app", 64)
    if not _APP_ID.fullmatch(app):
        raise ActivityValidationError("app must be a short application identifier")

    normalized: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "app": app,
        "title": _plain_string(value.get("title"), "title", 120),
        "state": _plain_string(value.get("state"), "state", 40),
        "priority": value.get("priority", "normal"),
        "ttl_seconds": value.get("ttl_seconds", 3600),
    }

    if not isinstance(normalized["priority"], str) or normalized["priority"] not in _PRIORITIES:
        raise ActivityValidationError("priority must be low, normal, high, or urgent")
    ttl = normalized["ttl_seconds"]
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= MAX_TTL_SECONDS:
        raise ActivityValidationError("ttl_seconds must be between 1 and 86400")

    if "progress" in value:
        progress = value["progress"]
        if not isinstance(progress, dict) or set(progress) - {"done", "total"}:
            raise ActivityValidationError("progress must contain only done and total")
        done, total = progress.get("done"), progress.get("total")
        if (
            isinstance(done, bool)
            or isinstance(total, bool)
            or not isinstance(done, int)
            or not isinstance(total, int)
            or done < 0
            or total < 1
            or done > total
        ):
            raise ActivityValidationError("progress requires 0 <= done <= total")
        normalized["progress"] = {"done": done, "total": total}

    if "lines" in value:
        lines = value["lines"]
        if not isinstance(lines, list) or len(lines) > 6:
            raise ActivityValidationError("lines must be an array of at most 6 label/value pairs")
        normalized["lines"] = [
            [_plain_string(pair[0], "line label", 48), _plain_string(pair[1], "line value", 80)]
            for pair in lines
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ]
        if len(normalized["lines"]) != len(lines):
            raise ActivityValidationError("each line must contain exactly two strings")

    if "icon" in value:
        icon = _plain_string(value["icon"], "icon", 128)
        if not _ICON_NAME.fullmatch(icon):
            raise ActivityValidationError("icon must be a theme icon name")
        normalized["icon"] = icon

    return normalized


def normalize_patch(patch: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ActivityValidationError("Activity patch must be a JSON object")
    known = {key: value for key, value in patch.items() if key in _ALLOWED_FIELDS}
    if "schema" in known and known["schema"] != current["schema"]:
        raise ActivityValidationError("schema cannot be changed by an update")
    if "app" in known and known["app"] != current["app"]:
        raise ActivityValidationError("app cannot be changed by an update")
    merged = dict(current)
    merged.update(known)
    normalized = normalize_activity(merged)
    normalized["app"] = current["app"]
    return normalized


def validate_activity_id(activity_id: str) -> str:
    if not isinstance(activity_id, str) or not _ACTIVITY_ID.fullmatch(activity_id):
        raise ActivityValidationError("activity_id is invalid")
    return activity_id


def _plain_string(value: Any, label: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ActivityValidationError(f"{label} must be a non-empty string of at most {max_length} characters")
    if any(ord(char) < 32 and char not in "\t\n" for char in value):
        raise ActivityValidationError(f"{label} contains unsupported control characters")
    return value
