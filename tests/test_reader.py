"""Reader API, resource limits, cancellation, and actual installed engines."""
from io import BytesIO
import time
import wave

from PIL import Image
import cv2
import numpy as np
import pytest

import app as app_module
import reader

HEADERS = {"X-Magnifier-Reader": "1"}


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("Reader operation did not finish")


def page_image():
    image = np.full((500, 1300, 3), 255, dtype=np.uint8)
    for y, line in [(150, "The magnifier makes reading easier."), (250, "Clear text helps students learn.")]:
        cv2.putText(image, line, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3, cv2.LINE_AA)
    return cv2.imencode(".png", image)[1].tobytes()


def wav_bytes():
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x01" * 16000)
    return output.getvalue()


@pytest.fixture
def manager(monkeypatch):
    manager = reader.ReaderJobs()
    monkeypatch.setattr(reader, "jobs", manager)
    yield manager
    manager.close()


@pytest.fixture
def client(manager):
    with app_module.app.test_client() as client:
        yield client


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(reader, "availability", lambda: {"ocr": True, "speech": True})


def test_reader_reports_missing_setup_without_affecting_viewer(client, monkeypatch):
    monkeypatch.setattr(reader, "availability", lambda: {"ocr": False, "speech": False})
    assert client.get("/api/reader/status").json == {"ocr": False, "speech": False}
    assert client.post("/api/ocr", headers=HEADERS).status_code == 503
    assert client.post("/api/reader/speech", headers=HEADERS, json={"text": "Hello"}).status_code == 503
    assert client.get("/remote").status_code == 200


def test_reader_rejects_cross_site_forms_and_invalid_inputs(client, ready):
    assert client.post("/api/ocr").status_code == 403
    assert client.delete("/api/reader/jobs/unknown").status_code == 403
    assert client.post("/api/ocr", headers=HEADERS).status_code == 400
    response = client.post("/api/ocr", headers=HEADERS, data={"image": (BytesIO(b"<html>"), "page.png")})
    assert response.status_code == 400
    response = client.post("/api/ocr", headers=HEADERS, data={"image": (BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * reader.MAX_UPLOAD), "page.png")})
    assert response.status_code == 413
    assert response.is_json
    for payload in (None, [], {"text": []}, {"text": " "}, {"text": "a" * (reader.MAX_SPEECH_TEXT + 1)}):
        assert client.post("/api/reader/speech", headers=HEADERS, json=payload).status_code == 400


def test_ocr_returns_private_result_and_deletes_it(client, manager, ready, monkeypatch):
    def fake_worker(job, payload):
        assert payload == b"\xff\xd8\xffimage"
        return {"text": "Printed words", "word_count": 2}, b""
    monkeypatch.setattr(reader, "run_job", fake_worker)
    response = client.post("/api/ocr", headers=HEADERS, data={"image": (BytesIO(b"\xff\xd8\xffimage"), "page.jpg")})
    assert response.status_code == 202
    job_id = response.json["id"]
    assert len(job_id) >= 32
    wait_until(lambda: manager.get(job_id)["state"] == "done")
    response = client.get(f"/api/reader/jobs/{job_id}")
    assert response.json["result"]["text"] == "Printed words"
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/reader/jobs/not-someone-elses-id").status_code == 404
    assert client.delete(f"/api/reader/jobs/{job_id}", headers=HEADERS).status_code == 204
    assert client.get(f"/api/reader/jobs/{job_id}").status_code == 404


def test_speech_audio_download_and_cleanup(client, manager, ready, monkeypatch):
    recording = wav_bytes()
    def fake_worker(job, payload):
        assert job.kind == "speech" and payload["text"] == "Hello"
        return {"voice": "Piper"}, recording
    monkeypatch.setattr(reader, "run_job", fake_worker)
    response = client.post("/api/reader/speech", headers=HEADERS, json={"text": "Hello"})
    job_id = response.json["id"]
    wait_until(lambda: manager.get(job_id)["state"] == "done")
    response = client.get(f"/api/reader/jobs/{job_id}/audio")
    assert response.mimetype == "audio/wav"
    assert response.data == recording
    assert response.headers["Cache-Control"] == "no-store"
    client.delete(f"/api/reader/jobs/{job_id}", headers=HEADERS)
    assert client.get(f"/api/reader/jobs/{job_id}/audio").status_code == 404


def test_busy_reader_does_not_queue_more_work_and_cancel_releases_it(client, manager, ready, monkeypatch):
    def worker(job, payload):
        job.cancelled.wait(timeout=5)
        return {}, b""
    monkeypatch.setattr(reader, "run_job", worker)
    first = client.post("/api/reader/speech", headers=HEADERS, json={"text": "First"}).json
    assert client.post("/api/reader/speech", headers=HEADERS, json={"text": "Second"}).status_code == 429
    client.delete(f"/api/reader/jobs/{first['id']}", headers=HEADERS)
    wait_until(lambda: manager.active is None)
    assert manager.get(first["id"]) is None
    assert client.post("/api/reader/speech", headers=HEADERS, json={"text": "Next"}).status_code == 202


def test_results_expire_without_more_requests(manager, monkeypatch):
    monkeypatch.setattr(reader, "JOB_TTL", 0.04)
    monkeypatch.setattr(reader, "run_job", lambda *_args: ({"text": "Private page"}, b"audio"))
    job = manager.submit("ocr", b"image")
    wait_until(lambda: manager.get(job["id"]) is None)
    assert not manager.jobs and not manager.timers


def test_real_worker_timeout_removes_temporary_image(monkeypatch, tmp_path):
    (tmp_path / "reader_worker.py").write_text("import time; time.sleep(30)")
    monkeypatch.setattr(reader, "ROOT", tmp_path)
    monkeypatch.setattr(reader, "JOB_TIMEOUTS", {"ocr": 0.05})
    monkeypatch.setattr(reader.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(TimeoutError):
        reader.run_job(reader.Job("timeout", "ocr"), b"image")
    assert list(tmp_path.glob("magnifier-reader-*")) == []


@pytest.mark.skipif(not reader.availability()["ocr"], reason="Install Tesseract and requirements-reader.txt")
def test_real_tesseract_worker_reads_printed_text():
    result, audio = reader.run_job(reader.Job("actual-ocr", "ocr"), page_image())
    assert "magnifier makes reading easier" in result["text"]
    assert "students learn" in result["text"]
    assert result["word_count"] >= 10
    assert not audio


@pytest.mark.skipif(not reader.availability()["ocr"], reason="Install Tesseract and requirements-reader.txt")
def test_real_tesseract_worker_handles_blank_and_corrupt_images():
    blank = BytesIO()
    Image.new("RGB", (400, 300), "white").save(blank, format="PNG")
    result, _audio = reader.run_job(reader.Job("blank", "ocr"), blank.getvalue())
    assert result["text"] == ""
    with pytest.raises(RuntimeError, match="clearer"):
        reader.run_job(reader.Job("corrupt", "ocr"), b"\xff\xd8\xffnot an image")


@pytest.mark.skipif(not reader.availability()["speech"], reason="Run scripts/setup_reader.py for the real Piper voice")
def test_real_piper_produces_non_silent_audio():
    result, audio = reader.run_job(reader.Job("actual-speech", "speech"), {
        "text": "The magnifier makes reading easier.", "model": str(reader.voice_path()),
    })
    assert result["voice"] == "Piper"
    with wave.open(BytesIO(audio), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() >= 16000
        assert wav.getnframes() > wav.getframerate()
        assert len(set(wav.readframes(wav.getnframes()))) > 50
