"""
In-memory log of hazard detections for the citizen web app to fetch.

Populated when the desktop app POSTs to /internal/alert or when the server
runs its own camera (optional).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass
class DetectionLogEntry:
    ts: float
    fire: int
    smoke: int
    source: str

    def to_json(self) -> Dict[str, Any]:
        dt = datetime.fromtimestamp(self.ts, tz=timezone.utc)
        return {
            "ts": self.ts,
            "iso": dt.isoformat().replace("+00:00", "Z"),
            "fire": self.fire,
            "smoke": self.smoke,
            "source": self.source,
            "summary": _summary(self.fire, self.smoke),
        }


def _summary(fire: int, smoke: int) -> str:
    parts: List[str] = []
    if fire > 0:
        parts.append(f"fire ×{fire}")
    if smoke > 0:
        parts.append(f"smoke ×{smoke}")
    return ", ".join(parts) if parts else "hazard"


class AlertLog:
    def __init__(self, max_entries: int = 500) -> None:
        self._lock = threading.Lock()
        self._entries: deque[DetectionLogEntry] = deque(maxlen=max_entries)

    def append(self, fire: int, smoke: int, source: str) -> None:
        if fire <= 0 and smoke <= 0:
            return
        with self._lock:
            self._entries.append(
                DetectionLogEntry(
                    ts=time.time(),
                    fire=fire,
                    smoke=smoke,
                    source=source,
                )
            )

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._lock:
            items = list(self._entries)[-limit:]
        # newest first
        return [e.to_json() for e in reversed(items)]

    def clear(self) -> int:
        """Remove all entries. Returns how many were cleared."""
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n


alert_log = AlertLog()
