"""Install / remove the Claude Code statusLine hook.

Claude Code hands usage data to a statusLine command, so we drop a standalone
copy of the hook next to the user's config and register it in
~/.claude/settings.json. No login, no API — the data rides in on stdin.
settings.json is backed up before it's touched.
"""

from __future__ import annotations

import json
import os
import shutil
import time

from linux_notch import config

CLAUDE_DIR = os.path.expanduser("~/.claude")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
HOOK_DEST = os.path.join(config.CONFIG_DIR, "claude-usage-hook.py")
MARKER = "claude-usage-hook.py"


def _hook_source() -> str:
    with open(os.path.join(os.path.dirname(__file__), "claude_hook.py")) as f:
        return f.read()


def install() -> str:
    if not os.path.isdir(CLAUDE_DIR):
        return (f"Claude Code config not found at {CLAUDE_DIR}. "
                "Install/run Claude Code first, then re-run this.")

    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    with open(HOOK_DEST, "w") as f:
        f.write(_hook_source())
    os.chmod(HOOK_DEST, 0o755)

    try:
        with open(SETTINGS) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}

    existing = settings.get("statusLine")
    if isinstance(existing, dict):
        cmd = existing.get("command", "")
        if cmd and MARKER not in cmd:
            return (
                "You already have a statusLine set:\n"
                f"  {cmd}\n"
                "Not overwriting it. To combine them, have that script also run:\n"
                f"  python3 {HOOK_DEST}\n"
                "(it reads the same stdin and just writes the usage cache).")

    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + f".bak-linux_notch-{int(time.time())}")

    settings["statusLine"] = {
        "type": "command",
        "command": f"python3 {HOOK_DEST}",
        "padding": 0,
    }
    with open(SETTINGS, "w") as f:
        json.dump(settings, f, indent=2)

    return ("Claude usage hook installed.\n"
            f"  hook:     {HOOK_DEST}\n"
            f"  statusLine registered in {SETTINGS}\n"
            "Open a Claude Code session once so the first numbers land, then "
            "enable the Claude usage module in Linux Notch Settings.")


def uninstall() -> str:
    try:
        with open(SETTINGS) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return "Nothing to remove."
    sl = settings.get("statusLine")
    if isinstance(sl, dict) and MARKER in sl.get("command", ""):
        shutil.copy2(SETTINGS, SETTINGS + f".bak-linux_notch-{int(time.time())}")
        settings.pop("statusLine", None)
        with open(SETTINGS, "w") as f:
            json.dump(settings, f, indent=2)
        return "Claude usage hook removed from settings.json."
    return "The statusLine isn't ours — left it untouched."
