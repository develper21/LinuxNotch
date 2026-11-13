"""Local YuNet/SFace face embeddings for the opt-in face-engine experiment."""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_REVISION = "48b10fa505aeb51fbd127fc60a5c660040e823b7"
FACE_DIR = Path(
    os.environ.get(
        "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
    )
) / "linux-notch" / "face"
MODEL_DIR = FACE_DIR / "models"
EMBEDDINGS_PATH = FACE_DIR / "embeddings.npy"
EMBEDDING_SIZE = 128
MIN_ENROLLMENT_SAMPLES = 8
MAX_ENROLLMENT_SAMPLES = 10
DEFAULT_THRESHOLD = 0.45


@dataclass(frozen=True)
class ModelAsset:
    filename: str
    sha256: str
    size: int
    url: str


MODEL_ASSETS = (
    ModelAsset(
        filename="face_detection_yunet_2023mar.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        size=232_589,
        url=(
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
            f"{MODEL_REVISION}/models/face_detection_yunet/"
            "face_detection_yunet_2023mar.onnx"
        ),
    ),
    ModelAsset(
        filename="face_recognition_sface_2021dec.onnx",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        size=38_696_353,
        url=(
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
            f"{MODEL_REVISION}/models/face_recognition_sface/"
            "face_recognition_sface_2021dec.onnx"
        ),
    ),
)


class FaceEngineError(RuntimeError):
    """An expected face-engine, model, camera, or storage error."""


@dataclass(frozen=True)
class FaceObservation:
    embedding: Any
    box: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float], ...]
    confidence: float


def _ensure_private_directory(path: Path) -> None:
    try:
        if path.is_symlink():
            raise FaceEngineError(
                f"Refusing to use symlinked face-data directory: {path}")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as error:
        raise FaceEngineError(
            f"Could not secure face-data directory {path}: {error}") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_asset(asset: ModelAsset, directory: Path) -> Path:
    target = directory / asset.filename
    if target.is_symlink():
        raise FaceEngineError(f"Refusing to replace symlinked model file: {target}")
    if (
        target.is_file()
        and target.stat().st_size == asset.size
        and _sha256_file(target) == asset.sha256
    ):
        os.chmod(target, 0o600)
        return target

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{asset.filename}.", suffix=".part", dir=directory)
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with os.fdopen(fd, "wb") as output:
            request = urllib.request.Request(
                asset.url, headers={"User-Agent": "LinuxNotch face-engine"})
            with urllib.request.urlopen(request, timeout=30) as response:
                while chunk := response.read(1024 * 1024):
                    downloaded += len(chunk)
                    if downloaded > asset.size:
                        raise FaceEngineError(
                            f"Model download exceeded expected size: {asset.filename}")
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        if downloaded != asset.size or digest.hexdigest() != asset.sha256:
            raise FaceEngineError(
                f"Model verification failed for {asset.filename}; "
                "downloaded file was discarded.")
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, target)
    except OSError as error:
        raise FaceEngineError(
            f"Could not download {asset.filename}: {error}") from error
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return target


def download_models(model_dir: Path = MODEL_DIR) -> list[Path]:
    """Download the pinned OpenCV Zoo models and verify their hashes."""
    _ensure_private_directory(model_dir.parent)
    _ensure_private_directory(model_dir)
    return [_download_asset(asset, model_dir) for asset in MODEL_ASSETS]


def validate_threshold(threshold: float) -> float:
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise FaceEngineError("Threshold must be a finite value between 0 and 1.")
    return threshold


class FaceEngine:
    def __init__(
        self,
        model_dir: Path = MODEL_DIR,
        cv_module: Any | None = None,
        np_module: Any | None = None,
    ) -> None:
        if cv_module is None or np_module is None:
            try:
                import cv2
                import numpy
            except ImportError as error:
                raise FaceEngineError(
                    "Face-engine dependencies are missing. Install with "
                    "`pip install -e '.[face]'`."
                ) from error
            cv_module = cv_module or cv2
            np_module = np_module or numpy

        self._cv = cv_module
        self._np = np_module
        paths = [
            (model_dir / asset.filename, asset)
            for asset in MODEL_ASSETS
        ]
        missing = [
            path.name for path, _asset in paths
            if not path.is_file()
        ]
        if missing:
            raise FaceEngineError(
                "Face models are missing: " + ", ".join(missing)
                + ". Run `notch-face-test download-models`."
            )
        for path, asset in paths:
            try:
                valid = (
                    path.stat().st_size == asset.size
                    and _sha256_file(path) == asset.sha256
                )
                if valid:
                    os.chmod(path, 0o600)
            except OSError as error:
                raise FaceEngineError(
                    f"Could not verify model {path.name}: {error}") from error
            if not valid:
                raise FaceEngineError(
                    f"Model integrity check failed for {path.name}. "
                    "Run `notch-face-test download-models` again.")
        try:
            self.detector = self._cv.FaceDetectorYN.create(
                str(paths[0][0]), "", (320, 320), 0.9, 0.3, 5000)
            self.recognizer = self._cv.FaceRecognizerSF.create(
                str(paths[1][0]), "")
        except self._cv.error as error:
            raise FaceEngineError(f"Could not load face models: {error}") from error

    def observe(self, frame: Any) -> list[FaceObservation]:
        if frame is None or len(frame.shape) < 2:
            raise FaceEngineError("Camera returned an invalid frame.")
        try:
            height, width = frame.shape[:2]
            self.detector.setInputSize((width, height))
            _status, faces = self.detector.detect(frame)
            if faces is None:
                return []

            observations = []
            for face in faces:
                aligned = self.recognizer.alignCrop(frame, face[:-1])
                feature = self._np.asarray(
                    self.recognizer.feature(aligned), dtype=self._np.float32
                ).reshape(-1)
                if feature.shape != (EMBEDDING_SIZE,):
                    raise FaceEngineError(
                        f"Unexpected SFace embedding size: {feature.size}.")
                if not self._np.isfinite(feature).all():
                    raise FaceEngineError("SFace produced a non-finite embedding.")
                if float(self._np.linalg.norm(feature)) <= 1e-8:
                    raise FaceEngineError("SFace produced an empty embedding.")
                landmarks = tuple(
                    (float(face[offset]), float(face[offset + 1]))
                    for offset in (4, 6, 8, 10, 12)
                )
                observations.append(FaceObservation(
                    embedding=feature.copy(),
                    box=tuple(float(value) for value in face[:4]),
                    landmarks=landmarks,
                    confidence=float(face[14]),
                ))
            return observations
        except self._cv.error as error:
            raise FaceEngineError(f"OpenCV face processing failed: {error}") from error

    def load_enrollment(self, path: Path = EMBEDDINGS_PATH) -> Any:
        if path.is_symlink():
            raise FaceEngineError(f"Refusing to read symlinked face data: {path}")
        if not path.is_file():
            raise FaceEngineError(
                "No face enrollment exists. Run `notch-face-test enroll` first.")
        _ensure_private_directory(path.parent)
        try:
            if path.stat().st_size > 8192:
                raise FaceEngineError("Face enrollment file is unexpectedly large.")
            os.chmod(path, 0o600)
            embeddings = self._np.load(path, allow_pickle=False)
        except (OSError, ValueError) as error:
            raise FaceEngineError(f"Could not read face enrollment: {error}") from error
        if (
            not isinstance(embeddings, self._np.ndarray)
            or embeddings.ndim != 2
            or embeddings.shape[1] != EMBEDDING_SIZE
            or not MIN_ENROLLMENT_SAMPLES
            <= embeddings.shape[0]
            <= MAX_ENROLLMENT_SAMPLES
            or embeddings.dtype != self._np.float32
            or not self._np.isfinite(embeddings).all()
        ):
            raise FaceEngineError(
                "Face enrollment has an invalid shape or contains invalid data.")
        return embeddings

    def save_enrollment(
        self,
        embeddings: list[Any],
        path: Path = EMBEDDINGS_PATH,
        replace: bool = False,
    ) -> None:
        if path.exists() and not replace:
            raise FaceEngineError(
                "Face enrollment already exists. Use --replace to replace it.")
        matrix = self._np.asarray(embeddings, dtype=self._np.float32)
        if (
            matrix.ndim != 2
            or matrix.shape[1] != EMBEDDING_SIZE
            or not MIN_ENROLLMENT_SAMPLES
            <= matrix.shape[0]
            <= MAX_ENROLLMENT_SAMPLES
            or not self._np.isfinite(matrix).all()
        ):
            raise FaceEngineError(
                f"Enrollment needs {MIN_ENROLLMENT_SAMPLES} to "
                f"{MAX_ENROLLMENT_SAMPLES} valid embeddings.")

        _ensure_private_directory(path.parent)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".embeddings.", suffix=".npy", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as output:
                self._np.save(output, matrix, allow_pickle=False)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, path)
        except OSError as error:
            raise FaceEngineError(f"Could not save face enrollment: {error}") from error
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def match(
        self,
        embedding: Any,
        enrolled: Any,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> tuple[bool, float]:
        threshold = validate_threshold(threshold)
        query = self._np.asarray(
            embedding, dtype=self._np.float32).reshape(1, -1)
        if query.shape[1] != EMBEDDING_SIZE:
            raise FaceEngineError("Query embedding has an invalid size.")
        if (
            enrolled.ndim != 2
            or enrolled.shape[1] != EMBEDDING_SIZE
            or not self._np.isfinite(enrolled).all()
        ):
            raise FaceEngineError("Stored face embeddings are invalid.")
        try:
            scores = [
                float(self.recognizer.match(
                    query,
                    self._np.asarray(
                        reference, dtype=self._np.float32).reshape(1, -1),
                    self._cv.FaceRecognizerSF_FR_COSINE,
                ))
                for reference in enrolled
            ]
        except self._cv.error as error:
            raise FaceEngineError(f"SFace comparison failed: {error}") from error
        if not scores or not all(math.isfinite(score) for score in scores):
            raise FaceEngineError("SFace returned an invalid similarity score.")
        best_score = max(scores)
        return best_score >= threshold, best_score
