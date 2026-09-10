"""Exercise stream recovery, quality selection, and reconnects without a camera."""
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

import app as app_module


@pytest.fixture(autouse=True)
def stream_state(monkeypatch):
    monkeypatch.setattr(app_module, "_stream_client_modes", {})
    monkeypatch.setattr(app_module, "_stream_thread", None)
    monkeypatch.setattr(app_module, "_release_timer", None)
    monkeypatch.setattr(app_module, "_camera", None)
    monkeypatch.setattr(app_module, "_current_mode", None)
    yield
    app_module._cancel_release_timer()
    app_module._release_camera()


@pytest.mark.parametrize("host, expected", [
    ("localhost:5000", "local"), ("127.0.0.1:5000", "local"),
    ("[::1]:5000", "local"), ("example.trycloudflare.com", "remote"),
])
def test_stream_profile_uses_hostname(host, expected):
    with app_module.app.test_request_context(headers={"Host": host}):
        assert app_module._get_stream_mode() == expected


def test_socket_clients_share_one_worker_and_cancel_release_on_reconnect(monkeypatch):
    worker = Mock()
    start = Mock(return_value=worker)
    monkeypatch.setattr(app_module.socketio, "start_background_task", start)
    first = app_module.socketio.test_client(app_module.app, namespace="/stream")
    second = app_module.socketio.test_client(
        app_module.app, namespace="/stream", headers={"Host": "remote.example"},
    )
    try:
        assert first.is_connected("/stream") and second.is_connected("/stream")
        start.assert_called_once_with(app_module._stream_frames)
        assert app_module._get_active_stream_mode() == "remote"
        second.disconnect(namespace="/stream")
        assert app_module._get_active_stream_mode() == "local"
        assert app_module._release_timer is None
        first.disconnect(namespace="/stream")
        assert app_module._release_timer is not None
        first.connect(namespace="/stream")
        assert app_module._release_timer is None
    finally:
        for client in (first, second):
            if client.is_connected("/stream"):
                client.disconnect(namespace="/stream")


def test_camera_is_reused_and_configured_only_when_mode_changes(monkeypatch):
    camera = Mock()
    camera.isOpened.return_value = True
    capture = Mock(return_value=camera)
    configure = Mock()
    monkeypatch.setattr(app_module.cv2, "VideoCapture", capture)
    monkeypatch.setattr(app_module, "_configure_camera", configure)
    assert app_module._get_camera("local") is camera
    assert app_module._get_camera("local") is camera
    app_module._get_camera("remote")
    assert capture.call_count == 1
    assert configure.call_count == 2
    app_module._release_camera()
    camera.release.assert_called_once_with()
    assert app_module._camera is None


def test_cancelled_release_callback_does_not_release_a_new_session(monkeypatch):
    timers = []

    def make_timer(_delay, callback):
        timer = Mock()
        timer.callback = callback
        timers.append(timer)
        return timer

    camera = Mock()
    monkeypatch.setattr(app_module, "_camera", camera)
    monkeypatch.setattr(app_module.threading, "Timer", make_timer)
    app_module._schedule_camera_release()
    app_module._schedule_camera_release()
    timers[0].callback()
    camera.release.assert_not_called()
    assert app_module._release_timer is timers[1]
    app_module._stream_client_modes["viewer"] = "local"
    timers[1].callback()
    camera.release.assert_not_called()
    app_module._stream_client_modes.clear()
    app_module._schedule_camera_release()
    timers[2].callback()
    camera.release.assert_called_once_with()


def test_capture_exception_recovers_without_losing_worker(monkeypatch):
    camera = Mock()
    frame = np.zeros((12, 16, 3), dtype=np.uint8)
    camera.read.side_effect = [cv2.error("Camera disconnected"), (True, frame)]
    monkeypatch.setattr(app_module, "_get_camera", Mock(return_value=camera))
    release = Mock()
    monkeypatch.setattr(app_module, "_release_camera", release)
    emit = Mock()
    monkeypatch.setattr(app_module.socketio, "emit", emit)
    app_module._stream_client_modes["viewer"] = "remote"

    def finish_after_frame(_delay):
        if any(call.args[0] == "frame" for call in emit.call_args_list):
            app_module._stream_client_modes.clear()

    monkeypatch.setattr(app_module.socketio, "sleep", finish_after_frame)
    app_module._stream_frames()
    assert [call.args[0] for call in emit.call_args_list] == ["stream_status", "frame"]
    assert camera.read.call_count == 2
    release.assert_called_once_with()
    assert app_module._stream_thread is None


@pytest.mark.parametrize("same_quality", [False, True])
def test_frames_are_encoded_once_per_distinct_quality(monkeypatch, same_quality):
    frame = np.zeros((12, 16, 3), dtype=np.uint8)
    camera = Mock()
    camera.read.return_value = (True, frame)
    monkeypatch.setattr(app_module, "_get_camera", Mock(return_value=camera))
    profiles = {mode: dict(profile) for mode, profile in app_module.STREAM_PROFILES.items()}
    if same_quality:
        profiles["local"]["quality"] = profiles["remote"]["quality"]
    monkeypatch.setattr(app_module, "STREAM_PROFILES", profiles)
    encode = Mock(wraps=cv2.imencode)
    monkeypatch.setattr(app_module.cv2, "imencode", encode)
    emit = Mock()
    monkeypatch.setattr(app_module.socketio, "emit", emit)
    monkeypatch.setattr(app_module.socketio, "sleep", lambda _delay: app_module._stream_client_modes.clear())
    app_module._stream_client_modes.update({"one": "remote", "two": "remote", "three": "local"})
    app_module._stream_frames()
    assert encode.call_count == (1 if same_quality else 2)
    assert {call.kwargs["to"] for call in emit.call_args_list} == {"one", "two", "three"}
    for call in emit.call_args_list:
        payload = call.args[1]
        assert payload["data"].startswith(b"\xff\xd8")
        assert payload["server_ts_ms"] > 0


def test_jpeg_encoding_error_does_not_stop_next_frame(monkeypatch):
    camera = Mock()
    camera.read.return_value = (True, np.zeros((12, 16, 3), dtype=np.uint8))
    monkeypatch.setattr(app_module, "_get_camera", Mock(return_value=camera))
    encode = Mock(side_effect=[cv2.error("Encode failed"), (True, np.array([255, 216], dtype=np.uint8))])
    monkeypatch.setattr(app_module.cv2, "imencode", encode)
    emit = Mock()
    monkeypatch.setattr(app_module.socketio, "emit", emit)
    monkeypatch.setattr(app_module.socketio, "sleep",
                        lambda _delay: app_module._stream_client_modes.clear() if emit.called else None)
    app_module._stream_client_modes["viewer"] = "remote"
    app_module._stream_frames()
    assert encode.call_count == 2
    emit.assert_called_once()
