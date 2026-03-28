"""
YOLO-based detection for fire and smoke.

Replace `models/yolov8n.pt` with a Roboflow/Kaggle fire–smoke fine-tuned checkpoint
when ready; class-name matching below targets labels like "fire", "smoke", "flame".
"""

from __future__ import annotations

import os
import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

from danger_detection.app.sqlite_store import ObjectRow, SqliteLogWriter
from danger_detection.app.utils import (
    default_coco_person_model_path,
    default_db_path,
    resolve_model_path,
)


# BGR colors for overlays
COLOR_FIRE = (0, 80, 255)
COLOR_SMOKE = (180, 180, 180)
COLOR_PERSON_NORMAL = (80, 180, 80)
COLOR_PERSON_UNUSUAL = (0, 0, 255)
COLOR_GENERAL_OBJECT = (100, 220, 255)  # light cyan — distinct from danger colors

GENERAL_MAX_DRAW_BOXES = 30

# COCO person class id
COCO_CLASS_PERSON = 0


def _env_truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

UNUSUAL_MOVE_MIN_PX = 50.0
UNUSUAL_MOVE_MAX_JUMP_PX = 300.0
UNUSUAL_STREAK_FRAMES = 3
PERSON_MATCH_IOU_MIN = 0.25
PERSON_MATCH_CENTER_MAX_PX = 150.0


@dataclass
class FramePacket:
    """One annotated frame plus optional status for the UI thread."""

    frame_bgr: np.ndarray
    summary: str
    fire_count: int
    smoke_count: int
    unusual_activity: bool = False
    person_count: int = 0
    general_object_count: int = 0


@dataclass
class _PersonTrack:
    last_center: np.ndarray
    last_bbox: np.ndarray
    unusual_streak: int = 0


def _bbox_center(xyxy: np.ndarray) -> np.ndarray:
    x1, y1, x2, y2 = xyxy.astype(np.float64)
    return np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float64)


def bbox_iou_xyxy(a: np.ndarray, b: np.ndarray) -> float:
    ax1, ay1, ax2, ay2 = a.astype(np.float64)
    bx1, by1, bx2, by2 = b.astype(np.float64)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


class PersonMovementTracker:
    """
    Track person bbox centers across frames; flag sustained fast movement as unusual.
    Multi-person: stable numeric track ids via IoU / center matching.
    """

    def __init__(self) -> None:
        self._tracks: Dict[int, _PersonTrack] = {}
        self._next_id = 0

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 0

    def update(self, boxes_xyxy: List[np.ndarray]) -> List[Tuple[int, np.ndarray, bool]]:
        """
        Returns list of (track_id, bbox_xyxy_int, confirmed_unusual) for each detection.
        Resets internal state when boxes_xyxy is empty.
        """
        if not boxes_xyxy:
            self.reset()
            return []

        curr_boxes = [np.asarray(b, dtype=np.float64) for b in boxes_xyxy]
        prev_ids = list(self._tracks.keys())
        prev_bboxes = [self._tracks[i].last_bbox for i in prev_ids]

        n_curr = len(curr_boxes)
        matched_prev: Set[int] = set()
        curr_tid: List[int] = [-1] * n_curr

        for ci in range(n_curr):
            best_pi, best_iou = -1, 0.0
            for pi in range(len(prev_ids)):
                if pi in matched_prev:
                    continue
                iou = bbox_iou_xyxy(curr_boxes[ci], prev_bboxes[pi])
                if iou > best_iou:
                    best_iou = iou
                    best_pi = pi
            if best_iou >= PERSON_MATCH_IOU_MIN and best_pi >= 0:
                curr_tid[ci] = prev_ids[best_pi]
                matched_prev.add(best_pi)

        for ci in range(n_curr):
            if curr_tid[ci] >= 0:
                continue
            cc = _bbox_center(curr_boxes[ci])
            best_pi, best_d = -1, 1e9
            for pi, tid in enumerate(prev_ids):
                if pi in matched_prev:
                    continue
                pc = _bbox_center(prev_bboxes[pi])
                d = float(np.linalg.norm(cc - pc))
                if d < best_d and d < PERSON_MATCH_CENTER_MAX_PX:
                    best_d = d
                    best_pi = pi
            if best_pi >= 0:
                curr_tid[ci] = prev_ids[best_pi]
                matched_prev.add(best_pi)

        for ci in range(n_curr):
            if curr_tid[ci] < 0:
                curr_tid[ci] = self._next_id
                self._next_id += 1

        new_tracks: Dict[int, _PersonTrack] = {}
        out: List[Tuple[int, np.ndarray, bool]] = []
        for ci, box in enumerate(curr_boxes):
            tid = curr_tid[ci]
            c = _bbox_center(box)
            old = self._tracks.get(tid)
            if old is None:
                streak = 0
            else:
                dist = float(np.linalg.norm(c - old.last_center))
                if dist > UNUSUAL_MOVE_MAX_JUMP_PX:
                    streak = 0
                elif dist > UNUSUAL_MOVE_MIN_PX:
                    streak = old.unusual_streak + 1
                else:
                    streak = 0
            confirmed = streak >= UNUSUAL_STREAK_FRAMES
            new_tracks[tid] = _PersonTrack(c, box.copy(), streak)
            out.append((tid, box.astype(np.int32), confirmed))

        self._tracks = new_tracks
        return out


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
        on_alert: Optional[Callable[[int, int], None]] = None,
        alert_debounce_s: float = 0.45,
        person_model_path: Optional[Path] = None,
        enable_person_tracking: bool = True,
    ) -> None:
        self.model_path = Path(model_path or resolve_model_path())
        self._person_model_path = (
            Path(person_model_path) if person_model_path is not None else None
        )
        self._enable_person_tracking = enable_person_tracking
        self.camera_index = camera_index
        self.conf_threshold = conf_threshold
        self._on_alert = on_alert
        self._alert_debounce_s = alert_debounce_s
        self._last_alert_mono: float = 0.0

        self._model: Optional[YOLO] = None
        self._person_model: Optional[YOLO] = None
        self._coco_model_path: Optional[Path] = None
        self._person_tracker = PersonMovementTracker()
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._queue: queue.Queue[Optional[FramePacket]] = queue.Queue(maxsize=1)
        self._error: Optional[str] = None
        self._error_lock = threading.Lock()

        db_raw = os.environ.get("DANGER_DETECTION_DB_PATH", "").strip()
        self._db_path = (
            Path(db_raw).expanduser().resolve()
            if db_raw
            else default_db_path()
        )
        self._sqlite_enabled = _env_truthy("DANGER_DETECTION_SQLITE", "1")
        self._log_objects_enabled = _env_truthy("DANGER_DETECTION_LOG_OBJECTS", "1")
        self._log_objects_every_n = max(
            1,
            int(os.environ.get("DANGER_DETECTION_LOG_OBJECTS_EVERY_N_FRAMES", "1")),
        )
        self._sqlite_writer: Optional[SqliteLogWriter] = None
        self._session_id = 0
        self._frame_index = 0

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
        self._person_model = None
        self._coco_model_path = None
        if self._enable_person_tracking:
            coco_path = self._person_model_path or default_coco_person_model_path()
            if coco_path.is_file():
                self._person_model = YOLO(str(coco_path))
                self._coco_model_path = coco_path.resolve()

    def _log_flow(
        self,
        event_type: str,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._sqlite_writer is None:
            return
        self._sqlite_writer.log_flow(
            self._session_id, event_type, message, metadata
        )

    def _rows_from_results(self, results, model_name: str) -> List[ObjectRow]:
        rows: List[ObjectRow] = []
        now = time.time()
        iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        sid = self._session_id
        fi = self._frame_index
        for r in results:
            if r.boxes is None:
                continue
            names: Dict[int, str] = r.names or {}
            for box in r.boxes:
                conf = float(box.conf[0])
                if conf < self.conf_threshold:
                    continue
                cls_id = int(box.cls[0])
                label = names.get(cls_id, str(cls_id))
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = (float(v) for v in xyxy.tolist())
                rows.append(
                    (
                        iso,
                        now,
                        sid,
                        fi,
                        model_name,
                        cls_id,
                        label,
                        conf,
                        x1,
                        y1,
                        x2,
                        y2,
                    )
                )
        return rows

    def _draw_general_objects(
        self,
        frame_bgr: np.ndarray,
        results,
        max_boxes: int = GENERAL_MAX_DRAW_BOXES,
    ) -> Tuple[np.ndarray, int]:
        """Draw COCO detections except person (person overlay drawn separately)."""
        out = frame_bgr
        names0: Dict[int, str] = {}
        if results:
            names0 = results[0].names or {}
        candidates: List[Tuple[float, Any]] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                if float(box.conf[0]) < self.conf_threshold:
                    continue
                if int(box.cls[0]) == COCO_CLASS_PERSON:
                    continue
                candidates.append((float(box.conf[0]), box))
        candidates.sort(key=lambda x: -x[0])
        count = len(candidates)
        for conf, box in candidates[:max_boxes]:
            xyxy = box.xyxy[0].cpu().numpy().astype(int)
            x1, y1, x2, y2 = [int(v) for v in xyxy.flatten().tolist()]
            cv2.rectangle(out, (x1, y1), (x2, y2), COLOR_GENERAL_OBJECT, 1)
            cid = int(box.cls[0])
            cap = f"{names0.get(cid, cid)} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(
                cap, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1
            )
            cv2.rectangle(
                out, (x1, y1 - th - 5), (x1 + tw + 2, y1), COLOR_GENERAL_OBJECT, -1
            )
            cv2.putText(
                out,
                cap,
                (x1 + 1, y1 - 3),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (20, 20, 20),
                1,
                cv2.LINE_AA,
            )
        return out, count

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

    def _extract_person_boxes(self, results) -> List[np.ndarray]:
        boxes: List[np.ndarray] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                if int(box.cls[0]) != COCO_CLASS_PERSON:
                    continue
                if float(box.conf[0]) < self.conf_threshold:
                    continue
                boxes.append(box.xyxy[0].cpu().numpy())
        return boxes

    def _draw_person_activity(
        self,
        frame_bgr: np.ndarray,
        person_draw: List[Tuple[int, np.ndarray, bool]],
    ) -> Tuple[np.ndarray, bool]:
        out = frame_bgr
        any_unusual = False
        for tid, xyxy, unusual in person_draw:
            x1, y1, x2, y2 = [int(v) for v in xyxy.flatten().tolist()]
            color = COLOR_PERSON_UNUSUAL if unusual else COLOR_PERSON_NORMAL
            if unusual:
                any_unusual = True
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"id{tid}"
            (tw, th), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
            )
            cv2.rectangle(out, (x1, y1 - th - 6), (x1 + tw + 3, y1), color, -1)
            cv2.putText(
                out,
                label,
                (x1 + 1, y1 - 3),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        if any_unusual:
            banner = "UNUSUAL ACTIVITY DETECTED"
            fs = 0.65
            thickness = 2
            (tw, th), _ = cv2.getTextSize(
                banner, cv2.FONT_HERSHEY_DUPLEX, fs, thickness
            )
            pad = 8
            x0, y0 = 10, 36
            cv2.rectangle(
                out,
                (x0 - pad, y0 - th - pad),
                (x0 + tw + pad * 2, y0 + pad),
                (20, 20, 100),
                -1,
            )
            cv2.putText(
                out,
                banner,
                (x0, y0),
                cv2.FONT_HERSHEY_DUPLEX,
                fs,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
            )
        return out, any_unusual

    def _worker(self) -> None:
        assert self._model is not None
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            err = f"Could not open camera index {self.camera_index}"
            self.set_error(err)
            self._log_flow("camera_error", err, None)
            return
        self.set_error(None)
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok:
                self.set_error("Camera read failed")
                self._log_flow("camera_error", "Camera read failed", None)
                break
            try:
                results = self._model.predict(
                    source=frame,
                    verbose=False,
                    conf=self.conf_threshold,
                )
                annotated, fc, sc = self._draw_detections(frame, results)

                general_object_count = 0
                person_count = 0
                unusual_flag = False
                if self._person_model is not None:
                    pr = self._person_model.predict(
                        source=frame,
                        verbose=False,
                        conf=self.conf_threshold,
                    )
                    annotated, general_object_count = self._draw_general_objects(
                        annotated, pr
                    )
                    pboxes = self._extract_person_boxes(pr)
                    person_count = len(pboxes)
                    pdraw = self._person_tracker.update(pboxes)
                    annotated, unusual_flag = self._draw_person_activity(
                        annotated, pdraw
                    )
                    if (
                        self._sqlite_writer
                        and self._log_objects_enabled
                        and (self._frame_index % self._log_objects_every_n == 0)
                    ):
                        batch: List[ObjectRow] = []
                        batch.extend(
                            self._rows_from_results(results, "fire_smoke")
                        )
                        batch.extend(
                            self._rows_from_results(pr, "coco_yolov8n")
                        )
                        self._sqlite_writer.log_objects(batch)
                else:
                    self._person_tracker.reset()
                    if (
                        self._sqlite_writer
                        and self._log_objects_enabled
                        and (self._frame_index % self._log_objects_every_n == 0)
                    ):
                        self._sqlite_writer.log_objects(
                            self._rows_from_results(results, "fire_smoke")
                        )

                parts: List[str] = []
                if fc:
                    parts.append(f"fire: {fc}")
                if sc:
                    parts.append(f"smoke: {sc}")
                if general_object_count:
                    parts.append(f"objects: {general_object_count}")
                if person_count:
                    parts.append(f"persons: {person_count}")
                if unusual_flag:
                    parts.append("unusual activity")
                summary = ", ".join(parts) if parts else "no fire/smoke"
                packet = FramePacket(
                    frame_bgr=annotated,
                    summary=summary,
                    fire_count=fc,
                    smoke_count=sc,
                    unusual_activity=unusual_flag,
                    person_count=person_count,
                    general_object_count=general_object_count,
                )
                if self._on_alert and (fc > 0 or sc > 0):
                    now = time.monotonic()
                    if now - self._last_alert_mono >= self._alert_debounce_s:
                        self._last_alert_mono = now
                        try:
                            self._on_alert(fc, sc)
                        except Exception:
                            pass
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
                self._frame_index += 1
            except Exception as exc:
                self._log_flow(
                    "detection_loop_error",
                    str(exc),
                    {"type": type(exc).__name__},
                )
                self.set_error(str(exc))
                break
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.load_model()
        self._person_tracker.reset()
        self._session_id = int(time.time() * 1000) % (10**9)
        self._frame_index = 0
        self._sqlite_writer = None
        if self._sqlite_enabled:
            self._sqlite_writer = SqliteLogWriter(self._db_path)
            self._sqlite_writer.start()
            self._log_flow(
                "session_start",
                "detection session started",
                {"camera_index": self.camera_index},
            )
            self._log_flow(
                "model_loaded",
                "weights loaded",
                {
                    "fire_smoke_model": str(self.model_path),
                    "coco_model": (
                        str(self._coco_model_path)
                        if self._coco_model_path
                        else None
                    ),
                },
            )
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
        self._person_tracker.reset()
        if self._sqlite_writer is not None:
            self._log_flow(
                "session_stop",
                "detection session stopped",
                None,
            )
            self._sqlite_writer.close()
            self._sqlite_writer = None
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
