# Activity API schema 1

The app exports `org.linuxnotch.Notch1` at `/org/linuxnotch/Notch1` on the
session bus:

- `StartActivity(s json) -> s activity_id`
- `UpdateActivity(s activity_id, s json_patch)`
- `EndActivity(s activity_id, s final_state)`
- `ActivityAction(s activity_id, s action_id)` signal

The `schema` field must be `1`. Unknown fields are ignored. `app`, `title`,
`state`, `progress`, `lines`, `priority`, `icon`, and `ttl_seconds` are
validated; titles and labels are plain text rendered as text, never markup.
Icon values are theme names only, not arbitrary paths or image payloads.
Payloads may not exceed 16 KiB, strings have field-specific length limits,
and TTL is 1–86,400 seconds.

Each D-Bus client and each declared app ID may have at most 10 active
activities. Clients and app IDs are limited to 20 starts/minute and 120
updates/minute. The random activity ID is a bearer token so distinct CLI
processes can update one activity; keep it private. Data is in memory only
and expires automatically; restarting the app clears it.

```sh
notchctl activity start --file run.json
notchctl activity update ACTIVITY_ID --progress 18/20
notchctl activity end ACTIVITY_ID --state success
```

The current active activity appears in the collapsed pill while the selected
face is `auto` or `activity`. The UI shows progress when supplied. Producers
should avoid sending secrets, paths, or other sensitive values.

## External producer example

[`examples/demo_activity.py`](../../plugins/examples/demo_activity.py) uses
only the public CLI and temporary JSON files. It does not import application
code or load as an in-process plugin.
