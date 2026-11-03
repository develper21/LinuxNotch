import sys

from linux_notch import __version__

HELP = """usage: linux-notch [--toggle] [--settings] [--quit] [--version]

Launch the island in the current graphical session.
  -t, --toggle    Expand or collapse the island
  -s, --settings  Open settings
  -q, --quit      Quit the running instance
  -v, --version   Print version without starting GTK
"""


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"linux-notch {__version__}")
        return 0
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(HELP, end="")
        return 0
    from linux_notch.app import main as run_application

    return run_application()


if __name__ == "__main__":
    raise SystemExit(main())
