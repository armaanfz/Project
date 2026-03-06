import os
import socket
import subprocess
import time
import cv2
import threading
from flask import Flask, render_template, request, Response

app = Flask(__name__)

# ── Camera streaming state ──────────────────────────────────────────────────
_camera_lock = threading.Lock()
_camera = None
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "1920"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "1080"))
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "30"))

# ── Shutdown safety state ───────────────────────────────────────────────────
_shutdown_lock = threading.Lock()
_last_shutdown_request_at = 0.0
SHUTDOWN_COOLDOWN_SECONDS = int(os.environ.get("SHUTDOWN_COOLDOWN_SECONDS", "30"))


def _release_camera():
    """Release the shared camera if it exists."""
    global _camera
    with _camera_lock:
        if _camera is not None:
            try:
                _camera.release()
            finally:
                _camera = None


def _configure_camera(camera):
    """Apply preferred camera properties and log when they cannot be set."""
    settings = (
        (cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH, "width"),
        (cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT, "height"),
        (cv2.CAP_PROP_FPS, CAMERA_FPS, "fps"),
    )

    for prop, value, label in settings:
        applied = camera.set(prop, value)
        if not applied:
            app.logger.warning("Unable to apply camera %s setting: %s", label, value)


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


def _get_camera():
    """Return a shared cv2.VideoCapture instance, opening it on first call."""
    global _camera
    with _camera_lock:
        if _camera is None or not _camera.isOpened():
            camera = cv2.VideoCapture(CAMERA_INDEX)
            if not camera or not camera.isOpened():
                if camera is not None:
                    camera.release()
                raise RuntimeError("Unable to open camera device")
            _configure_camera(camera)
            _camera = camera
    return _camera


def _generate_mjpeg(cam):
    """Yield MJPEG frames from the USB webcam indefinitely."""
    while True:
        with _camera_lock:
            ok, frame = cam.read()
        if not ok:
            app.logger.error("Camera frame capture failed; releasing camera")
            _release_camera()
            break
        encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not encoded:
            app.logger.error("MJPEG frame encoding failed")
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )


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


@app.route("/video_feed")
def video_feed():
    """MJPEG stream endpoint consumed by remote.html."""
    try:
        cam = _get_camera()
    except RuntimeError as exc:
        app.logger.error("Unable to start video feed: %s", exc)
        return Response("Camera unavailable", status=503, mimetype="text/plain")

    return Response(
        _generate_mjpeg(cam),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug)
