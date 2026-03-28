"""
FastAPI + WebSocket: push fire/smoke alerts to citizen notification clients.

Citizens only subscribe over WebSocket — they do not start/stop detection.

Desktop app + web: run uvicorn with DANGER_DETECTION_PWA_AUTO_START=0 (default),
start the Tkinter app for the camera; it POSTs to /internal/alert and the PWA
receives the same alerts over WebSocket.

Citizen-only (no desktop): set DANGER_DETECTION_PWA_AUTO_START=1 so the server
runs the camera + YOLO itself.

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
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from danger_detection.app.alert_log import alert_log
from danger_detection.app.detector import FireSmokeDetector

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DIST = REPO_ROOT / "web" / "dist"

alert_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
active_clients: Set[WebSocket] = set()
_detector: Optional[FireSmokeDetector] = None
_detector_lock = threading.Lock()


def _push_alert(fire: int, smoke: int, *, source: str = "system") -> None:
    if fire <= 0 and smoke <= 0:
        return
    alert_log.append(fire, smoke, source)
    alert_queue.put(
        {
            "type": "alert",
            "fire": fire,
            "smoke": smoke,
            "ts": time.time(),
            "source": source,
        }
    )


def get_detector() -> FireSmokeDetector:
    global _detector
    with _detector_lock:
        if _detector is None:

            def _on_server(f: int, s: int) -> None:
                _push_alert(f, s, source="server_camera")

            _detector = FireSmokeDetector(on_alert=_on_server)
        return _detector


def stop_detector_if_running() -> None:
    global _detector
    with _detector_lock:
        if _detector is not None:
            _detector.stop()


def _env_truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class AlertIngest(BaseModel):
    fire: int = Field(0, ge=0)
    smoke: int = Field(0, ge=0)


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
    # Default 0: Tkinter desktop usually owns the camera and POSTs to /internal/alert.
    if _env_truthy("DANGER_DETECTION_PWA_AUTO_START", "0"):
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


@app.delete("/api/events")
def clear_detection_events_delete() -> Dict[str, Any]:
    """
    Clear the in-memory hazard log (REST). Prefer POST /api/events/clear from the
    web app — some proxies and service workers mishandle DELETE on the same path
    as GET.
    """
    cleared = alert_log.clear()
    return {"ok": True, "cleared": cleared}


@app.post("/api/events/clear")
def clear_detection_events_post() -> Dict[str, Any]:
    """
    Clear the in-memory hazard log. Used by the PWA (POST avoids 405 from some
    static / SW setups).
    """
    cleared = alert_log.clear()
    return {"ok": True, "cleared": cleared}


@app.get("/api/events")
def list_detection_events(limit: int = 50) -> Dict[str, Any]:
    """
    Public log of hazard events (from the desktop detector via POST /internal/alert).
    Newest first. The web app polls this to show history alongside live WebSocket alerts.
    """
    return {"events": alert_log.recent(limit=limit)}


@app.post("/internal/alert")
async def ingest_alert_from_desktop(request: Request, body: AlertIngest) -> Dict[str, Any]:
    """Receive detections from the Tkinter app; fan out to WebSocket clients."""
    expected = os.environ.get("DANGER_DETECTION_ALERT_TOKEN", "").strip()
    if expected:
        got = request.headers.get("X-Alert-Token", "")
        if got != expected:
            raise HTTPException(status_code=403, detail="Invalid alert token")

    if body.fire <= 0 and body.smoke <= 0:
        return {"ok": False, "reason": "no hazard counts"}

    _push_alert(body.fire, body.smoke, source="desktop_app")
    return {"ok": True}


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
        # Use receive_text(), not receive(): after a disconnect, raw receive()
        # returns a disconnect message and the next receive() raises RuntimeError.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_clients.discard(websocket)


if WEB_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(WEB_DIST), html=True),
        name="citizen_pwa",
    )
else:

    @app.get("/")
    async def root_no_build() -> HTMLResponse:
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>Danger Detection API</title></head>
<body style="font-family:system-ui;max-width:40rem;margin:2rem;line-height:1.5">
<h1>Danger Detection API</h1>
<p>No citizen web app build found at <code>{WEB_DIST}</code>.</p>
<p><strong>One-time:</strong> from the project root run:</p>
<pre style="background:#f4f4f4;padding:1rem">cd web && npm install && npm run build</pre>
<p>Then restart uvicorn — <code>http://localhost:8000</code> will load the PWA.</p>
<p><strong>Desktop camera</strong> (separate window, not this browser tab):</p>
<pre style="background:#f4f4f4;padding:1rem">./venv/bin/python -m danger_detection.app.main</pre>
<p>During development you can use <code>npm run dev</code> in <code>web/</code> and open
<code>http://localhost:5173</code> while this API stays on port 8000.</p>
<p><a href="/health">GET /health</a></p>
</body></html>""",
            media_type="text/html",
        )
