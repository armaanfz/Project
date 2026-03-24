# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Magnifier** — a real-time camera magnification web app for visually impaired students. Runs on Raspberry Pi in production; Windows for development.

## Running Locally (Windows)

```bash
pip install -r requirements.txt
python app.py
```

`app.py` launches a Cloudflare tunnel and serves the app. Browse at `http://localhost:5000`.

## Architecture

```
Browser → app.py (Flask + Socket.IO) :5000
           ├─ /stream  → Socket.IO namespace   (camera frames)
           └─ /*       → Flask routes          (UI, routing, tunnel status)
Cloudflare tunnel → :5000
```

**app.py** — Flask + Socket.IO server on `0.0.0.0:5000`. Responsible for:
- Auto-downloading and launching Cloudflare tunnel (`cloudflared`) as a background subprocess
- Serving the three HTML pages: `index.html`, `samples.html`, `remote.html`
- `/tunnel-status` endpoint polled by the frontend to display the public URL
- `/shutdown` endpoint (local requests only, Pi-only) with 30s cooldown
- Camera streaming via Socket.IO `/stream` namespace — background task `_stream_frames()`
- Two quality profiles: `local` (1920×1080, 92% quality) and `remote` (1280×720, 75% quality)
- Forces DirectShow backend (`cv2.CAP_DSHOW`) on Windows to avoid MSMF black-frame bug
- Uses `async_mode='threading'` on Windows, `'gevent'` on Linux/Pi

**Frontend pages:**
- `samples.html` + `static/js/samples.js` — local camera page. Uses `getUserMedia()` → `<video>` → canvas. All zoom/filter/mask logic lives in `samples.js` (~1500 lines).
- `remote.html` — remote stream viewer. Connects to Socket.IO `/stream` namespace, draws JPEG frames to canvas. Same zoom/filter/mask controls as samples.
- `index.html` — home page with tabs, tunnel URL display, and shutdown button.

## Key Design Decisions

- **Socket.IO mode detection**: Host header — `localhost`/`127.0.0.1` → `local` profile, anything else → `remote` profile.
- **Single process**: Flask + Socket.IO runs on port 5000 directly. No separate stream server or proxy layer.
- **Async backend**: `threading` on Windows (dev), `gevent` on Linux/Pi (prod). Set via `SOCKETIO_ASYNC_MODE` env var.
- **Camera release grace period**: Camera is held for 2 seconds after the last client disconnects to avoid rapid off/on during reconnects.
- **Cloudflare quick tunnel** — ephemeral URL, changes every restart. No persistent domain.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `CAMERA_INDEX` | `0` | Camera device index |
| `CAMERA_WIDTH/HEIGHT/FPS` | `1920/1080/30` | Local stream resolution |
| `REMOTE_CAMERA_WIDTH/HEIGHT/FPS` | `1280/720/30` | Remote stream resolution |
| `LOCAL_JPEG_QUALITY` | `92` | Local JPEG quality |
| `REMOTE_JPEG_QUALITY` | `75` | Remote JPEG quality |
| `SHUTDOWN_COOLDOWN_SECONDS` | `30` | Min seconds between shutdown calls |
| `SOCKETIO_ASYNC_MODE` | `threading` (Win) / `gevent` (Linux) | Socket.IO async backend |
| `STREAM_RELEASE_GRACE_SECONDS` | `2.0` | Camera hold time after last client disconnects |

## Testing

```bash
pip install -r requirements-dev.txt   # adds pytest
pytest                                  # run all tests
pytest tests/test_app.py -v            # verbose
```

Tests live in `tests/test_app.py` and cover Flask routes.

## Common Development Tasks

| Task | Command |
|---|---|
| Run full app | `python app.py` |
| Run tests | `pytest` |
| Install runtime deps | `pip install -r requirements.txt` |
| Install dev deps | `pip install -r requirements-dev.txt` |

## Where to Look

| I want to... | Look at... |
|---|---|
| Change zoom/filter/mask logic | `static/js/samples.js` |
| Change remote stream rendering | `templates/remote.html` |
| Add a Flask route | `app.py` |
| Tune camera quality/resolution | `app.py` env-var defaults (`STREAM_PROFILES`) |
| Change tunnel or shutdown logic | `app.py:_start_tunnel()`, `app.py:shutdown()` |
| Change Socket.IO streaming logic | `app.py:_stream_frames()`, `app.py:stream_connect()` |
| Add a route test | `tests/test_app.py` |

## Pi Deployment

Single systemd service running `python app.py` on port 5000. Cloudflare tunnel is managed by app.py itself.
