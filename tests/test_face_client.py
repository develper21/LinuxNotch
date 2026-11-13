import tempfile
import unittest
from pathlib import Path

import numpy as np

from linux_notch.services.face_client import FaceDaemonClient


class FaceDaemonClientTests(unittest.TestCase):
    def test_client_fallback_when_daemon_not_running(self):
        with tempfile.TemporaryDirectory() as directory:
            enrollment = Path(directory) / "embeddings.npy"
            client = FaceDaemonClient(enrollment_path=enrollment)
            self.addCleanup(client.close)

            # Not enrolled initially
            status = client.get_status()
            self.assertFalse(status["enrolled"])
            self.assertEqual(status["sample_count"], 0)

            # Create fake embeddings
            data = np.zeros((8, 128), dtype=np.float32)
            np.save(enrollment, data)

            status = client.get_status()
            self.assertTrue(status["enrolled"])
            self.assertEqual(status["sample_count"], 8)

            # Reset removes file
            res = client.reset()
            self.assertTrue(res)
            self.assertFalse(enrollment.exists())
            self.assertFalse(client.get_status()["enrolled"])


if __name__ == "__main__":
    unittest.main()
