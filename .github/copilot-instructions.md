## Purpose
Provide concise, actionable guidance for AI coding agents working on this Flask-based single-repo website.

## Big-picture architecture (one-sentence)
This is a small Flask app (single-process) that renders three Jinja templates and serves static JS/CSS that implement all camera, zoom and filter behavior client-side.

## How to run locally (exact)
- From repository root (Windows PowerShell):
  - python .\app.py
  - The app binds to http://127.0.0.1:5000 by default (see `app.run(debug=True)` in `app.py`).
  - Open in a browser and allow camera access to test `samples` features.

## Key files to inspect (fast entry points)
- `app.py` — Flask routes: `/`, `/introduction`, `/samples` (render templates).
- `templates/index.html`, `templates/introduction.html`, `templates/samples.html` — UI markup and how JS is loaded via `url_for('static', filename=...)`.
- `static/js/samples.js` — Core client-side logic: camera access (navigator.mediaDevices.getUserMedia), zoom & pan state, predefined filters, reset logic.
- `static/js/script.js` & `static/js/introduction.js` — lightweight page helpers and navigation helper functions.
- `static/css/*.css` — styles for each page; `samples.css` contains many layout and accessibility-related rules (zoom UI, large filter buttons).

## Important project-specific patterns & conventions
- All dynamic behavior is client-side: video capture, zoom, filters and panning are implemented entirely in `static/js/samples.js` using `getUserMedia` and CSS `transform`/`filter`.
- Templates use `url_for('static', filename='...')` to reference CSS/JS. Prefer this pattern when adding new assets.
- Navigation is mixed: server defines routes like `/samples`, but some JS uses hard-coded filenames (e.g. `window.open("samples.html", "_self")` in `script.js`). Prefer linking to Flask routes (use `url_for`) to avoid 404s when served by Flask.

## Notable gotchas (explicit)
- `templates/*.html` are rendered server-side by Flask — they are not static files. Client code that tries to open `samples.html` (literal filename) may fail; use `/samples` or `{{ url_for('samples') }}`/`{{ url_for('static', filename='...') }}` for correct routing.
- The app currently runs with `debug=True` (development); do not assume production WSGI config exists.
- There are no server-side endpoints for processing video frames — any new server-side image processing requires adding routes in `app.py` and an API contract (multipart/form-data or websocket).

## Where to change core behaviors
- To add a new route or API: edit `app.py`, add Flask route, then create template under `templates/` and wire JS/CSS under `static/`.
- To change zoom/filter behavior: edit `static/js/samples.js` — central functions: `adjustZoom`, `changeZoom`, `applyCombinedFilters`, and the predefined filter functions (e.g. `applyProtanopia`).
- To tweak UI (large accessible buttons, slider styling): edit `static/css/samples.css` (look for `.filter-btn` and `.zoom-container`).

## Quick examples agents can use
- Navigation link in templates: `<a href="{{ url_for('introduction') }}">Introduction</a>` (use this pattern).
- Camera access pattern (copy from `static/js/samples.js`):
  navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
  .then(stream => videoElement.srcObject = stream)

## Testing & debugging tips
- Run `python .\app.py` and open devtools in browser to inspect console logs from `samples.js` (camera and filter errors appear there).
- For camera-related development, test in Chrome/Edge; ensure HTTPS or localhost and proper permissions.

## Additions and PR guidance for agents
- Keep changes minimal and focused: modify `static/js/*` for behavior, `templates/*` for markup, `static/css/*` for styling, and `app.py` only for new routes/APIs.
- When adding an API endpoint for frame uploads, define the request shape (JSON/multipart) in the route docstring and add a short example client call in `static/js/`.

If anything above is unclear or you'd like me to include more examples (e.g., example API route + small client upload snippet), tell me which area to expand. 

## Example: server-side API route (frame upload)
Below is a minimal Flask route you can add to `app.py` to accept a single image frame as multipart/form-data and save it to `images/media/` for later processing. This intentionally keeps error handling small so it's easy to adapt.

```python
from flask import request, jsonify
from werkzeug.utils import secure_filename
import os

@app.route('/api/upload_frame', methods=['POST'])
def upload_frame():
    # Expect a `frame` file field (Blob/image)
    if 'frame' not in request.files:
        return jsonify({'error': 'no frame file provided'}), 400

    f = request.files['frame']
    filename = secure_filename(f.filename or 'frame.png')

    # Ensure the save directory exists
    save_dir = os.path.join(os.path.dirname(__file__), 'images', 'media')
    os.makedirs(save_dir, exist_ok=True)

    save_path = os.path.join(save_dir, filename)
    f.save(save_path)

    # Return a JSON response with the saved path (relative)
    return jsonify({'status': 'ok', 'saved': os.path.join('images', 'media', filename)})
```

Notes:
- You'll need to `from flask import request, jsonify` and `from werkzeug.utils import secure_filename` at top of `app.py`.
- This route is synchronous and saves the file to disk; for production or large images, consider streaming, validating content-type, or using async/background workers.

## Example: client-side upload snippet (capture & POST)
Use this snippet in `static/js/samples.js` (or a new helper) to capture a single frame from the `<video id="video">` element and send it to `/api/upload_frame` as multipart/form-data.

```javascript
function sendCurrentFrame() {
  const video = document.getElementById('video');
  if (!video || !video.videoWidth) return console.error('video not ready');

  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  canvas.toBlob((blob) => {
    if (!blob) return console.error('failed to capture frame');
    const form = new FormData();
    form.append('frame', blob, 'frame.png');

    fetch('/api/upload_frame', { method: 'POST', body: form })
      .then(res => res.json())
      .then(console.log)
      .catch(console.error);
  }, 'image/png');
}
```

Alternatives: send base64 payload (JSON) or use a WebSocket for continuous frame streaming. If you add server-side image processing, document the expected content-type and max payload size in the route docstring.

## Low-risk PR checklist for contributors
Small, low-risk PRs that improve quality and maintainability without major rewrites:

- Functional smoke tests:
  - Add a minimal Flask test using the test client (pytest) in `tests/test_app.py` that asserts `GET /` and `GET /samples` return 200.
  - Example (not added by default):
    ```python
    def test_home(client):
        res = client.get('/')
        assert res.status_code == 200
    ```

- Small JS refactors (non-breaking):
  - Replace hard-coded navigation `window.open("samples.html", "_self")` with `window.location.href = '/samples'` or use Jinja `{{ url_for('samples') }}` in templates.
  - Replace legacy `var` with `let`/`const`, wrap page-scope helpers inside `document.addEventListener('DOMContentLoaded', ...)` or a small module object to avoid globals.
  - Add `aria-label` attributes to interactive elements when missing (buttons in `templates/samples.html` already have a few; add where needed).

- CSS/UI tweaks:
  - Make incremental visual changes in `static/css/samples.css` and test on desktop and narrow viewports; keep changes confined to single selectors (e.g., `.filter-btn`) to reduce regressions.

- Tests and verification steps for PRs (add to PR description):
  - How to run locally: `python .\app.py` then open `http://127.0.0.1:5000`.
  - Manual verification steps: open `/samples`, allow camera access, verify zoom slider and a couple of filters and the Reset Zoom button.

When in doubt, prefer small, well-described PRs with screenshots and a one-sentence risk summary (low/medium/high).

---

If you'd like, I can also create the `tests/` scaffold with a single pytest test and a `requirements-dev.txt` entry — tell me and I'll add it.
