#!/usr/bin/env python3
import json
import subprocess
import tempfile
from pathlib import Path


def run_notchctl(*args: str) -> str:
    result = subprocess.run(
        ["notchctl", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


with tempfile.TemporaryDirectory(prefix="linux-notch-") as directory:
    activity_file = Path(directory) / "activity.json"
    activity_file.write_text(
        json.dumps(
            {
                "schema": 1,
                "app": "example-build",
                "title": "Release build",
                "state": "running",
                "progress": {"done": 0, "total": 3},
                "lines": [["Build", "Starting"]],
                "priority": "normal",
                "ttl_seconds": 600,
            }
        ),
        encoding="utf-8",
    )
    activity_id = run_notchctl(
        "activity", "start", "--file", str(activity_file)
    )
    run_notchctl(
        "activity", "update", activity_id, "--progress", "3/3", "--state", "success"
    )
    run_notchctl("activity", "end", activity_id, "--state", "success")
