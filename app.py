import atexit
import math
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import qrcode
from flask import Flask, render_template, request, send_file
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
_tunnel_process = None

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
    # A failed download must not leave a partial binary that looks installed.
    with tempfile.NamedTemporaryFile(dir=_CF_INSTALL_DIR, delete=False) as download:
        temporary_path = download.name
    try:
        urllib.request.urlretrieve(url, temporary_path)
        if not sys.platform.startswith("win"):
            os.chmod(temporary_path, 0o755)
        os.replace(temporary_path, dest)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    print(f"cloudflared installed at {dest}")
    return dest


def _start_tunnel():
    """Launch a Cloudflare quick tunnel, auto-installing cloudflared if needed."""
    global _tunnel_status

    _cf_local = os.path.join(
        _CF_INSTALL_DIR,
        "cloudflared.exe" if sys.platform.startswith("win") else "cloudflared",
    )
    cmd = _cf_local if os.path.isfile(_cf_local) else "cloudflared"

    def _run(cf_cmd):
        """Publish the URL, then keep draining logs until cloudflared exits."""
        global _tunnel_url, _tunnel_status, _tunnel_process
        proc = subprocess.Popen(
            [cf_cmd, "tunnel", "--url", "http://localhost:5000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
        with _tunnel_lock:
            _tunnel_process = proc
        try:
            # Returning at the first URL can fill the pipe and block the tunnel.
            for line in proc.stdout:
                match = _CF_URL_RE.search(line)
                if match:
                    with _tunnel_lock:
                        _tunnel_url = match.group(0)
                        _tunnel_status = 'ready'
            proc.wait()
        finally:
            proc.stdout.close()
            _stop_tunnel()
            with _tunnel_lock:
                _tunnel_url = None
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
            return
    except Exception as exc:
        print(f"Tunnel error: {exc}")
        with _tunnel_lock:
            _tunnel_status = 'error'
        return


def _stop_tunnel():
    """Terminate only the tunnel subprocess owned by this application."""
    global _tunnel_process
    with _tunnel_lock:
        proc = _tunnel_process
        _tunnel_process = None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


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


def _nonnegative_env_float(name, default):
    """Read a finite duration, falling back on malformed or negative values."""
    try:
        value = float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


CAMERA_INDEX         = _clamp_env_int("CAMERA_INDEX",          0, lo=0)
CAMERA_WIDTH         = _clamp_env_int("CAMERA_WIDTH",       1920, lo=320)
CAMERA_HEIGHT        = _clamp_env_int("CAMERA_HEIGHT",      1080, lo=240)
CAMERA_FPS           = _clamp_env_int("CAMERA_FPS",           30, lo=1,  hi=60)
REMOTE_CAMERA_WIDTH  = _clamp_env_int("REMOTE_CAMERA_WIDTH", 1280, lo=320)
REMOTE_CAMERA_HEIGHT = _clamp_env_int("REMOTE_CAMERA_HEIGHT",  720, lo=240)
REMOTE_CAMERA_FPS    = _clamp_env_int("REMOTE_CAMERA_FPS",     30, lo=1,  hi=60)
LOCAL_JPEG_QUALITY   = _clamp_env_int("LOCAL_JPEG_QUALITY",    92, lo=1,  hi=100)
REMOTE_JPEG_QUALITY  = _clamp_env_int("REMOTE_JPEG_QUALITY",   75, lo=1,  hi=100)
STREAM_RELEASE_GRACE_SECONDS = _nonnegative_env_float("STREAM_RELEASE_GRACE_SECONDS", 2.0)

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
_last_shutdown_request_at = None
SHUTDOWN_COOLDOWN_SECONDS = _clamp_env_int("SHUTDOWN_COOLDOWN_SECONDS", 30, lo=0)

# ── Local address cache ─────────────────────────────────────────────────────
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
            # A cancelled timer may already be running. Do not let it replace a
            # newer timer or release a camera that a reconnect is about to use.
            if _release_timer is not timer:
                return
            _release_timer = None
            if _stream_client_modes:
                return
            _release_camera()

    with _stream_state_lock:
        if _release_timer is not None:
            _release_timer.cancel()
        timer = threading.Timer(STREAM_RELEASE_GRACE_SECONDS, _release_if_idle)
        timer.daemon = True
        _release_timer = timer
        timer.start()


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
    """
    host = _request_hostname()
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
    """Allow direct, same-origin requests from this device, excluding tunnels."""
    client_ip = (request.remote_addr or "").strip()
    if client_ip not in _LOCAL_ADDRESSES:
        return False
    # cloudflared connects to Flask over loopback on behalf of remote viewers.
    if any(name.lower() in {"forwarded", "cf-connecting-ip"}
           or name.lower().startswith("x-forwarded-") for name in request.headers.keys()):
        return False
    hostname = socket.gethostname().lower()
    local_hosts = _LOCAL_ADDRESSES | {"localhost", hostname, f"{hostname}.local"}
    if _request_hostname() not in local_hosts:
        return False
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return False
    return request.headers.get("Sec-Fetch-Site") != "cross-site"


def _request_hostname():
    """Parse both ordinary and bracketed IPv6 Host headers."""
    try:
        return (urlsplit(request.host_url).hostname or "").lower()
    except ValueError:
        return ""


def _is_raspberry_pi():
    """Shutdown is available only on the target hardware."""
    if not sys.platform.startswith("linux"):
        return False
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            if "raspberry pi" in Path(path).read_text().lower():
                return True
        except OSError:
            continue
    return False


def _shutdown_request_allowed():
    """Apply a small cooldown to avoid repeated shutdown attempts."""
    global _last_shutdown_request_at
    with _shutdown_lock:
        now = time.monotonic()
        if (_last_shutdown_request_at is not None
                and now - _last_shutdown_request_at < SHUTDOWN_COOLDOWN_SECONDS):
            return False
        _last_shutdown_request_at = now
        return True


def _get_camera(mode):
    """Return a shared camera configured for the requested stream mode."""
    global _camera, _current_mode
    profile = STREAM_PROFILES[mode]

    with _camera_lock:
        if _camera is None or not _camera.isOpened():
            if _camera is not None:
                _camera.release()
                _camera = None
            # Force DirectShow on Windows to avoid MSMF black-frame bug
            backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
            camera = cv2.VideoCapture(CAMERA_INDEX, backend)
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
                if _stream_client_modes:
                    continue
                _stream_thread = None
            return

        profile = STREAM_PROFILES[mode]
        interval = 1.0 / profile["fps"]
        started_at = time.monotonic()

        try:
            cam = _get_camera(mode)
            with _camera_lock:
                ok, frame = cam.read()
            if not ok or frame is None:
                raise RuntimeError("Camera frame capture failed")
        except (RuntimeError, cv2.error) as exc:
            app.logger.error("Unable to start stream: %s", exc)
            _release_camera()
            socketio.emit(
                "stream_status",
                {"state": "error", "message": "Camera unavailable"},
                namespace="/stream",
            )
            socketio.sleep(1.0)
            continue

        ts_ms = int(time.time() * 1000)
        with _stream_state_lock:
            clients_snapshot = dict(_stream_client_modes)

        # Encode once per requested quality, even when several viewers share it.
        clients_by_quality = {}
        for sid, client_mode in clients_snapshot.items():
            quality = STREAM_PROFILES[client_mode]["quality"]
            clients_by_quality.setdefault(quality, []).append(sid)
        for quality, client_sids in clients_by_quality.items():
            try:
                enc_ok, jpeg = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality],
                )
            except cv2.error:
                app.logger.exception("Unable to encode camera frame")
                continue
            if enc_ok and jpeg is not None:
                payload = {"data": jpeg.tobytes(), "server_ts_ms": ts_ms}
                for sid in client_sids:
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
    if not _is_raspberry_pi():
        return "Shutdown is only supported on Raspberry Pi", 501
    if not _shutdown_request_allowed():
        return "Too Many Requests", 429

    def _do_shutdown():
        subprocess.run(["pkill", "chromium"], capture_output=True)
        time.sleep(2)
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return "Shutting down...", 200


@app.route("/tunnel-status")
def tunnel_status():
    with _tunnel_lock:
        return {"status": _tunnel_status, "url": _tunnel_url}


@app.route("/tunnel-qr")
def tunnel_qr():
    with _tunnel_lock:
        tunnel_url = _tunnel_url
        tunnel_status = _tunnel_status

    if tunnel_status != "ready" or not tunnel_url:
        return {"error": "Tunnel unavailable"}, 503

    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(tunnel_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")


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
def stream_connect(auth=None):
    """Track stream clients and start the background emitter on first connect."""
    global _stream_thread

    mode = _get_stream_mode()
    _cancel_release_timer()
    with _stream_state_lock:
        _stream_client_modes[request.sid] = mode
        if _stream_thread is None:
            _stream_thread = socketio.start_background_task(_stream_frames)


@socketio.on("disconnect", namespace="/stream")
def stream_disconnect(reason=None):
    """Remove stream clients; the emitter exits when none remain."""
    _remove_stream_client(request.sid)


def _cleanup_resources():
    _cancel_release_timer()
    _release_camera()
    _stop_tunnel()


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    # A reloader starts multiple processes, each competing for the same camera.
    run_kwargs = {"debug": debug, "use_reloader": False, "host": "0.0.0.0", "port": 5000}
    if socketio.async_mode == "threading":
        run_kwargs["allow_unsafe_werkzeug"] = True
    atexit.register(_cleanup_resources)
    if os.environ.get("DISABLE_TUNNEL", "").lower() in ("1", "true", "yes"):
        _tunnel_status = "disabled"
    else:
        threading.Thread(target=_start_tunnel, daemon=True).start()
    try:
        socketio.run(app, **run_kwargs)
    finally:
        _cleanup_resources()
