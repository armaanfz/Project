"""Flask route and safety regression tests."""
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
    assert b"Live \xe2\x80\x93 Remote View" in response.data
    assert b"Tutorial" in response.data
    assert b"Reset Zoom" in response.data
    assert b"Mask" in response.data


def test_video_feed_uses_local_profile_for_localhost(client, monkeypatch):
    camera = object()
    get_camera_mock = Mock(return_value=camera)
    generate_mock = Mock(return_value=iter([b"frame"]))

    monkeypatch.setattr(app_module, "_get_camera", get_camera_mock)
    monkeypatch.setattr(app_module, "_generate_mjpeg", generate_mock)

    response = client.get("/video_feed", base_url="http://localhost")

    assert response.status_code == 200
    get_camera_mock.assert_called_once_with("local")
    generate_mock.assert_called_once_with(camera, "local")
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"


def test_video_feed_uses_remote_profile_for_non_local_host(client, monkeypatch):
    camera = object()
    get_camera_mock = Mock(return_value=camera)
    generate_mock = Mock(return_value=iter([b"frame"]))

    monkeypatch.setattr(app_module, "_get_camera", get_camera_mock)
    monkeypatch.setattr(app_module, "_generate_mjpeg", generate_mock)

    response = client.get("/video_feed", base_url="http://magnifier.example.com")

    assert response.status_code == 200
    get_camera_mock.assert_called_once_with("remote")
    generate_mock.assert_called_once_with(camera, "remote")


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


def test_video_feed_returns_503_when_camera_unavailable(monkeypatch, client):
    monkeypatch.setattr(app_module, "_get_camera", Mock(side_effect=RuntimeError("camera missing")))

    response = client.get("/video_feed")

    assert response.status_code == 503
    assert response.data == b"Camera unavailable"


def test_generate_mjpeg_releases_camera_on_read_failure(monkeypatch):
    released = {"called": False}

    class FakeCamera:
        def read(self):
            return False, None

    def fake_release_camera():
        released["called"] = True

    monkeypatch.setattr(app_module, "_release_camera", fake_release_camera)

    frames = list(app_module._generate_mjpeg(FakeCamera(), "remote"))

    assert frames == []
    assert released["called"] is True


def test_get_camera_raises_when_device_cannot_open(monkeypatch):
    class FakeCamera:
        def isOpened(self):
            return False

        def release(self):
            return None

    monkeypatch.setattr(app_module, "_camera", None)
    monkeypatch.setattr(app_module.cv2, "VideoCapture", Mock(return_value=FakeCamera()))

    with pytest.raises(RuntimeError):
        app_module._get_camera("local")


def test_get_camera_configures_opened_device(monkeypatch):
    set_calls = []

    class FakeCamera:
        def isOpened(self):
            return True

        def set(self, prop, value):
            set_calls.append((prop, value))
            return True

    monkeypatch.setattr(app_module, "_camera", None)
    monkeypatch.setattr(app_module.cv2, "VideoCapture", Mock(return_value=FakeCamera()))

    camera = app_module._get_camera("local")

    assert camera is not None
    assert set_calls == [
        (app_module.cv2.CAP_PROP_BUFFERSIZE, 1),
        (app_module.cv2.CAP_PROP_FRAME_WIDTH, app_module.STREAM_PROFILES["local"]["width"]),
        (app_module.cv2.CAP_PROP_FRAME_HEIGHT, app_module.STREAM_PROFILES["local"]["height"]),
        (app_module.cv2.CAP_PROP_FPS, app_module.STREAM_PROFILES["local"]["fps"]),
    ]

    app_module._camera = None


def test_get_camera_reconfigures_when_mode_changes(monkeypatch):
    set_calls = []

    class FakeCamera:
        def isOpened(self):
            return True

        def set(self, prop, value):
            set_calls.append((prop, value))
            return True

    fake_camera = FakeCamera()
    monkeypatch.setattr(app_module, "_camera", None)
    monkeypatch.setattr(app_module, "_current_mode", None)
    monkeypatch.setattr(app_module.cv2, "VideoCapture", Mock(return_value=fake_camera))

    app_module._get_camera("local")
    app_module._get_camera("remote")

    assert set_calls == [
        (app_module.cv2.CAP_PROP_BUFFERSIZE, 1),
        (app_module.cv2.CAP_PROP_FRAME_WIDTH, app_module.STREAM_PROFILES["local"]["width"]),
        (app_module.cv2.CAP_PROP_FRAME_HEIGHT, app_module.STREAM_PROFILES["local"]["height"]),
        (app_module.cv2.CAP_PROP_FPS, app_module.STREAM_PROFILES["local"]["fps"]),
        (app_module.cv2.CAP_PROP_BUFFERSIZE, 1),
        (app_module.cv2.CAP_PROP_FRAME_WIDTH, app_module.STREAM_PROFILES["remote"]["width"]),
        (app_module.cv2.CAP_PROP_FRAME_HEIGHT, app_module.STREAM_PROFILES["remote"]["height"]),
        (app_module.cv2.CAP_PROP_FPS, app_module.STREAM_PROFILES["remote"]["fps"]),
    ]
