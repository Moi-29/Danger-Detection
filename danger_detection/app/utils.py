"""Shared helpers for frame handling and paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

ENV_MODEL = "DANGER_DETECTION_MODEL"


def package_root() -> Path:
    """Directory containing `app/` and `models/` (the `danger_detection` package root)."""
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    """Repository root (parent directory of the `danger_detection` package)."""
    return Path(__file__).resolve().parent.parent.parent


def resolve_model_path() -> Path:
    """
    Choose weights in order:
    1. ``DANGER_DETECTION_MODEL`` if set (absolute path, or relative to cwd).
    2. ``app/models/fire_smoke.pt`` (fine-tuned fire/smoke; preferred over COCO ``yolov8n.pt``).
    3. ``danger_detection/models/fire_smoke.pt`` (bundled default when present).
    4. ``app/models/yolov8n.pt`` if present; else first ``*.pt`` in ``app/models/`` (sorted).
    5. ``danger_detection/models/yolov8n.pt``.

    COCO ``yolov8n.pt`` does not include fire/smoke classes; use ``fire_smoke.pt`` for real detection.
    """
    raw = os.environ.get(ENV_MODEL, "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
        return p

    app_models = repo_root() / "app" / "models"
    pkg_models = package_root() / "models"

    for candidate in (app_models / "fire_smoke.pt", pkg_models / "fire_smoke.pt"):
        if candidate.is_file():
            return candidate.resolve()

    preferred = app_models / "yolov8n.pt"
    if preferred.is_file():
        return preferred.resolve()
    if app_models.is_dir():
        candidates = sorted(app_models.glob("*.pt"))
        if candidates:
            return candidates[0].resolve()

    return (pkg_models / "yolov8n.pt").resolve()


def default_model_path() -> Path:
    return resolve_model_path()


def resize_to_fit(
    frame_bgr: np.ndarray,
    max_w: int,
    max_h: int,
) -> Tuple[np.ndarray, float]:
    """
    Resize frame so it fits within max_w x max_h while preserving aspect ratio.
    Returns (resized_frame, scale factor applied to width/height).
    """
    h, w = frame_bgr.shape[:2]
    if w <= max_w and h <= max_h:
        return frame_bgr, 1.0
    scale = min(max_w / w, max_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, scale


def bgr_to_rgb(frame_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
