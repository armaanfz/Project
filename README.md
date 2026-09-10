# Magnifier

A camera magnifier for students with low vision. The same zoom, pan, color
filters, image adjustments, and reading mask work with either a camera attached
to the browser's device or a camera attached to the Raspberry Pi server.

## Run

Use Python 3.10 or newer and a virtual environment:

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
| `static/images/magnifier.png` | Home background and site icon. |
| `magnifier-stream.service` | Single systemd service for `app.py` on port 5000. |
| `tests/test_app.py` | Routes, shutdown restrictions, configuration, and tunnel lifecycle tests. |
| `tests/test_stream.py` | Shared capture, quality selection, error recovery, and connection lifecycle tests using a simulated camera. |
| `tests/test_viewer.py` | Optional Chromium tests for controls, persistence, camera cleanup, and frame decoding. |
| `DESIGN.md` | Historical design audit; check the current CSS before applying its recommendations. The older preview assets have been removed from this branch. |

`requirements.txt` contains runtime dependencies, `requirements-dev.txt` adds
pytest, and `requirements-browser.txt` adds optional Playwright browser tests.

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
  `Escape` close panels. Shortcuts leave text inputs and browser shortcuts alone.
- Zoom, filters, adjustments, and mask preferences persist in local storage for
  the current browser/origin. A new tunnel URL has a separate set of preferences.

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
python -m pytest tests/test_app.py tests/test_stream.py -q
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
