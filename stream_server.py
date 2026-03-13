"""asyncio-based WebSocket camera streaming server.

Runs an independent WebSocket server on port 5001 that broadcasts JPEG frames
from the local camera to all connected viewers.

Binary frame protocol
---------------------
Each message is a raw bytes payload:
  [0:8]  big-endian signed int64 — server timestamp in milliseconds (Unix epoch)
  [8:]   JPEG-encoded frame data

NOTE: Remote WebSocket access through the Cloudflare tunnel will fail until a
reverse proxy (e.g., Caddy) routes /ws to port 5001. This is an intentional
known gap after Stage 3 of the streaming migration; Stage 4 (Caddy integration)
closes it.
"""
import asyncio
import cv2
import logging
import os
import struct
import time
import websockets
import websockets.exceptions

_log = logging.getLogger(__name__)

# ── Camera configuration constants ────────────────────────────────────────────

def _clamp_env_int(name, default, lo=None, hi=None):
    """Parse an integer env var with optional lower/upper bounds."""
    try:
        v = int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


CAMERA_INDEX         = _clamp_env_int("CAMERA_INDEX",          0, lo=0)
CAMERA_WIDTH         = _clamp_env_int("CAMERA_WIDTH",       1920, lo=320)
CAMERA_HEIGHT        = _clamp_env_int("CAMERA_HEIGHT",      1080, lo=240)
CAMERA_FPS           = _clamp_env_int("CAMERA_FPS",           30, lo=1,  hi=60)
REMOTE_CAMERA_WIDTH  = _clamp_env_int("REMOTE_CAMERA_WIDTH", 1280, lo=320)
REMOTE_CAMERA_HEIGHT = _clamp_env_int("REMOTE_CAMERA_HEIGHT",  720, lo=240)
REMOTE_CAMERA_FPS    = _clamp_env_int("REMOTE_CAMERA_FPS",     30, lo=1,  hi=60)
LOCAL_JPEG_QUALITY   = _clamp_env_int("LOCAL_JPEG_QUALITY",    92, lo=1,  hi=100)
REMOTE_JPEG_QUALITY  = _clamp_env_int("REMOTE_JPEG_QUALITY",   75, lo=1,  hi=100)
STREAM_RELEASE_GRACE_SECONDS = float(os.environ.get("STREAM_RELEASE_GRACE_SECONDS", "2.0"))

STREAM_PROFILES = {
    "local": {
        "width": CAMERA_WIDTH,
        "height": CAMERA_HEIGHT,
        "fps": CAMERA_FPS,
        "quality": LOCAL_JPEG_QUALITY,
    },
    "remote": {
        "width": REMOTE_CAMERA_WIDTH,
        "height": REMOTE_CAMERA_HEIGHT,
        "fps": REMOTE_CAMERA_FPS,
        "quality": REMOTE_JPEG_QUALITY,
    },
}

# ── Broadcaster state ──────────────────────────────────────────────────────────
# _viewers: set of asyncio.Queue objects, one per connected client.
# _viewer_modes: maps each Queue to "local" or "remote" for quality selection.
# Both are protected by _viewers_lock.
_viewers = set()
_viewer_modes = {}
_viewers_lock = None   # asyncio.Lock — initialised in start_stream_server()

_camera = None
_camera_lock = None    # asyncio.Lock — initialised in start_stream_server()

# ── Camera helpers ─────────────────────────────────────────────────────────────

def _configure_camera(camera, profile):
    """Apply preferred camera properties for the active stream profile."""
    settings = (
        (cv2.CAP_PROP_BUFFERSIZE, 1, "buffer size"),
        (cv2.CAP_PROP_FRAME_WIDTH, profile["width"], "width"),
        (cv2.CAP_PROP_FRAME_HEIGHT, profile["height"], "height"),
        (cv2.CAP_PROP_FPS, profile["fps"], "fps"),
    )
    for prop, value, label in settings:
        applied = camera.set(prop, value)
        if not applied:
            if prop == cv2.CAP_PROP_BUFFERSIZE:
                _log.debug("Camera backend does not support buffer size setting: %s", value)
            else:
                _log.warning("Unable to apply camera %s setting: %s", label, value)


async def _open_camera(mode):
    """Open the camera and configure it for the given stream mode."""
    global _camera
    loop = asyncio.get_event_loop()
    async with _camera_lock:
        if _camera is None or not _camera.isOpened():
            camera = await loop.run_in_executor(None, cv2.VideoCapture, CAMERA_INDEX)
            if not camera or not camera.isOpened():
                if camera is not None:
                    camera.release()
                raise RuntimeError("Unable to open camera device")
            _configure_camera(camera, STREAM_PROFILES[mode])
            _camera = camera


# ── Broadcaster coroutine ──────────────────────────────────────────────────────

async def _broadcast_frames():
    """Read camera frames and distribute them to all connected viewer queues."""
    loop = asyncio.get_event_loop()

    while True:
        async with _viewers_lock:
            viewers_snapshot = set(_viewers)
            has_remote = any(m == "remote" for m in _viewer_modes.values())

        if not viewers_snapshot:
            await asyncio.sleep(0.1)
            continue

        # Use remote profile when any remote viewer is connected, matching the
        # original per-connection quality logic from the Socket.IO implementation.
        active_mode = "remote" if has_remote else "local"
        profile = STREAM_PROFILES[active_mode]
        interval = 1.0 / profile["fps"]

        if _camera is None:
            await asyncio.sleep(0.1)
            continue

        cam = _camera
        ok, frame = await loop.run_in_executor(None, cam.read)
        if not ok:
            _log.warning("Camera frame capture failed; waiting before retry")
            await asyncio.sleep(0.25)
            continue

        ts_ms = int(time.time() * 1000)
        quality = profile["quality"]
        enc_ok, jpeg_buf = await loop.run_in_executor(
            None,
            lambda: cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]),
        )
        if not enc_ok or jpeg_buf is None:
            await asyncio.sleep(0.1)
            continue

        payload = {"data": jpeg_buf.tobytes(), "server_ts_ms": ts_ms}

        for q in viewers_snapshot:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # drop frame for this slow viewer; prevents memory growth

        await asyncio.sleep(interval)


# ── Connection handler coroutine ───────────────────────────────────────────────

async def handle_connection(websocket):
    """Handle a single WebSocket viewer connection."""
    host = websocket.request.headers.get("Host", "").split(":")[0].strip().lower()
    mode = "local" if host in {"localhost", "127.0.0.1", "::1"} else "remote"

    q = asyncio.Queue(maxsize=1)
    async with _viewers_lock:
        _viewers.add(q)
        _viewer_modes[q] = mode

    try:
        while True:
            payload = await q.get()
            ts_ms = payload["server_ts_ms"]
            jpeg_bytes = payload["data"]
            # Binary frame: 8-byte big-endian int64 timestamp then JPEG bytes.
            data = struct.pack(">q", ts_ms) + jpeg_bytes
            await websocket.send(data)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        async with _viewers_lock:
            _viewers.discard(q)
            _viewer_modes.pop(q, None)


# ── Server entry point ─────────────────────────────────────────────────────────

async def start_stream_server():
    """Initialise locks, warm up the camera, and serve WebSocket connections."""
    global _viewers_lock, _camera_lock
    _viewers_lock = asyncio.Lock()
    _camera_lock = asyncio.Lock()

    await _open_camera("local")
    asyncio.create_task(_broadcast_frames())

    server = await websockets.serve(handle_connection, "127.0.0.1", 5001)
    await server.serve_forever()


# ── Synchronous bridge function (used by app.py in Stage 2) ───────────────────

def run_stream_server():
    """Start the asyncio stream server from a background thread.

    Creates a dedicated event loop so the stream server does not share the
    Flask/gevent event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_stream_server())


# ── Standalone entry point (Stage 3) ──────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_stream_server())
