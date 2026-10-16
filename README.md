# Magnifier

A camera magnifier for students with low vision. The same zoom, pan, color
filters, image adjustments, and reading mask work with either a camera attached
to the browser's device or a camera attached to the Raspberry Pi server.

## Run

Use 64-bit Python 3.10 or newer (3.12 recommended) and a virtual environment:

```sh
python -m venv venv
# Linux/Pi: source venv/bin/activate
# Windows PowerShell: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`. Running `app.py` also starts a Cloudflare quick
tunnel, downloading `cloudflared` if necessary. The home page shows its URL and
QR code. The URL changes on restart; anyone with the URL can reach the viewer.
Importing `app` for tests or tooling does not start a tunnel or open a camera.

For local development without a public tunnel, set `DISABLE_TUNNEL=1` before
running the app. On Linux/macOS, use `DISABLE_TUNNEL=1 python app.py`. In
PowerShell, use `$env:DISABLE_TUNNEL='1'` and then `python app.py`.

## How the pieces fit together

| File | Purpose |
| --- | --- |
| `app.py` | Flask routes, Socket.IO camera capture, JPEG encoding, tunnel lifecycle, QR codes, and Pi shutdown. |
| `templates/index.html` | Home page, theme picker, tunnel status polling, QR display, and shutdown UI. |
| `templates/home_tab_content.html` | Content for the Home, Team, and About tabs, embedded in the home page. |
| `static/js/script.js` | Home tab navigation and camera/tutorial/remote navigation buttons. |
| `templates/samples.html` | Local camera page using the browser's `getUserMedia()` API. |
| `templates/remote.html` | Remote camera page using Socket.IO `/stream` and a JPEG canvas. |
| `static/js/samples.js` | Shared viewer controls, saved settings, local camera startup, remote frame decoding, reading mask, and tutorial. |
| `static/css/styles.css` | Home page styling and theme variables. |
| `static/css/samples.css` | Viewer layout, controls, mask, tutorial, and accessibility styles. |
| `templates/reader.html`, `static/js/reader.js` | Shared accessible Read Text dialog and Piper audio playback. |
| `reader.py`, `reader_worker.py` | OCR/speech jobs, isolated processing, cancellation, and cleanup. |
| `scripts/setup_reader.py` | Voice download with registry checksum validation. |
| `static/images/magnifier.png` | Home background and site icon. |
| `magnifier-stream.service` | Single systemd service for `app.py` on port 5000. |
| `tests/test_app.py` | Routes, shutdown restrictions, configuration, and tunnel lifecycle tests. |
| `tests/test_stream.py` | Shared capture, quality selection, error recovery, and connection lifecycle tests using a simulated camera. |
| `tests/test_viewer.py` | Optional Chromium tests for controls, persistence, camera cleanup, and frame decoding. |
| `DESIGN.md` | Historical design audit; check the current CSS before applying its recommendations. The older preview assets have been removed from this branch. |

`requirements.txt` contains runtime dependencies, `requirements-dev.txt` adds
pytest, and `requirements-browser.txt` adds optional Playwright browser tests.
Text recognition and its models are included in the normal runtime installation.

### Two camera paths

- **Start Magnifier (`/samples`):** uses the camera on the device running the
  browser. Camera permission requires HTTPS or localhost.
- **Access Remote Stream (`/remote`):** receives the server's camera over the
  Socket.IO `/stream` namespace. Open this page through the tunnel to view the
  Pi's camera from another device.

The server shares one camera across stream viewers. Any remote viewer selects
the remote capture profile; local viewers still receive their configured JPEG
quality. A frame is encoded once per distinct requested quality. The browser
decodes one frame at a time and retains only the newest waiting frame. Remote
images use the same aspect-preserving crop as the local camera view.

The local browser and server are separate camera owners. Some camera drivers
cannot open the same device for `/samples` and `/remote` simultaneously. Use
`/remote` on both devices when the camera must be shared.

### Controls

- Zoom from 1× to 20× with the slider, buttons, or pinch. Drag to pan; Center
  recenters the image. Reset Zoom restores 1×.
- Filters and custom adjustments share one implementation on both pages.
- Mask opens the reading-mask controls and enables the mask. Clicking Mask
  again while its panel is open turns the mask off. Clicking elsewhere or
  opening Filters closes the panel while keeping the mask enabled.
- Keyboard shortcuts: `+` / `-` zoom, `0` reset, `F` filters, `M` mask, and
  `R` Read Text. `Escape` closes panels or returns from the reader. Camera
  shortcuts pause while the reader or tutorial is open.
- Zoom, filters, adjustments, and mask preferences persist in local storage for
  the current browser/origin. A new tunnel URL has a separate set of preferences.

## Read Text and Read Aloud

Read Text scans the visible camera area once, then opens a full-screen reading
view. The snapshot follows zoom and pan and uses original camera pixels before
display color filters and the mask. It does not open another camera. Both local
and remote viewers use the same capture and reader controls.

The reading view offers text size, four contrast combinations, and Read Aloud
with Pause, Resume, Stop, and playback speed. Text wraps to fit the screen.
Scan Again returns to the camera so the next page can be positioned before
tapping Read Text. Back to Camera preserves the existing magnifier settings.
Reader appearance and speed are saved separately; scanned text is not saved
to browser storage. Escape closes the dialog and restores focus to Read Text.

Text recognition uses **RapidOCR with bundled PP-OCRv6 neural models**. Installing
`requirements.txt` installs the OCR engine, CPU runtime, and recognition models.
There is no Tesseract executable, PATH setting, language-pack installer, API key,
or first-scan model download. Scans run locally on the machine hosting Flask.
The bundled model supports printed English; no language selection is needed for
English pages. Nearby lines reflow into paragraphs and low-confidence results
retain the existing warning to check the original page.

Speech uses **Piper's local neural voice**, defaulting to `en_US-lessac-medium`.
The browser plays the generated WAV recording; it never uses browser speech
synthesis and there is no fallback to browser voices. Model loading and speech
generation run on the machine hosting Flask (the Pi in deployment). Preparing
a recording takes time; the UI shows progress and lets the user stop.

### Install or update on Windows / Raspberry Pi OS

Activate the same virtual environment used to start `app.py` (or the Pi service).
On the Pi, use a 64-bit OS. After pulling the updated `remote-feed` branch, install
the dependencies and restart the app to enable **Read Text**:

```sh
python -m pip install -r requirements.txt
```

To enable **Read Aloud** as well, run these commands instead. They install the
same OCR dependencies plus Piper and download its voice:

```sh
python -m pip install -r requirements-reader.txt
python scripts/setup_reader.py
```

Setup downloads the default voice and configuration to `models/`, checks their
sizes and checksums against the upstream voice registry, and retains the model
card. Restart the app/service afterward. Voice files are excluded from Git.
Package installation and the voice download require Internet access; the installed OCR and voice engines
run locally without an external OCR/TTS API or API key. ONNX Runtime telemetry
is disabled before inference. Existing remote viewing still uses the tunnel
and the viewer's existing Socket.IO dependency.

The commands are the same on Windows and Pi OS; no separate OCR program is needed.
People viewing the Pi's website do not install these packages on their own devices.
Existing Tesseract installations and the old `TESSERACT_CMD` / `OCR_LANGUAGE`
settings are no longer used. Other OCR languages need separately validated models;
the former Tesseract language-pack setting does not select RapidOCR models.
For a different Piper voice, run `python scripts/setup_reader.py --voice CODE`
and set `PIPER_MODEL` to the resulting `.onnx` file. Its `.onnx.json` file must
remain next to it. Configure these environment variables in the systemd service
when using automatic startup; shell settings alone do not reach that service.

| Setting | Default | Purpose |
| --- | --- | --- |
| `PIPER_MODEL` | `models/en_US-lessac-medium.onnx` relative to the app directory | Local neural voice model. |

If dependencies are missing, the viewer remains usable and the reader shows a
unavailable message. `GET /api/reader/status` checks for the OCR package, its bundled
models, the CPU runtime, and the speech package/model files. If `ocr` is false,
reinstall `requirements.txt` in the Python environment that actually runs the app
and restart it. The status does not prove camera accuracy or voice quality on the Pi.

### Processing and limits

`POST /api/ocr` accepts a PNG/JPEG snapshot. `POST /api/reader/speech` accepts
recognized text. Each returns an unguessable job ID immediately; the UI polls
`GET /api/reader/jobs/<id>`, downloads completed speech from its `/audio` URL,
and deletes jobs with `DELETE /api/reader/jobs/<id>`. IDs are bearer tokens:
results are never broadcast to other viewers. Mutations require the custom
`X-Magnifier-Reader: 1` header; no cross-origin API access is enabled.

One OCR or speech job runs at a time across viewers; extra requests receive a
busy message instead of building up a queue. Native worker processes keep the
web/Socket.IO loop responsive, and inference uses one CPU thread. Cancellation
stops the worker process tree. OCR has a 45-second deadline;
speech has a 120-second deadline. Uploads are capped
at 6 MiB / 12 megapixels, recognized text at 20,000 characters, speech input at
8,000 characters, and generated audio at 24 MiB. Long text is explicitly flagged
or rejected rather than silently reading only part of a page.

Temporary input images/text and generated files are deleted after the worker
finishes. Completed results/audio live in memory for at most five minutes, up
to four results, and the UI deletes them after receiving them. Closing the
reader stops audio and releases browser image/audio URLs. A disconnected client
cannot leave work running beyond the deadline. Camera ownership and streaming
remain independent of reader jobs.

Start validation with clear printed English worksheets. Blurred or tilted pages,
handwriting, equations, and multiple columns need testing against the originals.
The uncertainty message is a cue to check words, not an accuracy guarantee.

Third-party components: [RapidOCR](https://github.com/RapidAI/RapidOCR)
(Apache-2.0; see its bundled `MODEL_LICENSES.md` for model notices),
[ONNX Runtime](https://github.com/microsoft/onnxruntime) (MIT),
[Piper](https://github.com/OHF-Voice/piper1-gpl) (GPL-3.0), and the
[Lessac voice model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD).
Keep the applicable software and voice-model notices with a distributed device.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `CAMERA_INDEX` | `0` | Server camera device. |
| `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS` | `1920`, `1080`, `30` | Local capture profile. |
| `REMOTE_CAMERA_WIDTH`, `REMOTE_CAMERA_HEIGHT`, `REMOTE_CAMERA_FPS` | `1280`, `720`, `30` | Remote capture profile. |
| `LOCAL_JPEG_QUALITY`, `REMOTE_JPEG_QUALITY` | `92`, `75` | JPEG quality, clamped to 1–100. |
| `STREAM_RELEASE_GRACE_SECONDS` | `2.0` | Hold the server camera after the last viewer leaves. |
| `SHUTDOWN_COOLDOWN_SECONDS` | `30` | Minimum time between accepted shutdown requests. |
| `SOCKETIO_ASYNC_MODE` | `threading` on Windows, `gevent` elsewhere | Socket.IO backend. |
| `DISABLE_TUNNEL` | unset | `1`, `true`, or `yes` disables the public tunnel. |
| `FLASK_DEBUG` | unset | Enables debug logging; the process reloader stays off to avoid duplicate camera/tunnel owners. |

The shutdown route accepts only direct local requests on detected Raspberry Pi
hardware. Requests through the tunnel, forwarded requests, and cross-origin
requests are rejected. The service account needs permission for the existing
`sudo shutdown -h now` command.

## Tests

Backend tests require neither a camera nor Cloudflare:

```sh
pip install -r requirements-dev.txt
python -m pytest tests/test_app.py tests/test_stream.py tests/test_reader.py -q
```

For the full suite, including browser tests:

```sh
pip install -r requirements-browser.txt
python -m playwright install chromium
python -m pytest -q
```

Browser tests start a local test server, use a synthetic camera, and simulate
Socket.IO frame delivery. They cover actual JPEG decoding as well as controlled
slow decoding and disconnects. The browser module is skipped when Playwright
is not installed.

Reader browser tests cover both camera sources, the exact zoom/pan crop,
unfiltered snapshots, plain-text rendering, cancellation, neural-audio playback
controls, and layouts at 1280×720, 800×480, and 390×600. Engine integration tests
run real RapidOCR and Piper when installed, otherwise they are explicitly
skipped. OCR is included in the normal test dependencies; install
`requirements-reader.txt` and run the voice setup to enable the speech tests.
Recognition checks include printed text, skew, low contrast, blank/corrupt images,
and operation without Tesseract or network downloads. No public tunnel is started by the suite.

Before deploying, check the actual Pi camera, touchscreen/pinch interactions,
Windows DirectShow if used, and a live Cloudflare connection. Automated tests
do not establish hardware frame rate or end-to-end network latency. The displayed
remote timing also depends on the viewer and server clocks being synchronized.

## Raspberry Pi service

Adjust the paths in `magnifier-stream.service` to match the checkout and virtual
environment, then install it using the commands in its header. This service
starts the entire app, including the stream and tunnel. If a previous
`magnifier.service` already runs `app.py`, use only one of the two services.
The old standalone `stream_server.py` on port 8000 is no longer part of this
repository. The systemd control group also stops the tunnel when the app stops.
