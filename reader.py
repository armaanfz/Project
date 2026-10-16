"""Bounded, cancellable reader jobs; expensive work stays outside the web process."""
import atexit
from dataclasses import dataclass, field
import importlib.util
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time

from flask import Blueprint, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from reader_worker import ocr_model_paths

reader_api = Blueprint("reader", __name__, url_prefix="/api")
ROOT = Path(__file__).resolve().parent
MAX_UPLOAD = 6 * 1024 * 1024
MAX_SPEECH_TEXT = 8000
MAX_AUDIO = 24 * 1024 * 1024
JOB_TTL = 300
JOB_TIMEOUTS = {"ocr": 45, "speech": 120}
log = logging.getLogger(__name__)


def voice_path():
    return Path(os.environ.get("PIPER_MODEL", str(ROOT / "models/en_US-lessac-medium.onnx"))).expanduser().resolve()


def availability():
    model = voice_path()
    ocr_models = ocr_model_paths()
    return {
        "ocr": bool(ocr_models) and all(path.is_file() for path in ocr_models.values())
               and importlib.util.find_spec("onnxruntime") is not None,
        "speech": importlib.util.find_spec("piper") is not None
                  and model.is_file() and Path(str(model) + ".json").is_file(),
    }


@dataclass
class Job:
    id: str
    kind: str
    state: str = "running"
    result: dict = field(default_factory=dict)
    error: str = ""
    audio: bytes = b""
    cancelled: threading.Event = field(default_factory=threading.Event)

    def snapshot(self):
        return {"id": self.id, "kind": self.kind, "state": self.state,
                "result": self.result, "error": self.error}


def terminate_process(process):
    """Stop the worker process tree, including on cancellation."""
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            process.kill()
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()


def run_job(job, payload):
    with tempfile.TemporaryDirectory(prefix="magnifier-reader-") as temporary:
        directory = Path(temporary)
        if job.kind == "ocr":
            (directory / "image").write_bytes(payload)
        else:
            (directory / "input.json").write_text(json.dumps(payload), encoding="utf-8")
        environment = os.environ.copy()
        # Keep the Pi's other cores available for camera capture / JPEG encoding.
        for name in ("OMP_THREAD_LIMIT", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            environment[name] = "1"
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "reader_worker.py"), job.kind, temporary],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env=environment, start_new_session=(os.name == "posix"),
        )
        deadline = time.monotonic() + JOB_TIMEOUTS[job.kind]
        try:
            while True:
                if job.cancelled.is_set():
                    return {}, b""
                if time.monotonic() > deadline:
                    raise TimeoutError("Reading took too long. Try scanning a smaller area.")
                try:
                    _, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if stderr:
                log.warning("Reader %s worker: %s", job.kind, stderr.decode(errors="replace")[-2000:])
            if process.returncode or not (directory / "result.json").is_file():
                raise RuntimeError("The reader could not finish. Please try again.")
            response = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            if response.get("error"):
                raise RuntimeError(response["error"])
            audio = b""
            if job.kind == "speech":
                path = directory / "speech.wav"
                if not path.is_file() or not 44 < path.stat().st_size <= MAX_AUDIO:
                    raise RuntimeError("The recording is too long. Scan a smaller area.")
                audio = path.read_bytes()
            return response["result"], audio
        finally:
            terminate_process(process)
            process.communicate()


class ReaderJobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}
        self.active = None
        self.timers = {}
        self.thread = None

    def submit(self, kind, payload):
        with self.lock:
            if self.active is not None:
                return None
            # At most four completed results/audio clips are retained in memory.
            while len(self.jobs) >= 4:
                old_id = next(iter(self.jobs))
                self._remove(old_id)
            job = Job(secrets.token_urlsafe(32), kind)
            self.jobs[job.id] = job
            self.active = job.id
            self.thread = threading.Thread(target=self._run, args=(job, payload), daemon=True)
            self.thread.start()
            return job.snapshot()

    def _remove(self, job_id):
        job = self.jobs.pop(job_id, None)
        if job:
            job.cancelled.set()
        timer = self.timers.pop(job_id, None)
        if timer:
            timer.cancel()

    def cancel(self, job_id):
        with self.lock:
            self._remove(job_id)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return job.snapshot() if job else None

    def audio(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return job.audio if job and job.state == "done" else None

    def _run(self, job, payload):
        try:
            result, audio = run_job(job, payload)
            with self.lock:
                if not job.cancelled.is_set():
                    job.result, job.audio, job.state = result, audio, "done"
        except (TimeoutError, RuntimeError) as exc:
            with self.lock:
                job.error, job.state = str(exc), "error"
        except Exception:
            log.exception("Reader worker failed")
            with self.lock:
                job.error, job.state = "The reader could not finish. Please try again.", "error"
        finally:
            with self.lock:
                self.active = None
                if job.id in self.jobs:
                    timer = threading.Timer(JOB_TTL, self.cancel, args=(job.id,))
                    timer.daemon = True
                    self.timers[job.id] = timer
                    timer.start()

    def close(self):
        with self.lock:
            for job_id in list(self.jobs):
                self._remove(job_id)
            thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=6)


jobs = ReaderJobs()
atexit.register(jobs.close)


@reader_api.before_request
def validate_reader_request():
    # A custom header prevents cross-site forms from starting expensive work.
    if request.method in {"POST", "DELETE"} and request.headers.get("X-Magnifier-Reader") != "1":
        return jsonify(error="This request must come from the magnifier reader."), 403
    if request.content_length and request.content_length > MAX_UPLOAD + 65536:
        raise RequestEntityTooLarge()


@reader_api.after_request
def reader_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@reader_api.errorhandler(RequestEntityTooLarge)
def image_too_large(_error):
    return jsonify(error="The image is too large. Scan a smaller area."), 413


@reader_api.get("/reader/status")
def reader_status():
    return jsonify(availability())


def start_job(kind, payload):
    job = jobs.submit(kind, payload)
    if job is None:
        return jsonify(error="The reader is busy. Please try again in a moment."), 429
    return jsonify(job), 202


@reader_api.post("/ocr")
def start_ocr():
    if not availability()["ocr"]:
        return jsonify(error="Text recognition is unavailable. The magnifier's installation needs updating."), 503
    upload = request.files.get("image")
    if upload is None:
        return jsonify(error="No camera image was received. Please scan again."), 400
    data = upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise RequestEntityTooLarge()
    if not data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        return jsonify(error="Use a JPEG or PNG camera image."), 400
    return start_job("ocr", data)


@reader_api.post("/reader/speech")
def start_speech():
    if not availability()["speech"]:
        return jsonify(error="Read Aloud has not been set up on this device yet."), 503
    payload = request.get_json(silent=True)
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="There is no text to read aloud."), 400
    if len(text) > MAX_SPEECH_TEXT:
        return jsonify(error="There is too much text to read at once. Scan a smaller area."), 400
    return start_job("speech", {"text": text.strip(), "model": str(voice_path())})


@reader_api.route("/reader/jobs/<job_id>", methods=["GET", "DELETE"])
def reader_job(job_id):
    if request.method == "DELETE":
        jobs.cancel(job_id)
        return "", 204
    result = jobs.get(job_id)
    return (jsonify(result), 200) if result else (jsonify(error="This scan has expired. Please scan again."), 404)


@reader_api.get("/reader/jobs/<job_id>/audio")
def reader_audio(job_id):
    audio = jobs.audio(job_id)
    if not audio:
        return jsonify(error="The recording is no longer available. Tap Read Aloud again."), 404
    return send_file(BytesIO(audio), mimetype="audio/wav", download_name="reading.wav")
