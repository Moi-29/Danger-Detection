"""
YOLO-based detection for fire and smoke.

Replace `models/yolov8n.pt` with a Roboflow/Kaggle fire–smoke fine-tuned checkpoint
when ready; class-name matching below targets labels like "fire", "smoke", "flame".
"""

from __future__ import annotations

import threading
import queue
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

from danger_detection.app.utils import resolve_model_path


# BGR colors for overlays
COLOR_FIRE = (0, 80, 255)
COLOR_SMOKE = (180, 180, 180)


@dataclass
class FramePacket:
    """One annotated frame plus optional status for the UI thread."""

    frame_bgr: np.ndarray
    summary: str
    fire_count: int
    smoke_count: int


class BaseDetector(ABC):
    """Common interface for future detector types (weapons, behavior, etc.)."""

    @abstractmethod
    def load_model(self) -> None:
        ...

    @abstractmethod
    def process_frame(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Return frame with visualizations applied."""


class WeaponDetector(BaseDetector):
    """
    Placeholder for future weapon detection.
    Wire a dedicated YOLO weights file and class map when implementing.
    """

    def load_model(self) -> None:
        raise NotImplementedError("Weapon detection is not implemented yet.")

    def process_frame(self, frame_bgr: np.ndarray) -> np.ndarray:
        raise NotImplementedError("Weapon detection is not implemented yet.")


class AbnormalBehaviorDetector(BaseDetector):
    """Placeholder for future unusual-activity / behavior analysis."""

    def load_model(self) -> None:
        raise NotImplementedError("Abnormal behavior detection is not implemented yet.")

    def process_frame(self, frame_bgr: np.ndarray) -> np.ndarray:
        raise NotImplementedError("Abnormal behavior detection is not implemented yet.")


def _normalize_label(name: str) -> str:
    return name.strip().lower()


def classify_fire_smoke(class_name: str) -> Optional[str]:
    """
    Map a YOLO class name to 'fire' or 'smoke', or None if not a target class.
    Handles common naming from custom datasets.
    COCO's "fire hydrant" is excluded (substring "fire" only).
    """
    n = _normalize_label(class_name)
    if "fire hydrant" in n:
        return None
    if n in {"fire", "flame", "burning"} or "flame" in n or "fire" in n:
        return "fire"
    if n in {"smoke", "smoking"} or "smoke" in n:
        return "smoke"
    return None


class FireSmokeDetector:
    """
    Webcam capture + YOLO inference on a worker thread.
    Annotated frames are exposed via a queue for the Tkinter main thread.
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        camera_index: int = 0,
        conf_threshold: float = 0.35,
    ) -> None:
        self.model_path = Path(model_path or resolve_model_path())
        self.camera_index = camera_index
        self.conf_threshold = conf_threshold

        self._model: Optional[YOLO] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._queue: queue.Queue[Optional[FramePacket]] = queue.Queue(maxsize=1)
        self._error: Optional[str] = None
        self._error_lock = threading.Lock()

    def set_error(self, message: Optional[str]) -> None:
        with self._error_lock:
            self._error = message

    def get_error(self) -> Optional[str]:
        with self._error_lock:
            return self._error

    def load_model(self) -> None:
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Model not found: {self.model_path}. "
                "Place yolov8n.pt there or pass a path to your fine-tuned weights."
            )
        self._model = YOLO(str(self.model_path))

    def _draw_detections(
        self,
        frame_bgr: np.ndarray,
        results,
    ) -> Tuple[np.ndarray, int, int]:
        fire_count = 0
        smoke_count = 0
        out = frame_bgr.copy()
        for r in results:
            names: Dict[int, str] = r.names or {}
            if r.boxes is None:
                continue
            for box in r.boxes:
                conf = float(box.conf[0])
                if conf < self.conf_threshold:
                    continue
                cls_id = int(box.cls[0])
                label = names.get(cls_id, str(cls_id))
                kind = classify_fire_smoke(label)
                if kind is None:
                    continue
                xyxy = box.xyxy[0].cpu().numpy().astype(int)
                x1, y1, x2, y2 = xyxy.tolist()
                color = COLOR_FIRE if kind == "fire" else COLOR_SMOKE
                if kind == "fire":
                    fire_count += 1
                else:
                    smoke_count += 1
                cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
                caption = f"{kind} {conf:.2f}"
                (tw, th), _ = cv2.getTextSize(
                    caption, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                )
                cv2.rectangle(out, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
                cv2.putText(
                    out,
                    caption,
                    (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
        return out, fire_count, smoke_count

    def _worker(self) -> None:
        assert self._model is not None
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            self.set_error(f"Could not open camera index {self.camera_index}")
            return
        self.set_error(None)
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok:
                self.set_error("Camera read failed")
                break
            results = self._model.predict(
                source=frame,
                verbose=False,
                conf=self.conf_threshold,
            )
            annotated, fc, sc = self._draw_detections(frame, results)
            parts: List[str] = []
            if fc:
                parts.append(f"fire: {fc}")
            if sc:
                parts.append(f"smoke: {sc}")
            summary = ", ".join(parts) if parts else "no fire/smoke"
            packet = FramePacket(
                frame_bgr=annotated,
                summary=summary,
                fire_count=fc,
                smoke_count=sc,
            )
            try:
                self._queue.put_nowait(packet)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(packet)
                except queue.Full:
                    pass
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.load_model()
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._cap = None
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def poll_frame(self) -> Optional[FramePacket]:
        """Non-blocking read for the UI thread."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None
