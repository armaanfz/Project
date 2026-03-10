import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.request
import cv2
import threading
from flask import Flask, render_template, request
from flask_socketio import SocketIO


def _default_socketio_async_mode():
    """Choose a safer default async backend for the current platform.

    gevent is a good production fit for Linux/Raspberry Pi deployments, but it
    can be unstable in this project's current Windows development environment.
    Allow an explicit env override, otherwise default to threading on Windows
    and gevent elsewhere.
    """
    configured = os.environ.get("SOCKETIO_ASYNC_MODE", "").strip().lower()
    if configured:
        return configured
    return "threading" if sys.platform.startswith("win") else "gevent"

# ── Cloudflare tunnel state ──────────────────────────────────────────────────
_tunnel_url    = None
_tunnel_status = 'starting'
_tunnel_lock   = threading.Lock()

_CF_URL_RE     = re.compile(r'https://\S+\.trycloudflare\.com')
_CF_INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))


def _install_cloudflared():
    """Download the cloudflared binary for this platform and return its path."""
    machine = platform.machine().lower()
    if sys.platform.startswith("win"):
        filename = "cloudflared.exe"
        arch = "amd64" if "64" in machine else "386"
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-{arch}.exe"
    elif sys.platform.startswith("linux"):
        filename = "cloudflared"
        if "aarch64" in machine or "arm64" in machine:
            arch = "arm64"
        elif "arm" in machine:
            arch = "arm"
        else:
            arch = "amd64"
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    else:
        raise OSError(f"Auto-install not supported on {sys.platform}; install cloudflared manually")

    dest = os.path.join(_CF_INSTALL_DIR, filename)
    print(f"cloudflared not found — downloading from {url} ...")
    urllib.request.urlretrieve(url, dest)
    if not sys.platform.startswith("win"):
        os.chmod(dest, 0o755)
    print(f"cloudflared installed at {dest}")
    return dest


def _start_tunnel():
    """Launch a Cloudflare quick tunnel, auto-installing cloudflared if needed."""
    global _tunnel_url, _tunnel_status

    _cf_local = os.path.join(
        _CF_INSTALL_DIR,
        "cloudflared.exe" if sys.platform.startswith("win") else "cloudflared",
    )
    cmd = _cf_local if os.path.isfile(_cf_local) else "cloudflared"

    def _run(cf_cmd):
        proc = subprocess.Popen(
            [cf_cmd, "tunnel", "--url", "http://localhost:5000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
        for line in proc.stdout:
            m = _CF_URL_RE.search(line)
            if m:
                with _tunnel_lock:
                    _tunnel_url    = m.group(0)
                    _tunnel_status = 'ready'
                break
        else:
            with _tunnel_lock:
                _tunnel_status = 'error'

    try:
        _run(cmd)
    except FileNotFoundError:
        try:
            cmd = _install_cloudflared()
        except Exception as exc:
            print(f"cloudflared auto-install failed: {exc}")
            with _tunnel_lock:
                _tunnel_status = 'error'
            return
        try:
            _run(cmd)
        except Exception as exc:
            print(f"Tunnel error after install: {exc}")
            with _tunnel_lock:
                _tunnel_status = 'error'
    except Exception as exc:
        print(f"Tunnel error: {exc}")
        with _tunnel_lock:
            _tunnel_status = 'error'


threading.Thread(target=_start_tunnel, daemon=True).start()

app = Flask(__name__)
socketio = SocketIO(
    app,
    async_mode=_default_socketio_async_mode(),
    cors_allowed_origins="*",
)

# ── Camera streaming state ──────────────────────────────────────────────────
_camera_lock = threading.Lock()
_camera = None
_current_mode = None
_stream_state_lock = threading.Lock()
_stream_client_modes = {}
_stream_thread = None
_release_timer = None
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
REMOTE_CAMERA_FPS    = _clamp_env_int("REMOTE_CAMERA_FPS",     24, lo=1,  hi=60)
LOCAL_JPEG_QUALITY   = _clamp_env_int("LOCAL_JPEG_QUALITY",    85, lo=1,  hi=100)
REMOTE_JPEG_QUALITY  = _clamp_env_int("REMOTE_JPEG_QUALITY",   50, lo=1,  hi=100)
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

# ── Shutdown safety state ───────────────────────────────────────────────────
_shutdown_lock = threading.Lock()
_last_shutdown_request_at = 0.0
SHUTDOWN_COOLDOWN_SECONDS = int(os.environ.get("SHUTDOWN_COOLDOWN_SECONDS", "30"))

# ── Local address cache ─────────────────────────────────────────────────────
# Computed once at startup to avoid a DNS lookup on every request.
def _compute_local_addresses():
    """Return the set of IP addresses that belong to this machine."""
    addresses = {"127.0.0.1", "::1"}
    try:
        hostname = socket.gethostname()
        _, _, host_addresses = socket.gethostbyname_ex(hostname)
        addresses.update(host_addresses)
    except OSError:
        app.logger.debug("Unable to resolve host addresses for local request check")
    return frozenset(addresses)

_LOCAL_ADDRESSES = _compute_local_addresses()


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


def _cancel_release_timer():
    """Cancel any pending delayed camera release."""
    global _release_timer
    with _stream_state_lock:
        if _release_timer is not None:
            _release_timer.cancel()
            _release_timer = None


def _schedule_camera_release():
    """Delay camera shutdown briefly to avoid rapid off/on cycles during reconnects."""
    global _release_timer

    def _release_if_idle():
        global _release_timer
        with _stream_state_lock:
            if _stream_client_modes:
                _release_timer = None
                return
            _release_timer = None
        _release_camera()

    with _stream_state_lock:
        if _release_timer is not None:
            _release_timer.cancel()
        _release_timer = threading.Timer(STREAM_RELEASE_GRACE_SECONDS, _release_if_idle)
        _release_timer.daemon = True
        _release_timer.start()


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
                app.logger.debug("Camera backend does not support buffer size setting: %s", value)
            else:
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
    if client_ip and client_ip not in _LOCAL_ADDRESSES:
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


def _remove_stream_client(sid):
    """Remove a tracked stream client and release the camera when none remain."""
    removed = False
    with _stream_state_lock:
        removed = _stream_client_modes.pop(sid, None) is not None
        has_clients = bool(_stream_client_modes)

    if removed and not has_clients:
        _schedule_camera_release()

    return removed


def _is_local_request():
    """Allow only requests originating from this device."""
    client_ip = (request.remote_addr or "").strip()
    return client_ip in _LOCAL_ADDRESSES


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


def _stream_frames():
    """Capture frames and emit them to connected Socket.IO stream clients."""
    global _stream_thread

    while True:
        mode = _get_active_stream_mode()
        if mode is None:
            with _stream_state_lock:
                # Re-check inside the lock: a new client may have connected
                # between the _get_active_stream_mode() call above and now.
                if _stream_client_modes:
                    continue
                _stream_thread = None
            return

        profile = STREAM_PROFILES[mode]
        interval = 1.0 / profile["fps"]
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

        ts_ms = int(time.time() * 1000)
        with _stream_state_lock:
            clients_snapshot = dict(_stream_client_modes)

        local_sids  = [sid for sid, m in clients_snapshot.items() if m == "local"]
        remote_sids = [sid for sid, m in clients_snapshot.items() if m == "remote"]

        if remote_sids:
            enc_ok, rem_jpeg = cv2.imencode(
                ".jpg", frame,
                [cv2.IMWRITE_JPEG_QUALITY, STREAM_PROFILES["remote"]["quality"]],
            )
            if enc_ok and rem_jpeg is not None:
                payload = {"data": rem_jpeg.tobytes(), "server_ts_ms": ts_ms}
                for sid in remote_sids:
                    socketio.emit("frame", payload, namespace="/stream", to=sid)

        if local_sids:
            enc_ok, loc_jpeg = cv2.imencode(
                ".jpg", frame,
                [cv2.IMWRITE_JPEG_QUALITY, STREAM_PROFILES["local"]["quality"]],
            )
            if enc_ok and loc_jpeg is not None:
                payload = {"data": loc_jpeg.tobytes(), "server_ts_ms": ts_ms}
                for sid in local_sids:
                    socketio.emit("frame", payload, namespace="/stream", to=sid)

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

    def _do_shutdown():
        # Close Chromium gracefully before shutting down (Raspberry Pi default browser)
        subprocess.run(["pkill", "chromium"], capture_output=True)
        time.sleep(2)
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return "Shutting down...", 200

@app.route("/tunnel-status")
def tunnel_status():
    with _tunnel_lock:
        return {"status": _tunnel_status, "url": _tunnel_url}

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
    _cancel_release_timer()
    with _stream_state_lock:
        _stream_client_modes[request.sid] = mode
        if _stream_thread is None:
            _stream_thread = socketio.start_background_task(_stream_frames)


@socketio.on("disconnect", namespace="/stream")
def stream_disconnect():
    """Remove stream clients; the emitter exits when none remain."""
    _remove_stream_client(request.sid)

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    socketio.run(app, debug=debug, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
