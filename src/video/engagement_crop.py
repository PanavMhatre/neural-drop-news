from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

_face_cascade: cv2.CascadeClassifier | None = None


def _get_face_cascade() -> cv2.CascadeClassifier:
    """Lazy-load once — the Haar cascade XML ships inside opencv-python(-headless)
    itself, no extra download or dependency needed."""
    global _face_cascade
    if _face_cascade is None:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(path)
    return _face_cascade


def _detect_face_x_centers(frame_bgr: np.ndarray) -> list[float]:
    """Return face-center x-positions in the ORIGINAL frame's pixel coordinates."""
    h, w = frame_bgr.shape[:2]
    # Downscale for speed — Haar cascades are already fast, but detection
    # accuracy doesn't need full resolution and this runs on every sampled frame.
    detect_w = 480
    scale = detect_w / w if w > detect_w else 1.0
    small = cv2.resize(frame_bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else frame_bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    faces = _get_face_cascade().detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(30, 30))
    return [(x + fw / 2) / scale for (x, y, fw, fh) in faces]


def _frame_score(gray: np.ndarray) -> float:
    edges = cv2.Laplacian(gray, cv2.CV_64F).var()
    contrast = float(gray.std())
    brightness = float(gray.mean())
    brightness_penalty = 0.35 if brightness < 35 or brightness > 235 else 1.0
    return (edges * 0.75 + contrast * 3.0) * brightness_penalty


def _sample_frames(video_path: Path, start: float = 0.0, duration: float = 30.0, samples: int = 12) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    total_duration = total_frames / fps if fps else duration
    end = min(start + duration, total_duration)
    if end <= start:
        end = start + duration

    frames: list[np.ndarray] = []
    for t in np.linspace(start, max(start, end - 0.1), samples):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t) * 1000)
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def engagement_crop_x(
    video_path: str | Path,
    target_h: int,
    target_w: int = 1080,
    start: float = 0.0,
    duration: float = 30.0,
) -> float:
    """
    Score candidate horizontal crop positions for detail/motion and return the
    best one as a 0.0-1.0 fraction of the available crop range (0.0 = left
    edge, 0.5 = center, 1.0 = right edge) — independent of whatever actual
    scale (including any zoom effect) a caller later renders at.

    If a face is detected in the sampled frames, it takes priority over the
    detail/motion heuristic — a landscape source with a person centered in a
    wide shot was otherwise getting cropped to whatever background object had
    the most texture, sometimes cutting the actual speaker out of frame
    entirely. Falls back to the detail/motion score when no face is found
    (charts, screen recordings, b-roll with no people in it).
    """
    frames = _sample_frames(Path(video_path), start=start, duration=duration)
    if not frames:
        return 0.5

    height, width = frames[0].shape[:2]
    scaled_w = int(round(width * (target_h / height)))
    max_x = max(0, scaled_w - target_w)
    if max_x <= 0:
        return 0.5

    face_x_centers: list[float] = []
    for frame in frames:
        face_x_centers.extend(_detect_face_x_centers(frame))
    if face_x_centers:
        # Median is robust to an occasional false-positive detection —
        # center the crop window on where faces actually are, in the same
        # scaled coordinate space the candidates below use.
        face_x_scaled = float(np.median(face_x_centers)) * (scaled_w / width)
        best_x = int(round(face_x_scaled - target_w / 2))
        best_x = max(0, min(best_x, max_x))
        return best_x / max_x

    candidate_count = 9
    candidates = np.linspace(0, max_x, candidate_count)
    scores = np.zeros(candidate_count, dtype=np.float64)
    previous: list[np.ndarray | None] = [None] * candidate_count

    for frame in frames:
        for i, scaled_x in enumerate(candidates):
            src_x = int(round(scaled_x / scaled_w * width))
            src_w = int(round(target_w / scaled_w * width))
            src_x = max(0, min(src_x, width - src_w))
            crop = frame[:, src_x:src_x + src_w]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (180, 180), interpolation=cv2.INTER_AREA)

            score = _frame_score(small)
            if previous[i] is not None:
                motion = cv2.absdiff(small, previous[i]).mean()
                score += motion * 18.0
            previous[i] = small

            # Keep a small center bias so presenter/keynote shots do not drift
            # to empty edges when motion is similar across the frame.
            center_distance = abs((scaled_x + target_w / 2) - (scaled_w / 2)) / (scaled_w / 2)
            scores[i] += score * (1.0 - center_distance * 0.12)

    best_x = int(round(float(candidates[int(scores.argmax())])))
    best_x = max(0, min(best_x, max_x))
    return best_x / max_x


def engagement_window_start(
    video_path: str | Path,
    duration: float,
    max_scan_seconds: float = 90.0,
) -> float:
    """
    Pick a strong opening window by scanning for detail and motion. This is
    conservative: it avoids title slates/blank frames but does not invent cuts.
    """
    path = Path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 0.0

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    total_duration = total_frames / fps if fps else duration
    scan_duration = min(max_scan_seconds, max(0.0, total_duration - duration))
    if scan_duration <= 1:
        cap.release()
        return 0.0

    sample_times = np.arange(0, scan_duration, 1.0)
    frame_scores: list[float] = []
    previous = None
    for t in sample_times:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, frame = cap.read()
        if not ok:
            frame_scores.append(0.0)
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (240, 135), interpolation=cv2.INTER_AREA)
        score = _frame_score(small)
        if previous is not None:
            score += cv2.absdiff(small, previous).mean() * 18.0
        previous = small
        frame_scores.append(score)
    cap.release()

    window = max(1, int(round(duration)))
    if len(frame_scores) <= window:
        return 0.0
    sums = np.convolve(np.asarray(frame_scores), np.ones(window), mode="valid")
    return float(int(sums.argmax()))
