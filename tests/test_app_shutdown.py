import unittest
from unittest.mock import patch

from linux_notch import app


class ApplicationShutdownTests(unittest.TestCase):
    def test_ctrl_c_returns_interrupt_status_without_propagating(self):
        with (
            patch.object(app, "LostIsland") as application_type,
            patch.object(app.logger, "info") as log_info,
        ):
            application_type.return_value.run.side_effect = KeyboardInterrupt

            self.assertEqual(app.main(), 130)

        log_info.assert_called_once_with(
            "Received Ctrl+C; Linux Notch shut down cleanly.")


if __name__ == "__main__":
    unittest.main()
