import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.request
import threading
import logging
from flask import Flask, render_template, request

_log = logging.getLogger(__name__)

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
        """Start cloudflared and return (url, status) once the URL is known."""
        proc = subprocess.Popen(
            [cf_cmd, "tunnel", "--url", "http://localhost:8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
        for line in proc.stdout:
            m = _CF_URL_RE.search(line)
            if m:
                return m.group(0), 'ready'
        return None, 'error'

    try:
        url, status = _run(cmd)
    except FileNotFoundError:
        try:
            cmd = _install_cloudflared()
        except Exception as exc:
            print(f"cloudflared auto-install failed: {exc}")
            with _tunnel_lock:
                _tunnel_status = 'error'
            return
        try:
            url, status = _run(cmd)
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

    with _tunnel_lock:
        _tunnel_url    = url
        _tunnel_status = status


_STREAM_SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stream_server.py")


def _start_stream_server():
    """Launch stream_server.py as a background subprocess on port 8000."""
    try:
        subprocess.Popen(
            [sys.executable, _STREAM_SERVER_SCRIPT],
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
        _log.info("stream_server.py launched on port 8000")
    except Exception as exc:
        _log.error("Failed to start stream_server.py: %s", exc)


threading.Thread(target=_start_stream_server, daemon=True).start()
threading.Thread(target=_start_tunnel, daemon=True).start()

app = Flask(__name__)

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

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
