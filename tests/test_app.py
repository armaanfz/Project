"""Flask route, shutdown, and tunnel lifecycle regression tests."""
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest
import app as app_module
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_shutdown_state(monkeypatch):
    monkeypatch.setattr(app_module, "_last_shutdown_request_at", None)


@pytest.fixture
def shutdown_commands(monkeypatch):
    """Run the shutdown worker synchronously with all system commands mocked."""
    run = Mock()
    popen = Mock()
    monkeypatch.setattr(app_module, "_is_raspberry_pi", lambda: True)
    monkeypatch.setattr(app_module.subprocess, "run", run)
    monkeypatch.setattr(app_module.subprocess, "Popen", popen)
    monkeypatch.setattr(app_module.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(app_module.threading.Thread, "start", lambda thread: thread.run())
    return run, popen


def test_home_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"replace-this-with-a-strong-secret" not in r.data
    assert b"Access Remote Stream" in r.data
    assert b"Tutorial" in r.data
    assert b"Show QR Code" in r.data
    assert b"Copy URL" not in r.data


def test_samples_returns_200(client):
    r = client.get("/samples")
    assert r.status_code == 200
    assert b'id="tutorial-btn"' not in r.data
    assert b"Start tutorial" not in r.data


def test_remote_returns_200_and_includes_remote_controls(client):
    response = client.get("/remote")

    assert response.status_code == 200
    assert b"Access Remote Stream" not in response.data
    assert b"Remote Feed - Connecting..." in response.data
    assert b"stream-canvas" in response.data
    assert b'id="tutorial-btn"' not in response.data
    assert b"Start tutorial" not in response.data
    assert b"Reset Zoom" in response.data
    assert b"Mask" in response.data


def test_home_tab_content_returns_200(client):
    r = client.get("/home-tab-content")
    assert r.status_code == 200


def test_tunnel_qr_returns_png_when_tunnel_ready(client, monkeypatch):
    monkeypatch.setattr(app_module, "_tunnel_status", "ready")
    monkeypatch.setattr(app_module, "_tunnel_url", "https://example.trycloudflare.com")

    response = client.get("/tunnel-qr")

    assert response.status_code == 200
    assert response.content_type == "image/png"
    assert response.data.startswith(b"\x89PNG")


def test_tunnel_qr_returns_503_when_tunnel_unavailable(client, monkeypatch):
    monkeypatch.setattr(app_module, "_tunnel_status", "starting")
    monkeypatch.setattr(app_module, "_tunnel_url", None)

    response = client.get("/tunnel-qr")

    assert response.status_code == 503


def test_shutdown_rejects_non_local_requests(client):
    response = client.post("/shutdown", environ_base={"REMOTE_ADDR": "10.0.0.9"})
    assert response.status_code == 403


def test_shutdown_accepts_local_requests_and_invokes_shutdown(client, shutdown_commands):
    run_mock, popen_mock = shutdown_commands
    response = client.post("/shutdown", environ_base={"REMOTE_ADDR": "127.0.0.1"})

    assert response.status_code == 200
    run_mock.assert_called_once_with(["pkill", "chromium"], capture_output=True)
    popen_mock.assert_called_once_with(["sudo", "shutdown", "-h", "now"])


def test_shutdown_rate_limit_returns_429(monkeypatch, client, shutdown_commands):
    monkeypatch.setattr(app_module, "SHUTDOWN_COOLDOWN_SECONDS", 30)
    response_one = client.post("/shutdown", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    response_two = client.post("/shutdown", environ_base={"REMOTE_ADDR": "127.0.0.1"})

    assert response_one.status_code == 200
    assert response_two.status_code == 429


@pytest.mark.parametrize("headers", [
    {"Host": "example.trycloudflare.com"},
    {"CF-Connecting-IP": "203.0.113.1"},
    {"X-Forwarded-For": "203.0.113.1"},
    {"X-Forwarded-Host": "example.trycloudflare.com"},
    {"Forwarded": "for=203.0.113.1"},
    {"Origin": "https://another-site.example"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_shutdown_rejects_proxied_or_cross_origin_loopback(client, shutdown_commands, headers):
    response = client.post("/shutdown", headers=headers,
                           environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert response.status_code == 403
    for command in shutdown_commands:
        command.assert_not_called()


def test_shutdown_rejects_unsupported_hardware(client, monkeypatch):
    monkeypatch.setattr(app_module, "_is_raspberry_pi", lambda: False)
    start = Mock()
    monkeypatch.setattr(app_module.threading.Thread, "start", start)
    assert client.post("/shutdown").status_code == 501
    start.assert_not_called()


def test_first_shutdown_is_allowed_immediately_after_boot(monkeypatch):
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 1.0)
    assert app_module._shutdown_request_allowed()
    assert not app_module._shutdown_request_allowed()


@pytest.mark.parametrize("model, expected", [
    ("Raspberry Pi 5 Model B Rev 1.0\x00", True),
    ("Desktop computer", False),
])
def test_shutdown_hardware_detection(monkeypatch, model, expected):
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(Path, "read_text", lambda _path: model)
    assert app_module._is_raspberry_pi() is expected


def test_import_does_not_start_background_services():
    code = '''
from unittest.mock import patch
with patch("threading.Thread.start") as start, patch("subprocess.Popen") as popen:
    import app
    start.assert_not_called()
    popen.assert_not_called()
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            cwd=Path(app_module.__file__).parent, timeout=20)
    assert result.returncode == 0, result.stderr


def test_tunnel_drains_logs_and_clears_url_on_exit(monkeypatch, client):
    observed = []

    class TunnelOutput(StringIO):
        def __next__(self):
            line = super().__next__()
            if line.startswith("after URL"):
                observed.append(client.get("/tunnel-status").json)
            return line

    process = Mock()
    process.stdout = TunnelOutput("https://example.trycloudflare.com\nafter URL\nmore logs\n")
    process.poll.return_value = 0
    monkeypatch.setattr(app_module.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(app_module, "_tunnel_url", None)
    monkeypatch.setattr(app_module, "_tunnel_status", "starting")
    monkeypatch.setattr(app_module, "_tunnel_process", None)

    app_module._start_tunnel()

    assert observed == [{"status": "ready", "url": "https://example.trycloudflare.com"}]
    assert client.get("/tunnel-status").json == {"status": "error", "url": None}
    assert process.stdout.closed
    process.wait.assert_called_once_with()
    assert app_module._tunnel_process is None


def test_tunnel_cleanup_kills_a_process_that_ignores_termination(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("cloudflared", 3), 0]
    monkeypatch.setattr(app_module, "_tunnel_process", process)
    app_module._stop_tunnel()
    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert app_module._tunnel_process is None


def test_failed_tunnel_download_leaves_no_partial_binary(monkeypatch, tmp_path):
    def incomplete_download(_url, destination):
        Path(destination).write_bytes(b"partial download")
        raise OSError("Connection interrupted")

    monkeypatch.setattr(app_module, "_CF_INSTALL_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(app_module.urllib.request, "urlretrieve", incomplete_download)
    with pytest.raises(OSError, match="Connection interrupted"):
        app_module._install_cloudflared()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw, expected", [
    ("invalid", 2.0), ("nan", 2.0), ("inf", 2.0), ("-1", 2.0), ("0", 0.0), ("1.5", 1.5),
])
def test_camera_release_duration_validation(monkeypatch, raw, expected):
    monkeypatch.setenv("STREAM_RELEASE_GRACE_SECONDS", raw)
    assert app_module._nonnegative_env_float("STREAM_RELEASE_GRACE_SECONDS", 2.0) == expected
