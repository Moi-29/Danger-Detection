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

## Run the desktop app

From the repo root, with the virtual environment active:

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

## Optional: PWA server + web UI

**Terminal 1** — API + WebSocket (serves the built PWA from `web/dist` if present):

```bash
source venv/bin/activate
export PYTHONPATH="${PWD}"
uvicorn danger_detection.app.pwa_server:app --host 0.0.0.0 --port 8000
```

**Build the web frontend** (once, or after UI changes):

```bash
cd web
npm install
npm run build
cd ..
```

Then open `http://localhost:8000` in a browser.

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
PYTHONPATH=. python -m danger_detection.app.main
```
