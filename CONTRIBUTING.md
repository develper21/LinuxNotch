# Contributing to Linux Notch

Thanks for considering a contribution. By submitting a patch, you agree to the
Developer Certificate of Origin (DCO), not to a copyright assignment or a
Contributor License Agreement. You keep copyright in your contributions and
license them under the project license and any applicable file-specific
license.

## Before opening a pull request

1. Check open issues and pull requests for related work.
2. Keep changes focused and include tests for behavior changes.
3. Do not include credentials, personal data, generated build output, or
   third-party material unless its license and attribution are clear.
4. Describe user-visible changes and manual checks in the pull request.

## Development setup

Install the native GTK dependencies described in the README, then create an
environment and install the development extras:

```sh
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run checks before submitting:

```sh
ruff check src tests plugins/examples
python -m compileall -q src tests
dbus-run-session -- env PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m linux_notch --version
```

The GTK application needs a logged-in desktop session for interactive
compositor testing. Please state which platform/backend you tested and note
checks you could not run.

## Developer Certificate of Origin

Every non-merge commit in a pull request must include a `Signed-off-by` line
certifying the Developer Certificate of Origin 1.1. Use `git commit -s`; the
name and email in the sign-off must identify you. Do not sign off someone
else's work.

By adding the sign-off, you certify:

```text
Developer Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the
    right to submit it under the open source license indicated in the file; or

(b) The contribution is based upon previous work that, to the best of my
    knowledge, is covered under an appropriate open source license and I have
    the right under that license to submit that work with modifications,
    whether created in whole or in part by me, under the same open source
    license (unless I am permitted to submit under a different license), as
    indicated in the file; or

(c) The contribution was provided directly to me by some other person who
    certified (a), (b) or (c) and I have not modified it.

(d) I understand and agree that this project and the contribution are public
    and that a record of the contribution (including all personal information
    I submit with it, including my sign-off) is maintained indefinitely and
    may be redistributed consistent with this project or the open source
    license(s) involved.
```

## Copyright and project assets

Contributors retain copyright in their code; the DCO does not transfer it to
the maintainer. The main application is MIT-licensed, subject to the upstream
notices and separately licensed components listed in [`NOTICE`](NOTICE) and
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).

The Mochi character and bundled sound assets are not covered by the
application's MIT license. The project records separate permission to include
them with this integration; contributors must use them only as integrated
project assets and must not extract, relicense, or replace their attribution.
This project policy does not expand or change the rights granted by the asset
rights holder. See [`ASSET-ATTRIBUTION.md`](ASSET-ATTRIBUTION.md).
