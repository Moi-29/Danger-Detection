"""
Forward fire/smoke counts from the desktop detector to the citizen PWA API.

The Tkinter app runs in a different process than uvicorn, so alerts must be
sent over HTTP to the same /internal/alert endpoint the server fans out on WebSockets.

Environment:
  DANGER_DETECTION_ALERT_URL — default http://127.0.0.1:8000/internal/alert
                               Set empty or "0" to disable forwarding.
  DANGER_DETECTION_ALERT_TOKEN — optional shared secret; must match the server.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request


def push_alert_to_pwa(fire: int, smoke: int) -> None:
    if fire <= 0 and smoke <= 0:
        return
    raw = os.environ.get("DANGER_DETECTION_ALERT_URL", "http://127.0.0.1:8000/internal/alert")
    if not raw.strip() or raw.strip().lower() in ("0", "false", "off", "no"):
        return

    url = raw.strip()
    token = os.environ.get("DANGER_DETECTION_ALERT_TOKEN", "").strip()

    def _post() -> None:
        try:
            body = json.dumps({"fire": fire, "smoke": smoke}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            if token:
                req.add_header("X-Alert-Token", token)
            with urllib.request.urlopen(req, timeout=3) as resp:
                resp.read()
        except (urllib.error.URLError, OSError, ValueError):
            pass

    threading.Thread(target=_post, daemon=True).start()
