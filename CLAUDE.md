# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Magnifier** — a real-time camera magnification web app for visually impaired students. Runs on Raspberry Pi in production; Windows for development.

## Running Locally (Windows)

```bash
pip install -r requirements.txt
python app.py
```

`app.py` auto-spawns `stream_server.py` and a Cloudflare tunnel. Browse at `http://localhost:8000`.

`stream_server.py` can also be run standalone: `python stream_server.py`

## Architecture

```
Browser → stream_server.py :8000
           ├─ /ws  → WebSocket handler          (asyncio, camera frames)
           └─ /*   → HTTP proxy → Flask :5000   (UI, routing, tunnel status)
Cloudflare tunnel → :8000
```

**app.py** — Flask server (internal, `127.0.0.1:5000`). Also responsible for:
- Auto-downloading and launching Cloudflare tunnel (`cloudflared`) as a background subprocess
- Spawning `stream_server.py` as a background subprocess
- Serving the three HTML pages: `index.html`, `samples.html`, `remote.html`
- `/tunnel-status` endpoint polled by the frontend to display the public URL
- `/shutdown` endpoint (local requests only, Pi-only) with 30s cooldown

**stream_server.py** — Unified entry point on `0.0.0.0:8000`.
- WebSocket connections to `/ws` are handled directly (camera frames)
- All other HTTP requests are proxied to Flask on port 5000 via `process_request` hook
- Reads from OpenCV camera, encodes JPEG frames, broadcasts to all connected clients
- Binary frame protocol: `[0:8] int64 timestamp (ms) + [8:] JPEG bytes`
- Two quality profiles: `local` (1920×1080, 92% quality) and `remote` (1280×720, 75% quality)
- Profile selection is dynamic: uses `remote` profile if any connected client's Host header is not localhost
- Per-viewer queue with maxsize=1 — old frames are dropped for slow clients
- Forces DirectShow backend (`cv2.CAP_DSHOW`) on Windows to avoid MSMF black-frame bug

**Frontend pages:**
- `samples.html` + `static/js/samples.js` — local camera page. Uses `getUserMedia()` → `<video>` → canvas. All zoom/filter/mask logic lives in `samples.js` (~1500 lines).
- `remote.html` — remote stream viewer. Connects WebSocket, draws binary frames to canvas. Same zoom/filter/mask controls as samples.
- `index.html` — home page with tabs, tunnel URL display, and shutdown button.

## Key Design Decisions

- **WebSocket mode detection**: Host header — `localhost`/`127.0.0.1` → `local`, anything else → `remote`.
- **Separate event loops**: `stream_server.py` runs a native asyncio loop. Flask uses `gevent` on Linux, `threading` on Windows. They share no async primitives.
- **SocketIO is initialized but unused** — legacy from Stage 1–2 Socket.IO streaming. Can be removed.
- **LAN entry point is port 8000** (stream_server), not 5000. Flask is loopback-only (`127.0.0.1:5000`).
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

## Testing

```bash
pip install -r requirements-dev.txt   # adds pytest
pytest                                  # run all tests
pytest tests/test_app.py -v            # verbose
```

Tests live in `tests/test_app.py` and cover Flask routes. Camera/streaming tests belong in a separate `tests/test_stream_server.py` (not yet written).

## Common Development Tasks

| Task | Command |
|---|---|
| Run full app | `python app.py` |
| Run stream server only | `python stream_server.py` |
| Run tests | `pytest` |
| Install runtime deps | `pip install -r requirements.txt` |
| Install dev deps | `pip install -r requirements-dev.txt` |

## Where to Look

| I want to... | Look at... |
|---|---|
| Change zoom/filter/mask logic | `static/js/samples.js` |
| Change remote stream rendering | `templates/remote.html` |
| Add a Flask route | `app.py` |
| Tune camera quality/resolution | `stream_server.py` env-var defaults at top |
| Change tunnel or shutdown logic | `app.py:_start_tunnel()`, `app.py:shutdown()` |
| Add a route test | `tests/test_app.py` |

## Pi Deployment

Systemd services: `magnifier-stream.service` (stream_server) and a `magnifier.service` for Flask. `app.py` also launches them as subprocess fallbacks, so harmless if systemd is already running them.

