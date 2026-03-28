"""
SQLite audit log: app flow events + per-detection rows.

Writes run on a background thread so the capture loop stays responsive.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ObjectRow = Tuple[
    str,
    float,
    int,
    int,
    str,
    int,
    str,
    float,
    float,
    float,
    float,
    float,
]


def init_db(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_flow_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                created_at_unix REAL NOT NULL,
                session_id INTEGER,
                event_type TEXT NOT NULL,
                message TEXT,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS object_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                created_at_unix REAL NOT NULL,
                session_id INTEGER NOT NULL,
                frame_index INTEGER NOT NULL,
                model TEXT NOT NULL,
                class_id INTEGER,
                class_name TEXT,
                confidence REAL,
                bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL
            );

            CREATE INDEX IF NOT EXISTS idx_object_session_frame
                ON object_detections (session_id, frame_index);
            CREATE INDEX IF NOT EXISTS idx_flow_session
                ON app_flow_events (session_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


class SqliteLogWriter:
    """
    Thread-safe async logging: enqueue flow events and object rows;
    a daemon thread batches inserts.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._q: queue.Queue[Optional[Tuple[str, Any]]] = queue.Queue(maxsize=5000)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            init_db(self._db_path)
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def close(self, timeout: float = 5.0) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(("shutdown", None))
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def log_flow(
        self,
        session_id: int,
        event_type: str,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        try:
            self._q.put_nowait(
                (
                    "flow",
                    (
                        session_id,
                        event_type,
                        message,
                        json.dumps(metadata) if metadata else None,
                    ),
                )
            )
        except queue.Full:
            pass

    def log_objects(self, rows: List[ObjectRow]) -> None:
        if not rows:
            return
        if self._thread is None or not self._thread.is_alive():
            return
        try:
            self._q.put_nowait(("objects", rows))
        except queue.Full:
            pass

    def _run(self) -> None:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        pending_objects: List[ObjectRow] = []
        batch_size = 80
        last_flush = time.monotonic()

        def flush_objects() -> None:
            nonlocal pending_objects
            if not pending_objects:
                return
            conn.executemany(
                """
                INSERT INTO object_detections (
                    created_at, created_at_unix, session_id, frame_index,
                    model, class_id, class_name, confidence,
                    bbox_x1, bbox_y1, bbox_x2, bbox_y2
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                pending_objects,
            )
            conn.commit()
            pending_objects = []

        try:
            while not self._stop.is_set():
                try:
                    item = self._q.get(timeout=0.15)
                except queue.Empty:
                    if time.monotonic() - last_flush > 0.5 and pending_objects:
                        flush_objects()
                        last_flush = time.monotonic()
                    continue

                if item is None:
                    break
                kind, payload = item
                if kind == "shutdown":
                    break
                if kind == "flow":
                    sid, event_type, message, meta_json = payload
                    now = time.time()
                    iso = datetime.fromtimestamp(
                        now, tz=timezone.utc
                    ).isoformat()
                    conn.execute(
                        """
                        INSERT INTO app_flow_events (
                            created_at, created_at_unix, session_id,
                            event_type, message, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (iso, now, sid, event_type, message or "", meta_json),
                    )
                    conn.commit()
                elif kind == "objects":
                    pending_objects.extend(payload)
                    if len(pending_objects) >= batch_size:
                        flush_objects()
                        last_flush = time.monotonic()
        finally:
            if pending_objects:
                flush_objects()
            conn.close()

    @staticmethod
    def get_recent_objects(db_path: Path, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 2000))
        conn = sqlite3.connect(str(db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT * FROM object_detections
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
