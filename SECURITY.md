# Security Policy

## Reporting a vulnerability

Please do not report exploitable vulnerabilities in a public issue or pull
request. Use GitHub's **Report a vulnerability** option in the repository's
Security tab (a private advisory). If private vulnerability reporting is not
available, contact the maintainers privately through the repository owner
before publishing details. Include affected versions, steps to reproduce, and
potential impact; redact credentials, personal data, and unrelated logs.

The maintainers will acknowledge reports and coordinate a fix and disclosure
timeline on a best-effort basis. Please allow time for investigation and a
release before public disclosure.

## Scope and support

Security fixes are intended for the latest version on the `main` branch and
the latest published release, if any. Older versions may not receive fixes.
The experimental face scanner is **not** a screen-unlock or authentication
security boundary; see [`docs/face-auth.md`](docs/face-auth.md).

Linux Notch processes local mail, clipboard, music, and optional face data.
Do not attach account credentials, mailbox content, face embeddings, private
keys, or other sensitive material to a report.
