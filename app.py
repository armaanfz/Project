import os
import subprocess
import time
import cv2
import threading
from flask import Flask, render_template, request, Response

app = Flask(__name__)

# ── Camera streaming state ──────────────────────────────────────────────────
_camera_lock = threading.Lock()
_camera = None


def _get_camera():
    """Return a shared cv2.VideoCapture instance, opening it on first call."""
    global _camera
    with _camera_lock:
        if _camera is None or not _camera.isOpened():
            _camera = cv2.VideoCapture(0)  # 0 = first USB camera
            _camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            _camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            _camera.set(cv2.CAP_PROP_FPS, 30)
    return _camera


def _generate_mjpeg():
    """Yield MJPEG frames from the USB webcam indefinitely."""
    cam = _get_camera()
    while True:
        with _camera_lock:
            ok, frame = cam.read()
        if not ok:
            break
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )


# Generate a new token with: python3 -c "import secrets; print(secrets.token_hex(32))"
SHUTDOWN_TOKEN = "replace-this-with-a-strong-secret"

@app.route("/")
def index():
    return render_template("index.html", shutdown_token=SHUTDOWN_TOKEN)

@app.route("/shutdown", methods=["POST"])
def shutdown():
    token = request.headers.get("X-Shutdown-Token")
    if token != SHUTDOWN_TOKEN:
        return "Forbidden", 403
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
    return Response(
        _generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug)
