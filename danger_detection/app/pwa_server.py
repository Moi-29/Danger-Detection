"""
FastAPI + WebSocket: push fire/smoke alerts to citizen notification clients.

Citizens only subscribe over WebSocket — they do not start/stop detection.
By default the server starts the on-device detector when the API boots
(set DANGER_DETECTION_PWA_AUTO_START=0 if you run the desktop app or another
process that owns the camera instead).

Run from repo root:
  uvicorn danger_detection.app.pwa_server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from danger_detection.app.detector import FireSmokeDetector

alert_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
active_clients: Set[WebSocket] = set()
_detector: Optional[FireSmokeDetector] = None
_detector_lock = threading.Lock()


def _push_alert(fire: int, smoke: int) -> None:
    alert_queue.put(
        {
            "type": "alert",
            "fire": fire,
            "smoke": smoke,
            "ts": time.time(),
        }
    )


def get_detector() -> FireSmokeDetector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = FireSmokeDetector(on_alert=_push_alert)
        return _detector


def stop_detector_if_running() -> None:
    global _detector
    with _detector_lock:
        if _detector is not None:
            _detector.stop()


def _env_truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


async def relay_alerts() -> None:
    while True:
        await asyncio.sleep(0.05)
        try:
            while True:
                msg = alert_queue.get_nowait()
                for ws in list(active_clients):
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        active_clients.discard(ws)
        except queue.Empty:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(relay_alerts())
    if _env_truthy("DANGER_DETECTION_PWA_AUTO_START", "1"):
        get_detector().start()
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        stop_detector_if_running()


app = FastAPI(title="Danger Detection PWA API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Citizens subscribe; they only receive alert payloads (no commands)."""
    await websocket.accept()
    active_clients.add(websocket)
    try:
        await websocket.send_json(
            {
                "type": "hello",
                "message": "You will receive hazard alerts here.",
            }
        )
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        pass
    finally:
        active_clients.discard(websocket)
