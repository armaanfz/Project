import os
import base64
import socket
import subprocess
import time
import cv2
import threading
from flask import Flask, render_template, request
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(
    app,
    async_mode=os.environ.get("SOCKETIO_ASYNC_MODE", "threading"),
    cors_allowed_origins="*",
)

# ── Camera streaming state ──────────────────────────────────────────────────
_camera_lock = threading.Lock()
_camera = None
_current_mode = None
_stream_state_lock = threading.Lock()
_stream_client_modes = {}
_stream_thread = None
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "1920"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "1080"))
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "30"))
REMOTE_CAMERA_WIDTH = int(os.environ.get("REMOTE_CAMERA_WIDTH", "1280"))
REMOTE_CAMERA_HEIGHT = int(os.environ.get("REMOTE_CAMERA_HEIGHT", "720"))
REMOTE_CAMERA_FPS = int(os.environ.get("REMOTE_CAMERA_FPS", "24"))
LOCAL_JPEG_QUALITY = int(os.environ.get("LOCAL_JPEG_QUALITY", "85"))
REMOTE_JPEG_QUALITY = int(os.environ.get("REMOTE_JPEG_QUALITY", "50"))

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

# ── Shutdown safety state ───────────────────────────────────────────────────
_shutdown_lock = threading.Lock()
_last_shutdown_request_at = 0.0
SHUTDOWN_COOLDOWN_SECONDS = int(os.environ.get("SHUTDOWN_COOLDOWN_SECONDS", "30"))


def _release_camera():
    """Release the shared camera if it exists."""
    global _camera, _current_mode
    with _camera_lock:
        if _camera is not None:
            try:
                _camera.release()
            finally:
                _camera = None
                _current_mode = None


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
            app.logger.warning("Unable to apply camera %s setting: %s", label, value)


def _get_stream_mode():
    """Choose the video stream profile for this request.

    We use the Host header for stream quality selection because remote tunnel
    traffic may still terminate locally and appear to originate from 127.0.0.1.
    This helper is only for performance tuning, not authorization.
    """
    host = (request.host or "").split(":", 1)[0].strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "local"

    client_ip = (request.remote_addr or "").strip()
    if client_ip and client_ip not in _local_addresses():
        return "remote"

    return "remote" if host else "local"


def _get_active_stream_mode():
    """Prefer remote mode when any remote viewer is connected."""
    with _stream_state_lock:
        if not _stream_client_modes:
            return None
        if "remote" in _stream_client_modes.values():
            return "remote"
        return "local"


def _local_addresses():
    """Return IP addresses that should be treated as local to this machine."""
    addresses = {"127.0.0.1", "::1"}

    try:
        hostname = socket.gethostname()
        _, _, host_addresses = socket.gethostbyname_ex(hostname)
        addresses.update(host_addresses)
    except OSError:
        app.logger.debug("Unable to resolve host addresses for local request check")

    return addresses


def _is_local_request():
    """Allow only requests originating from this device."""
    client_ip = (request.remote_addr or "").strip()
    return client_ip in _local_addresses()


def _shutdown_request_allowed():
    """Apply a small cooldown to avoid repeated shutdown attempts."""
    global _last_shutdown_request_at
    with _shutdown_lock:
        now = time.monotonic()
        if now - _last_shutdown_request_at < SHUTDOWN_COOLDOWN_SECONDS:
            return False
        _last_shutdown_request_at = now
        return True


def _get_camera(mode):
    """Return a shared camera configured for the requested stream mode."""
    global _camera, _current_mode
    profile = STREAM_PROFILES[mode]

    with _camera_lock:
        if _camera is None or not _camera.isOpened():
            camera = cv2.VideoCapture(CAMERA_INDEX)
            if not camera or not camera.isOpened():
                if camera is not None:
                    camera.release()
                raise RuntimeError("Unable to open camera device")
            _camera = camera
            _current_mode = None

        if _current_mode != mode:
            _configure_camera(_camera, profile)
            _current_mode = mode

    return _camera


def _generate_mjpeg(cam, mode):
    """Yield MJPEG frames using the requested stream profile."""
    profile = STREAM_PROFILES[mode]
    interval = 1.0 / profile["fps"]
    quality = profile["quality"]
    last_frame_at = 0.0

    while True:
        now = time.monotonic()
        if now - last_frame_at < interval:
            time.sleep(0.005)
            continue

        with _camera_lock:
            ok, frame = cam.read()
        last_frame_at = now

        if not ok:
            app.logger.error("Camera frame capture failed; releasing camera")
            _release_camera()
            break

        encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not encoded:
            app.logger.error("MJPEG frame encoding failed")
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )


def _stream_frames():
    """Capture frames and emit them to connected Socket.IO stream clients."""
    global _stream_thread

    while True:
        mode = _get_active_stream_mode()
        if mode is None:
            with _stream_state_lock:
                _stream_thread = None
            return

        profile = STREAM_PROFILES[mode]
        interval = 1.0 / profile["fps"]
        quality = profile["quality"]
        started_at = time.monotonic()

        try:
            cam = _get_camera(mode)
        except RuntimeError as exc:
            app.logger.error("Unable to start websocket stream: %s", exc)
            socketio.emit(
                "stream_status",
                {"state": "error", "message": "Camera unavailable"},
                namespace="/stream",
            )
            socketio.sleep(1.0)
            continue

        with _camera_lock:
            ok, frame = cam.read()

        if not ok:
            app.logger.error("Camera frame capture failed; releasing camera")
            _release_camera()
            socketio.emit(
                "stream_status",
                {"state": "error", "message": "Camera unavailable"},
                namespace="/stream",
            )
            socketio.sleep(0.25)
            continue

        encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not encoded:
            app.logger.error("WebSocket frame encoding failed")
            socketio.sleep(0)
            continue

        socketio.emit(
            "frame",
            {"data": base64.b64encode(jpeg.tobytes()).decode("utf-8")},
            namespace="/stream",
        )

        elapsed = time.monotonic() - started_at
        socketio.sleep(max(0, interval - elapsed))


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/shutdown", methods=["POST"])
def shutdown():
    if not _is_local_request():
        return "Forbidden", 403
    if not _shutdown_request_allowed():
        return "Too Many Requests", 429
    # Close Chromium gracefully before shutting down (Raspberry Pi default browser)
    subprocess.run(["pkill", "chromium"], capture_output=True)
    time.sleep(2)
    subprocess.Popen(["sudo", "shutdown", "-h", "now"])
    return "Shutting down...", 200

@app.route("/home-tab-content")
def home_tab_content():
    return render_template("home_tab_content.html")

@app.route("/samples")
def samples():
    return render_template("samples.html")


@app.route("/remote")
def remote():
    """Remote viewer page — shows the Pi's camera stream."""
    return render_template("remote.html")


@socketio.on("connect", namespace="/stream")
def stream_connect():
    """Track stream clients and start the background emitter on first connect."""
    global _stream_thread

    mode = _get_stream_mode()
    with _stream_state_lock:
        _stream_client_modes[request.sid] = mode
        if _stream_thread is None:
            _stream_thread = socketio.start_background_task(_stream_frames)


@socketio.on("disconnect", namespace="/stream")
def stream_disconnect():
    """Remove stream clients; the emitter exits when none remain."""
    with _stream_state_lock:
        _stream_client_modes.pop(request.sid, None)

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    socketio.run(app, debug=debug, host="0.0.0.0", port=5000)
