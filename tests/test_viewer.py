"""Optional browser regressions. Install requirements-browser.txt and Chromium."""
import json
import os
import threading

import cv2
import numpy as np
import pytest
from werkzeug.serving import make_server

import app as app_module

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def viewer_server():
    server = make_server("127.0.0.1", 0, app_module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"), args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        ])
        yield browser
        browser.close()


@pytest.fixture
def page(browser, viewer_server):
    context = browser.new_context(viewport={"width": 1280, "height": 720}, permissions=["camera"])
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # Tests use local assets and synthetic frames; never open a public tunnel.
    page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(viewer_server)
               else route.fulfill(status=200, body=""))
    page.add_init_script("""
      window.io = () => {
        const handlers = {};
        window.testSocket = {
          on(event, handler) { handlers[event] = handler; },
          receive(event, payload) { handlers[event]?.(payload); },
          removeAllListeners() { Object.keys(handlers).forEach(key => delete handlers[key]); },
          disconnect() { handlers.disconnect?.(); },
        };
        queueMicrotask(() => handlers.connect?.());
        return window.testSocket;
      };
      const createURL = URL.createObjectURL.bind(URL);
      const revokeURL = URL.revokeObjectURL.bind(URL);
      window.activeFrameURLs = new Set();
      window.createdFrameBlobs = [];
      URL.createObjectURL = blob => {
        const url = createURL(blob);
        activeFrameURLs.add(url);
        createdFrameBlobs.push(blob);
        return url;
      };
      URL.revokeObjectURL = url => {
        activeFrameURLs.delete(url);
        revokeURL(url);
      };
    """)
    yield page
    context.close()
    assert errors == [], f"Unhandled browser errors: {errors}"


def set_range(page, selector, value):
    page.locator(selector).evaluate("(input, value) => { input.value = value; input.dispatchEvent(new Event('input', {bubbles: true})); }", value)


@pytest.mark.parametrize("route", ["/samples", "/remote"])
def test_preferences_restore_without_being_overwritten(page, viewer_server, route):
    saved = {
        "zoom": 3.2, "filterKey": "grayscale",
        "customFilters": {"hue": 35, "brightness": "140", "contrast": 120, "saturation": 80},
        "mask": {"enabled": True, "barPct": 12, "orientation": "vertical", "inverted": True},
    }
    page.add_init_script(f"localStorage.setItem('magnifier_settings', {json.dumps(json.dumps(saved))});")
    page.goto(viewer_server + route)
    assert page.locator("#zoom-slider").input_value() == "3.2"
    assert page.locator(".zoom-label").inner_text() == "3.2×"
    assert page.locator('[data-filter="grayscale"]').get_attribute("aria-pressed") == "true"
    assert page.locator("#brightness").input_value() == "140"
    assert page.locator("#brightness").get_attribute("aria-valuetext") == "140%"
    assert page.locator("#mask-radius").input_value() == "12"
    assert page.locator("#mask-btn").get_attribute("aria-pressed") == "true"
    assert page.locator("#mask-vertical-btn").get_attribute("aria-pressed") == "true"
    assert page.locator("#mask-invert-btn").get_attribute("aria-pressed") == "true"
    assert page.locator("#mask-overlay").count() == 1
    persisted = page.evaluate("JSON.parse(localStorage.getItem('magnifier_settings'))")
    assert persisted["zoom"] == saved["zoom"]
    assert persisted["filterKey"] == saved["filterKey"]
    assert persisted["mask"] == saved["mask"]


@pytest.mark.parametrize("route", ["/samples", "/remote"])
def test_zoom_reset_and_mask_toggle_persist(page, viewer_server, route):
    page.goto(viewer_server + route)
    set_range(page, "#zoom-slider", 4)
    page.locator("#reset-btn").click()
    assert page.locator(".zoom-label").inner_text() == "1×"
    assert page.locator("#zoom-slider").get_attribute("aria-valuenow") == "1"
    assert page.evaluate("JSON.parse(localStorage.getItem('magnifier_settings')).zoom") == 1
    page.locator("#mask-btn").click()
    assert page.locator("#mask-overlay").count() == 1
    page.locator("#mask-btn").click()
    assert page.locator("#mask-overlay").count() == 0
    assert page.locator("#mask-btn").get_attribute("aria-pressed") == "false"
    assert not page.evaluate("JSON.parse(localStorage.getItem('magnifier_settings')).mask.enabled")
    page.reload()
    assert page.locator(".zoom-label").inner_text() == "1×"
    assert page.locator("#mask-overlay").count() == 0


@pytest.mark.parametrize("saved", ["null", "[]", "not json", json.dumps({
    "zoom": 100, "filterKey": "toString", "customFilters": {"hue": -20, "brightness": "900"},
    "mask": {"barPct": 900, "orientation": "invalid", "inverted": "false"},
})])
def test_invalid_preferences_do_not_break_controls(page, viewer_server, saved):
    page.add_init_script(f"localStorage.setItem('magnifier_settings', {json.dumps(saved)});")
    page.goto(viewer_server + "/remote")
    value = float(page.locator("#zoom-slider").input_value())
    assert 1 <= value <= 20
    assert 0 <= int(page.locator("#mask-radius").input_value()) <= 48
    assert 0 <= int(page.locator("#brightness").input_value()) <= 200
    page.locator("#filter-button").click()
    assert page.locator("#filter-button").get_attribute("aria-expanded") == "true"
    page.locator('[data-filter="normal"]').click()
    assert page.locator("#brightness").input_value() == "100"
    assert page.locator("#brightness").get_attribute("aria-valuetext") == "100%"


def test_closing_mask_panel_keeps_mask_state_accessible(page, viewer_server):
    page.goto(viewer_server + "/remote")
    page.locator("#mask-btn").click()
    page.locator("#filter-button").click()
    assert not page.locator("#mask-controls").is_visible()
    assert page.locator("#mask-btn").get_attribute("aria-pressed") == "true"
    assert page.locator("#mask-btn").get_attribute("aria-expanded") == "false"
    page.keyboard.press("Escape")
    assert page.locator("#filter-button").get_attribute("aria-expanded") == "false"
    assert page.locator("#mask-overlay").count() == 1


def test_latest_frame_queue_releases_urls_on_decode_error_and_cleanup(page, viewer_server):
    # Hold image decoding manually so bursts reliably arrive before onload.
    page.add_init_script("""
      window.Image = class {
        constructor() { this.naturalWidth = 160; this.naturalHeight = 90; window.testFrameImage = this; }
        removeAttribute() {}
      };
      CanvasRenderingContext2D.prototype.drawImage = function(...args) {
        window.lastDrawArguments = args.slice(1);
      };
    """)
    page.goto(viewer_server + "/remote")
    page.evaluate("""() => {
      for (let id = 1; id <= 100; id++) {
        testSocket.receive('frame', {data: new Uint8Array([id]), server_ts_ms: Date.now()});
      }
    }""")
    assert page.evaluate("activeFrameURLs.size") == 1
    assert page.evaluate("createdFrameBlobs.length") == 1
    page.evaluate("testFrameImage.onload()")
    assert page.evaluate("activeFrameURLs.size") == 1
    decoded_ids = page.evaluate("async () => Promise.all(createdFrameBlobs.map(async blob => new Uint8Array(await blob.arrayBuffer())[0]))")
    assert decoded_ids == [1, 100]
    page.evaluate("testFrameImage.onerror()")
    assert page.evaluate("activeFrameURLs.size") == 0
    page.evaluate("testSocket.receive('frame', {data: new Uint8Array([101])})")
    page.evaluate("testFrameImage.onload()")
    assert page.locator("#remote-status-badge").get_attribute("data-state") == "connected"
    page.evaluate("testSocket.receive('frame', {data: new Uint8Array([102])})")
    page.evaluate("cleanupViewerResources()")
    assert page.evaluate("activeFrameURLs.size") == 0
    assert page.evaluate("window.remoteStreamSocket") is None
    assert page.evaluate("testFrameImage.onload") is None


def test_real_jpeg_decoding_preserves_aspect_ratio_and_recovers(page, viewer_server):
    page.set_viewport_size({"width": 800, "height": 800})
    page.add_init_script("""
      const drawImage = CanvasRenderingContext2D.prototype.drawImage;
      CanvasRenderingContext2D.prototype.drawImage = function(...args) {
        window.lastDrawArguments = args.slice(1);
        return drawImage.apply(this, args);
      };
    """)
    page.goto(viewer_server + "/remote")
    frame = np.full((90, 160, 3), (0, 0, 255), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", frame)
    page.evaluate("data => testSocket.receive('frame', {data: new Uint8Array(data), server_ts_ms: Date.now()})", encoded.tolist())
    page.wait_for_function("window.lastDrawArguments && activeFrameURLs.size === 0")
    x, y, width, height = page.evaluate("lastDrawArguments")
    assert width / height == pytest.approx(16 / 9)
    assert x < 0 and y == 0
    pixel = page.evaluate("Array.from(document.getElementById('stream-canvas').getContext('2d').getImageData(400,400,1,1).data)")
    assert pixel[0] > 240 and pixel[1] < 10
    page.evaluate("testSocket.receive('disconnect')")
    assert page.locator("#remote-status-badge").get_attribute("data-state") == "error"
    page.evaluate("testSocket.receive('connect')")
    page.evaluate("data => testSocket.receive('frame', {data: new Uint8Array(data)})", encoded.tolist())
    page.wait_for_function("activeFrameURLs.size === 0")
    assert page.locator("#remote-status-badge").get_attribute("data-state") == "connected"


def test_camera_tracks_stop_on_navigation_and_late_permission_result(page, viewer_server):
    page.goto(viewer_server + "/samples")
    page.wait_for_function("document.getElementById('video').readyState >= 1")
    page.evaluate("window.originalTracks = document.getElementById('video').srcObject.getTracks()")
    page.evaluate("cleanupViewerResources()")
    assert page.evaluate("originalTracks.every(track => track.readyState === 'ended')")
    # A camera permission promise can resolve after Back has already been clicked.
    page.evaluate("""async () => {
      const track = {stop() { window.lateTrackStopped = true; }};
      navigator.mediaDevices.getUserMedia = async () => ({getTracks: () => [track]});
      await startCamera(document.getElementById('video'));
    }""")
    assert page.evaluate("lateTrackStopped")
    assert page.evaluate("document.getElementById('video').srcObject") is None


def test_tutorial_highlights_current_adjustment_controls(page, viewer_server):
    page.goto(viewer_server + "/samples?tutorial=1")
    for _ in range(4):
        page.locator(".tutorial-next-btn").click()
    page.wait_for_function("""() => {
      const highlight = document.querySelector('.tutorial-highlight').getBoundingClientRect();
      const grid = document.querySelector('.adjustment-grid').getBoundingClientRect();
      return Math.abs(highlight.width - grid.width - 24) < 1;
    }""")
    highlight = page.locator(".tutorial-highlight").bounding_box()
    grid = page.locator(".adjustment-grid").bounding_box()
    assert highlight["width"] == pytest.approx(grid["width"] + 24, abs=1)
    page.locator(".tutorial-exit-btn").click()
    assert page.locator(".tutorial-overlay").count() == 0


def test_filter_controls_remain_reachable_on_small_screen(page, viewer_server):
    page.set_viewport_size({"width": 390, "height": 600})
    page.goto(viewer_server + "/remote")
    page.locator("#filter-button").click()
    page.locator("#saturation").scroll_into_view_if_needed()
    bounds = page.locator("#saturation").bounding_box()
    assert 0 <= bounds["y"] < 600


def test_home_updates_a_previously_ready_tunnel_when_it_stops(page, viewer_server):
    status = {"status": "ready", "url": "https://example.trycloudflare.com"}
    page.route("**/tunnel-status", lambda route: route.fulfill(json=status))
    page.goto(viewer_server)
    playwright.expect(page.locator("#tunnel-url-text a")).to_have_attribute("href", status["url"])
    assert page.locator("#tunnel-qr-btn").is_visible()
    status.update(status="error", url=None)
    playwright.expect(page.locator("#tunnel-url-text")).to_have_text("Tunnel unavailable", timeout=7000)
    assert not page.locator("#tunnel-qr-btn").is_visible()
