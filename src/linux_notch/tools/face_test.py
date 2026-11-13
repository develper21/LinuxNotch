"""Interactive, local-only camera tests for the experimental face engine."""

from __future__ import annotations

import argparse
import sys
import time

from linux_notch.services.face_engine import (
    DEFAULT_THRESHOLD,
    EMBEDDINGS_PATH,
    MAX_ENROLLMENT_SAMPLES,
    MIN_ENROLLMENT_SAMPLES,
    FaceEngine,
    FaceEngineError,
    download_models,
    validate_threshold,
)

POSES = (
    "look straight ahead",
    "turn slightly to your left",
    "turn slightly to your right",
    "look slightly upward",
    "look slightly downward",
    "turn slightly left, then center",
    "turn slightly right, then center",
    "look straight ahead from a comfortable distance",
    "look slightly upward, then center",
    "look slightly downward, then center",
)
SCAN_TIMEOUT_SECONDS = 8.0
MATCH_SAMPLE_INTERVAL_SECONDS = 0.2


def _open_camera(cv2, camera_index: int):
    camera = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    if not camera.isOpened():
        camera.release()
        raise FaceEngineError(
            f"Could not open camera {camera_index}. Check camera access "
            "and pass --camera with a valid /dev/video index.")
    return camera


def _capture_one(engine: FaceEngine, camera, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    multiple_faces_reported = False
    while time.monotonic() < deadline:
        ok, frame = camera.read()
        if not ok:
            raise FaceEngineError("Camera stopped returning frames.")
        observations = engine.observe(frame)
        if len(observations) == 1:
            return observations[0]
        if len(observations) > 1 and not multiple_faces_reported:
            print("More than one face detected; make sure you are alone.")
            multiple_faces_reported = True
    return None


def _enroll(args: argparse.Namespace) -> int:
    if EMBEDDINGS_PATH.exists() and not args.replace:
        raise FaceEngineError(
            f"Enrollment already exists at {EMBEDDINGS_PATH}. "
            "Pass --replace to replace it.")
    engine = FaceEngine()
    import cv2

    camera = _open_camera(cv2, args.camera)
    embeddings = []
    try:
        for index in range(args.samples):
            pose = POSES[index]
            while True:
                input(
                    f"Sample {index + 1}/{args.samples}: {pose}. "
                    "Press Enter to capture (Ctrl+C to cancel). "
                )
                observation = _capture_one(engine, camera)
                if observation is None:
                    print("No single face found in time; adjust and retry.")
                    continue
                embeddings.append(observation.embedding)
                print("Captured embedding; no camera image was saved.")
                break
    finally:
        camera.release()

    engine.save_enrollment(
        embeddings, path=EMBEDDINGS_PATH, replace=args.replace)
    print(
        f"Saved {len(embeddings)} embeddings to {EMBEDDINGS_PATH} "
        "(directory mode 0700, file mode 0600).")
    return 0


def _check(args: argparse.Namespace) -> int:
    threshold = validate_threshold(args.threshold)
    engine = FaceEngine()
    enrolled = engine.load_enrollment()
    import cv2

    camera = _open_camera(cv2, args.camera)
    scores = []
    deadline = time.monotonic() + SCAN_TIMEOUT_SECONDS
    next_sample_at = 0.0
    multiple_faces_reported = False
    print(
        f"Checking for up to {SCAN_TIMEOUT_SECONDS:.0f} seconds "
        f"(threshold {threshold:.2f}); press Ctrl+C to stop.")
    try:
        while len(scores) < args.frames and time.monotonic() < deadline:
            ok, frame = camera.read()
            if not ok:
                raise FaceEngineError("Camera stopped returning frames.")
            observations = engine.observe(frame)
            if len(observations) > 1:
                if not multiple_faces_reported:
                    print("More than one face detected; make sure you are alone.")
                    multiple_faces_reported = True
                continue
            if not observations:
                continue
            now = time.monotonic()
            if now < next_sample_at:
                continue
            _matched, score = engine.match(
                observations[0].embedding, enrolled, threshold)
            scores.append(score)
            next_sample_at = now + MATCH_SAMPLE_INTERVAL_SECONDS
            print(f"Sample {len(scores)}/{args.frames}: similarity {score:.3f}")
    finally:
        camera.release()

    if not scores:
        print("No face found; no match was made.")
        return 1
    matches = sum(score >= threshold for score in scores)
    required = max(3, len(scores) // 2 + 1)
    matched = matches >= required
    print(
        f"{'MATCH' if matched else 'NO MATCH'}: "
        f"{matches}/{len(scores)} samples met threshold {threshold:.2f}.")
    print("This test never unlocks the screen.")
    return 0 if matched else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local-only YuNet/SFace enrollment and recognition test.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "download-models",
        help="download and SHA-256 verify the pinned OpenCV Zoo models")

    enroll = commands.add_parser(
        "enroll", help="capture 8-10 face embeddings; no images are saved")
    enroll.add_argument("--camera", type=int, default=0)
    enroll.add_argument(
        "--samples",
        type=int,
        choices=range(MIN_ENROLLMENT_SAMPLES, MAX_ENROLLMENT_SAMPLES + 1),
        default=8,
    )
    enroll.add_argument(
        "--replace", action="store_true",
        help="replace an existing local enrollment")

    check = commands.add_parser(
        "check", help="compare a live face against the local enrollment")
    check.add_argument("--camera", type=int, default=0)
    check.add_argument("--frames", type=int, choices=range(3, 11), default=5)
    check.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help="cosine similarity threshold (starting value: 0.45)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "download-models":
            paths = download_models()
            for path in paths:
                print(f"Verified model: {path}")
            return 0
        if args.command == "enroll":
            return _enroll(args)
        if args.command == "check":
            return _check(args)
    except FaceEngineError as error:
        print(f"notch-face-test: {error}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nFace test cancelled; camera was released.", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
