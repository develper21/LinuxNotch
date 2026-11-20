import os
import unittest

from linux_notch.ui.terminal import clean_environment


class TerminalEnvironmentTests(unittest.TestCase):
    def test_shell_environment_does_not_inherit_python_or_gtk_overrides(self):
        environment = {
            "PATH": "/venv/bin:/usr/bin",
            "VIRTUAL_ENV": "/venv",
            "PYTHONPATH": "src",
            "PYTHONHOME": "/opt/python",
            "GDK_BACKEND": "wayland",
            "LANG": "en_US.UTF-8",
        }

        result = dict(
            item.split("=", 1) for item in clean_environment(environment))

        self.assertNotIn("VIRTUAL_ENV", result)
        self.assertNotIn("PYTHONPATH", result)
        self.assertNotIn("PYTHONHOME", result)
        self.assertNotIn("GDK_BACKEND", result)
        self.assertEqual(result["PATH"], "/usr/bin")
        self.assertEqual(result["LANG"], "en_US.UTF-8")
        self.assertEqual(result["TERM"], "xterm-256color")
        self.assertEqual(result["COLORTERM"], "truecolor")

    def test_environment_filter_preserves_similarly_named_virtualenvs(self):
        environment = {
            "PATH": os.pathsep.join(
                ("/home/user/venv/bin", "/home/user/venv-other/bin", "/usr/bin")),
            "VIRTUAL_ENV": "/home/user/venv",
        }

        result = dict(item.split("=", 1) for item in clean_environment(environment))

        self.assertEqual(
            result["PATH"],
            os.pathsep.join(("/home/user/venv-other/bin", "/usr/bin")),
        )


if __name__ == "__main__":
    unittest.main()
