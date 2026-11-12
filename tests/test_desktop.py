import unittest
from unittest.mock import patch

from linux_notch.desktop.factory import choose_backend
from linux_notch.desktop.floating import FloatingWindowBackend


class BackendSelectionTests(unittest.TestCase):
    @patch("linux_notch.desktop.layer_shell.LayerShellBackend.is_supported", return_value=False)
    def test_unknown_wayland_desktop_uses_floating_fallback(self, _probe):
        backend = choose_backend(
            {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "River"}
        )
        self.assertIsInstance(backend, FloatingWindowBackend)
        self.assertFalse(backend.probe().anchor_top_center)

    @patch("linux_notch.desktop.x11.X11Backend.usable", return_value=False)
    def test_unavailable_x11_backend_uses_floating_fallback(self, _probe):
        backend = choose_backend({"XDG_SESSION_TYPE": "x11", "DISPLAY": ":1"})
        self.assertIsInstance(backend, FloatingWindowBackend)

    @patch("linux_notch.desktop.x11.X11Backend.usable", return_value=False)
    def test_wayland_does_not_select_x11_for_xwayland_display(self, _probe):
        with patch(
            "linux_notch.desktop.layer_shell.LayerShellBackend.is_supported",
            return_value=False,
        ):
            backend = choose_backend(
                {
                    "XDG_SESSION_TYPE": "wayland",
                    "XDG_CURRENT_DESKTOP": "KDE",
                    "DISPLAY": ":0",
                }
            )
        self.assertIsInstance(backend, FloatingWindowBackend)

    @patch("linux_notch.desktop.x11.X11Backend.usable", return_value=True)
    def test_explicit_x11_backend_is_used_in_wayland_session(self, _probe):
        backend = choose_backend(
            {
                "XDG_SESSION_TYPE": "wayland",
                "GDK_BACKEND": "x11",
                "DISPLAY": ":0",
            }
        )
        self.assertEqual(backend.name, "x11")

    def test_empty_environment_uses_floating_fallback(self):
        self.assertIsInstance(choose_backend({}), FloatingWindowBackend)


if __name__ == "__main__":
    unittest.main()
