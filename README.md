# Danger Detection

**Real-time hazard monitoring with computer vision, citizen-facing alerts, and optional audit logging.**

A desktop security-style monitor detects **fire**, **smoke**, **people**, and **general COCO objects** using YOLOv8. Unusual **person movement** is flagged on-screen. A **FastAPI** backend fans out hazard alerts to a **Progressive Web App (PWA)** so phones and browsers can show the same events without running the camera stack. Optional **SQLite** storage records session flow and per-detection metadata for review or compliance-style demos.

---

## Why this project matters

**Problem:** Public spaces and small venues rarely combine on-site visual hazard detection with a simple way to notify staff or citizens on their own devices.

**Approach:** Run inference locally (low latency, no cloud video upload required for the core loop), push structured alerts over HTTP/WebSocket to a lightweight web client, and keep an optional local database for traceability.

---

## What judges should look for

| Area | What we built |
|------|----------------|
| **Vision** | Two-stage YOLO: dedicated fire/smoke weights + COCO `yolov8n` for people and 80-class “scene context” objects. |
| **Safety UX** | Clear on-frame overlays (fire/smoke vs. general objects vs. person tracks), plus **unusual activity** when a person’s movement exceeds thresholds across multiple frames. |
| **Citizen / ops web** | Installable PWA: **Alerts** (live feed + history) and **Settings** (sound, vibration). Responsive: bottom nav on mobile, sidebar on tablet/desktop. |
| **Real-time alerts** | WebSocket push for instant hazard notices; polling for history. Desktop POSTs to `/internal/alert` when fire/smoke counts are positive. |
| **Audit trail** | SQLite (`app_flow_events`, `object_detections`) with async writer thread so logging does not block the capture loop. |
| **Operations** | Clear local history from the web (`POST /api/events/clear`); configurable logging rate and DB path via environment variables. |

---

## Architecture (high level)

```mermaid
flowchart LR
  subgraph desktop [Desktop — Tkinter]
    CAM[Camera]
    YFS[YOLO fire/smoke]
    YC[YOLO COCO]
    PM[Person movement]
    CAM --> YFS --> UI[Annotated preview]
    YC --> PM --> UI
    YC --> DBQ[SQLite writer queue]
    YFS --> HTTP[POST /internal/alert]
  end
  subgraph server [FastAPI — port 8000]
    API[/api/events]
    WS[/ws]
    LOG[In-memory alert log]
    HTTP --> LOG
    API --> LOG
    LOG --> WS
  end
  subgraph web [Browser PWA]
    PWA[Alerts and Settings UI]
  end
  API --> PWA
  WS --> PWA
  DBQ --> SQLITE[(SQLite file)]
```

- **Desktop** and **API** are separate processes: start **uvicorn first**, then the desktop app (see [Run the full stack](#run-the-full-stack-desktop--web-pwa)).
- **Models** live under `danger_detection/models/` (e.g. fire/smoke weights + `yolov8n.pt` for COCO). Paths are resolved via `danger_detection/app/utils.py`.

---

## Tech stack

| Layer | Technologies |
|--------|----------------|
| Inference | [Ultralytics](https://github.com/ultralytics/ultralytics) YOLOv8, OpenCV, NumPy |
| Desktop UI | Python **Tkinter** + Pillow |
| API | **FastAPI**, **Uvicorn**, WebSocket |
| Web | **React** (Vite), **TypeScript**, PWA (vite-plugin-pwa) |
| Persistence | **SQLite** (optional), in-memory alert list for the PWA |

---

## Prerequisites

- **Python** 3.10+
- **Node.js** 18+ (only to build or develop the `web/` frontend)

---

## Install Python dependencies

From the **repository root**:

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r danger_detection/requirements.txt
```

This installs OpenCV, Ultralytics (PyTorch-backed), Pillow, FastAPI, and Uvicorn.

---

## Run the full stack (desktop + web PWA)

The **desktop app does not start the HTTP server.** The PWA and API live on **port 8000**. The desktop sends hazard POSTs to that server when fire/smoke are detected.

1. **Terminal A — API + static PWA (start first)**

   ```bash
   source venv/bin/activate
   export PYTHONPATH="${PWD}"
   uvicorn danger_detection.app.pwa_server:app --host 127.0.0.1 --port 8000
   ```

2. **Terminal B — desktop monitor**

   ```bash
   source venv/bin/activate
   PYTHONPATH=. python -m danger_detection.app.main
   ```

3. Open **`http://localhost:8000`** in a browser.

**Build the web UI once** (so `uvicorn` can serve `web/dist/`):

```bash
cd web && npm install && npm run build && cd ..
```

**Frontend dev alternative:** `cd web && npm run dev` (e.g. port 5173) talks to `http://localhost:8000` for API/WebSocket by default in development.

**Tip:** The desktop prints a short reminder to stderr about starting uvicorn. Suppress it with: `export DANGER_DETECTION_NO_PWA_TIP=1`.

---

## Run the desktop app only

No web or API:

```bash
export PYTHONPATH="${PWD}"
python -m danger_detection.app.main
```

Linux/macOS one-liner: `PYTHONPATH=. python -m danger_detection.app.main`

Windows (cmd): `set PYTHONPATH=%CD%` then `python -m danger_detection.app.main`

---

## Configuration (environment variables)

| Variable | Purpose |
|----------|---------|
| `DANGER_DETECTION_ALERT_URL` | URL for desktop → server alert POST (default `http://127.0.0.1:8000/internal/alert`). Set empty or `0` to disable. |
| `DANGER_DETECTION_ALERT_TOKEN` | Optional shared secret; must match server `X-Alert-Token` if set on the API. |
| `DANGER_DETECTION_DB_PATH` | Override SQLite file path (default under `danger_detection/data/`). |
| `DANGER_DETECTION_SQLITE` | Enable/disable SQLite (`1` / `0`, default on). |
| `DANGER_DETECTION_LOG_OBJECTS` | Log per-object rows (`1` / `0`). |
| `DANGER_DETECTION_LOG_OBJECTS_EVERY_N_FRAMES` | Sample object logging every N frames (default `1`). |
| `DANGER_DETECTION_PWA_AUTO_START` | If `1`, API process can run the camera detector internally (default `0`; desktop usually owns the camera). |

---

## API overview (for demos)

| Method | Path | Role |
|--------|------|------|
| `GET` | `/health` | Liveness |
| `GET` | `/api/events` | Recent hazard entries (newest first) |
| `POST` | `/api/events/clear` | Clear server-side alert history (used by PWA) |
| `DELETE` | `/api/events` | Same clear action (REST); PWA uses POST for broader compatibility |
| `POST` | `/internal/alert` | Body: `{"fire": n, "smoke": n}` — from desktop; fans out WebSocket + log |
| WebSocket | `/ws` | Push `alert` JSON to connected clients |

---

## Suggested demo script for judges

1. Show **`web/dist`** built and **`uvicorn`** running; open the PWA at `http://localhost:8000` — **Alerts** and **Settings**, connection indicator.
2. Start the **desktop** app; point the camera at the demo feed or a safe test scene.
3. Walk through **on-screen overlays**: fire/smoke, persons, optional general objects, **unusual activity** banner when applicable.
4. Trigger or simulate a hazard (per your demo setup); show **instant PWA** notification path and **detection log** updating.
5. Optionally open the **SQLite** file (e.g. with DB Browser) and show `app_flow_events` / `object_detections` if auditing is part of your pitch.

---

## Limitations and honesty for judging

- Models and thresholds are only as good as weights and calibration; this is a **prototype** for hackathon / research, not certified safety equipment.
- **In-memory** PWA log resets when the API process restarts; SQLite is separate and optional.
- **Unusual activity** is movement-heuristic based, not action recognition; tune thresholds for your scenario.
- Running cloud inference or uploading video is out of scope for the default local loop.

---

## Quick install + run (copy-paste)

```bash
cd Danger-Detection
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r danger_detection/requirements.txt
cd web && npm install && npm run build && cd ..
```

Then **terminal 1:** `PYTHONPATH=. uvicorn danger_detection.app.pwa_server:app --host 127.0.0.1 --port 8000`  
**terminal 2:** `PYTHONPATH=. python -m danger_detection.app.main`  
**Browser:** `http://localhost:8000`

---

## License and contributions

Add your team name, license, and contact here as appropriate for your hackathon submission.
