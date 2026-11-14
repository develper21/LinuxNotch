# Face-scan daemon (experimental)

The user-session daemon exposes `org.linuxnotch.FaceDaemon` at
`/org/linuxnotch/FaceDaemon`. It does not unlock the screen or alter the
password path. The lock-screen extension is expected to call `SetLocked`
before requesting a scan.

## Running

The daemon does not open a camera at startup. It opens camera 0 only after a
valid `StartScan` request while the extension has reported a locked session.
The experimental face dependencies and enrollment must already be installed:

```sh
linux-notch-face-daemon
```

For a packaged installation, the optional user service can be enabled with:

```sh
systemctl --user enable --now linux-notch-face.service
```

The daemon checks the enrollment and models before opening the camera. It
captures frames in memory only, releases the camera at the end of each scan,
and sends no image over D-Bus.

## Methods

- `SetLocked(locked: b)`: called by the shell extension on lock/unlock. A new
  lock starts a fresh attempt budget; unlocking cancels the active scan.
- `StartScan()`: starts one scan, only while locked and enrolled. Calls while
  busy, unlocked, un-enrolled, or over the attempt limit return a named D-Bus
  error.
- `TestScan()`: triggers an interactive camera test scan while the desktop is
  unlocked, emitting frames and match results without altering screen lock.
- `StartEnroll()`: starts an 8-pose interactive face enrollment sequence in memory
  and writes embeddings with 0600 file permissions (parent directory 0700).
- `Reset() -> b`: securely unlinks stored face embeddings.
- `GetStatus() -> (b, i, b, d, b)`: returns `(is_enrolled, sample_count, enabled, threshold, challenge_enabled)`.
- `SetThreshold(threshold: d)`: adjusts cosine similarity threshold (0.0 to 1.0).
- `SetEnabled(enabled: b)`: enables or disables face authentication.
- `SetChallenge(enabled: b)`: enables/disables the liveness head-movement challenge.
- `StopScan()`: cancels the active scan or enrollment.
- `UserActivity()`: re-arms the three-attempt budget after explicit user
  keyboard/pointer activity while locked. The extension must request the next
  scan separately.

Each scan is limited to eight seconds and succeeds only after three
consecutive matching frames. At most three scans run between user-activity
re-arms in a locked session.

## Signals

- `ScanState(state: s, message: s)`: state is `scanning`, `no_face`,
  `move_closer`, `challenge`, `not_recognized`, or `matched`.
- `ScanFrame(x: d, y: d, width: d, height: d, landmarks: a(dd))`: normalized
  face rectangle and five normalized landmarks; each coordinate is between
  zero and one relative to the camera frame. Frames are emitted at up to 15 Hz.
- `ScanResult(success: b, score: d)`: final result and best cosine score for
  that scan.
- `EnrollProgress(step: i, total: i, pose: s)`: live step progress during enrollment.
- `EnrollComplete(success: b, message: s)`: enrollment outcome.

## Lock screen UI (GNOME Extension)

The extension (`session-modes: ["user", "unlock-dialog"]`) hooks into
`Main.screenShield.connect('locked-changed')`:
1. **Idle/Closed**: Nothing is visible during normal desktop usage.
2. **Lock Screen Trigger**: When the unlock prompt opens, the notch eases up
   from the bottom edge using Cairo outward-curve shoulder geometry and
   `Clutter.AnimationMode.EASE_OUT_BACK`.
3. **Live Scan**: Renders live face outline and 5 landmark dots from `ScanFrame`.
4. **Success**: Shows a green checkmark + "Welcome", waiting ~400 ms before
   calling `Main.screenShield.deactivate(true)` to unlock.
5. **Failure / Timeout**: Shows "Face not recognized. Enter password", and after
   3 seconds the notch smoothly eases back below the bottom edge. The password box
   remains fully accessible and functional below at all times.

## Security & Hardening

- **Private Embeddings Only**: Stored as a NumPy matrix at
  `~/.local/share/linux-notch/face/embeddings.npy` with mode `0600` and
  directory mode `0700`. No camera images are ever saved to disk.
- **Strict Multi-Frame Agreement**: Requires 3 consecutive frames meeting the
  similarity threshold before an unlock signal is accepted.
- **Liveness Challenge**: An optional head-movement challenge verifies nose
  offset relative to the eye centers using YuNet 5-point landmarks, thwarting 2D photo spoofing.
- **First Login & Fallback**: Face unlock only operates on an existing locked
  user session. System boot login always requires the user password via GDM/PAM.
- **Camera Window**: The camera device is opened strictly during the scan
  duration and is immediately released in `finally` cleanup.
- **Uncompromised Fallback**: The extension never intercepts or interferes with
  password entry or PAM. The user can always type their password to unlock.
