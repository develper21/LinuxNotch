import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import numpy as np
except ImportError:
    np = None

from linux_notch.services import face_engine


class FaceEngineStorageTests(unittest.TestCase):
    @unittest.skipIf(np is None, "NumPy is installed by the optional face extra")
    def test_enrollment_round_trip_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "face" / "embeddings.npy"
            engine = object.__new__(face_engine.FaceEngine)
            engine._np = np
            samples = np.arange(8 * 128, dtype=np.float32).reshape(8, 128)

            engine.save_enrollment(list(samples), path=path)
            loaded = engine.load_enrollment(path)

            np.testing.assert_array_equal(loaded, samples)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(np is None, "NumPy is installed by the optional face extra")
    def test_existing_enrollment_requires_explicit_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "embeddings.npy"
            engine = object.__new__(face_engine.FaceEngine)
            engine._np = np
            first = np.zeros((8, 128), dtype=np.float32)
            second = np.ones((8, 128), dtype=np.float32)
            engine.save_enrollment(list(first), path=path)

            with self.assertRaises(face_engine.FaceEngineError):
                engine.save_enrollment(list(second), path=path)
            engine.save_enrollment(list(second), path=path, replace=True)
            np.testing.assert_array_equal(engine.load_enrollment(path), second)

    @unittest.skipIf(np is None, "NumPy is installed by the optional face extra")
    def test_enrollment_rejects_bad_sample_count_and_invalid_file(self):
        engine = object.__new__(face_engine.FaceEngine)
        engine._np = np
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "embeddings.npy"
            with self.assertRaises(face_engine.FaceEngineError):
                engine.save_enrollment(
                    [np.zeros(128, dtype=np.float32)] * 7, path=path)

            np.save(path, np.zeros((7, 128), dtype=np.float32))
            with self.assertRaises(face_engine.FaceEngineError):
                engine.load_enrollment(path)

    @unittest.skipIf(np is None, "NumPy is installed by the optional face extra")
    def test_match_uses_best_cosine_score_and_validates_threshold(self):
        engine = object.__new__(face_engine.FaceEngine)
        engine._np = np
        engine._cv = SimpleNamespace(FaceRecognizerSF_FR_COSINE=0)

        class FakeRecognizer:
            def __init__(self):
                self.scores = iter([0.31, 0.62, 0.44])

            def match(self, _query, _reference, _distance):
                return next(self.scores)

        engine.recognizer = FakeRecognizer()
        enrolled = np.zeros((3, 128), dtype=np.float32)
        matched, score = engine.match(np.zeros(128), enrolled, 0.45)
        self.assertTrue(matched)
        self.assertEqual(score, 0.62)
        with self.assertRaises(face_engine.FaceEngineError):
            engine.match(np.zeros(128), enrolled, float("nan"))


class FaceModelDownloadTests(unittest.TestCase):
    def test_model_download_verifies_checksum_and_restricts_permissions(self):
        content = b"trusted model bytes"
        asset = face_engine.ModelAsset(
            filename="model.onnx",
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
            url="https://models.invalid/model.onnx",
        )
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                face_engine.urllib.request, "urlopen",
                return_value=io.BytesIO(content),
            ) as urlopen:
                path = face_engine._download_asset(asset, Path(directory))

            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            urlopen.assert_called_once()

    def test_bad_model_download_is_discarded(self):
        asset = face_engine.ModelAsset(
            filename="model.onnx",
            sha256="0" * 64,
            size=4,
            url="https://models.invalid/model.onnx",
        )
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                face_engine.urllib.request, "urlopen",
                return_value=io.BytesIO(b"bad!"),
            ):
                with self.assertRaises(face_engine.FaceEngineError):
                    face_engine._download_asset(asset, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
