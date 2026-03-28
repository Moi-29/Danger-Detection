# Danger-Detection

Fire/smoke detection with YOLO (desktop app) and a web PWA for alerts.

## Prerequisites

- **Python** 3.10 or newer  
- **Node.js** 18+ (only if you build or develop the web UI)

## Install Python dependencies

From the **repository root** (`Danger-Detection/`):

```bash
python3 -m venv venv
source venv/bin/activate
```

On **Windows** (PowerShell or Command Prompt):

```cmd
python -m venv venv
venv\Scripts\activate
```

Then install packages:

```bash
pip install --upgrade pip
pip install -r danger_detection/requirements.txt
```

`pip` will pull in `opencv-python`, `ultralytics`, `torch`, `fastapi`, `uvicorn`, and other transitive dependencies.

## Desktop app + web PWA (two terminals)

The **desktop app only** runs the camera and detection. It does **not** start the HTTP server. The **web PWA** loads alerts from `GET /api/events` and WebSocket `/ws` on **port 8000**, and the desktop sends alerts with `POST` to `/internal/alert` on that same server.

So you need **both** running:

1. **Terminal A — API + web (start this first)**  
   From the repo root, with the venv active:

   ```bash
   source venv/bin/activate
   export PYTHONPATH="${PWD}"
   uvicorn danger_detection.app.pwa_server:app --host 127.0.0.1 --port 8000
   ```

2. **Terminal B — Desktop**  

   ```bash
   source venv/bin/activate
   PYTHONPATH=. python -m danger_detection.app.main
   ```

3. Open **`http://localhost:8000`** in a browser for the PWA.

**Build the web UI once** (so the server can serve `web/dist/`):

```bash
cd web && npm install && npm run build && cd ..
```

If you skip the build, uvicorn still serves the API and WebSocket; you can open the PWA from a dev server (`cd web && npm run dev`, usually port 5173) but it must point at the API on port 8000 (default in dev).

**Optional:** `export DANGER_DETECTION_NO_PWA_TIP=1` hides the desktop app’s reminder about starting uvicorn.

---

## Run the desktop app only

If you only need the camera window (no web):

```bash
export PYTHONPATH="${PWD}"
python -m danger_detection.app.main
```

Or one line (Linux/macOS):

```bash
PYTHONPATH=. python -m danger_detection.app.main
```

On **Windows** (cmd):

```cmd
set PYTHONPATH=%CD%
python -m danger_detection.app.main
```

## Push to GitHub

```bash
git status
git add README.md danger_detection/requirements.txt
git add -A
git commit -m "Document setup and Python dependencies"
git push origin main
```

(Use your branch name instead of `main` if different.)

---

**Quick copy-paste (Linux/macOS, fresh clone):**

```bash
cd Danger-Detection
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r danger_detection/requirements.txt
```

Then **terminal 1:** `PYTHONPATH=. uvicorn danger_detection.app.pwa_server:app --host 127.0.0.1 --port 8000`  
**terminal 2:** `PYTHONPATH=. python -m danger_detection.app.main`  
Browser: `http://localhost:8000` (build `web/` first if you want the full PWA from port 8000).
