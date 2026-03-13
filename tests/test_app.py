"""Flask route and safety regression tests.

Tests for the Socket.IO /stream namespace handlers were removed in Stage 2 of
the streaming migration when that namespace was replaced by the standalone
asyncio WebSocket server (stream_server.py on port 5001).  Camera and streaming
unit tests now belong in a separate test_stream_server.py module.
"""
from unittest.mock import Mock

import pytest
import app as app_module
from app import app, socketio


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_shutdown_state(monkeypatch):
    monkeypatch.setattr(app_module, "_last_shutdown_request_at", 0.0)


def test_home_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"replace-this-with-a-strong-secret" not in r.data
    assert b"Access Remote Stream" in r.data


def test_samples_returns_200(client):
    r = client.get("/samples")
    assert r.status_code == 200


def test_remote_returns_200_and_includes_remote_controls(client):
    response = client.get("/remote")

    assert response.status_code == 200
    assert b"Access Remote Stream" not in response.data
    assert b"Remote Feed - Connecting..." in response.data
    assert b"stream-canvas" in response.data
    assert b"Tutorial" in response.data
    assert b"Reset Zoom" in response.data
    assert b"Mask" in response.data


def test_home_tab_content_returns_200(client):
    r = client.get("/home-tab-content")
    assert r.status_code == 200


def test_shutdown_rejects_non_local_requests(client):
    response = client.post("/shutdown", environ_base={"REMOTE_ADDR": "10.0.0.9"})
    assert response.status_code == 403


def test_shutdown_accepts_local_requests_and_invokes_shutdown(monkeypatch, client):
    run_mock = Mock()
    popen_mock = Mock()

    monkeypatch.setattr(app_module.subprocess, "run", run_mock)
    monkeypatch.setattr(app_module.subprocess, "Popen", popen_mock)
    monkeypatch.setattr(app_module.time, "sleep", lambda *_args, **_kwargs: None)

    response = client.post("/shutdown", environ_base={"REMOTE_ADDR": "127.0.0.1"})

    assert response.status_code == 200
    run_mock.assert_called_once_with(["pkill", "chromium"], capture_output=True)
    popen_mock.assert_called_once_with(["sudo", "shutdown", "-h", "now"])


def test_shutdown_rate_limit_returns_429(monkeypatch, client):
    monkeypatch.setattr(app_module, "SHUTDOWN_COOLDOWN_SECONDS", 30)
    monkeypatch.setattr(app_module.subprocess, "run", Mock())
    monkeypatch.setattr(app_module.subprocess, "Popen", Mock())
    monkeypatch.setattr(app_module.time, "sleep", lambda *_args, **_kwargs: None)
    response_one = client.post("/shutdown", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    response_two = client.post("/shutdown", environ_base={"REMOTE_ADDR": "127.0.0.1"})

    assert response_one.status_code == 200
    assert response_two.status_code == 429
