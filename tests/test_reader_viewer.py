"""Real Chromium capture, accessible reader controls, and audio lifecycle."""
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
import wave

import cv2
import numpy as np
from PIL import Image
import pytest

from test_viewer import browser, page, viewer_server, set_range  # shared fixtures
import reader


READING = "Reading with confidence\n\nPlace your worksheet under the camera. Read the text at a size that is comfortable for you.\n\nYou can change the colors or listen to the page aloud."


def remote_image(width=1600, height=900):
    frame = np.full((height, width, 3), (255, 0, 0), dtype=np.uint8)
    frame[:, :width // 2] = (0, 0, 255)
    _, encoded = cv2.imencode(".jpg", frame)
    return encoded.tobytes()


def inject_remote_frame(page):
    page.evaluate("data => testSocket.receive('frame', {data: new Uint8Array(data)})", list(remote_image()))
    page.wait_for_function("readerRemoteFrame !== null")


def mock_reader(page, text=READING, speech=True, empty=False, snapshot_size=(1600, 900)):
    calls = {"images": [], "speech": [], "deleted": [], "snapshots": 0}
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x01" * 16000 * 15)
    def route_request(route):
        request = route.request
        path = request.url.split("/api/", 1)[1]
        if request.method == "DELETE":
            calls["deleted"].append(path.rsplit("/", 1)[-1])
            route.fulfill(status=204)
        elif path == "reader/status":
            route.fulfill(json={"ocr": True, "speech": speech})
        elif path == "reader/snapshot":
            assert request.method == "POST" and request.headers["x-magnifier-reader"] == "1"
            calls["snapshots"] += 1
            route.fulfill(body=remote_image(*snapshot_size), content_type="image/jpeg")
        elif path == "ocr":
            data = ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode() + request.post_data_buffer
            multipart = BytesParser(policy=policy.default).parsebytes(data)
            calls["images"].append(next(multipart.iter_parts()).get_payload(decode=True))
            route.fulfill(status=202, json={"id": "ocr-job", "state": "running"})
        elif path == "reader/speech":
            calls["speech"].append(request.post_data_json)
            route.fulfill(status=202, json={"id": "voice-job", "state": "running"})
        elif path.endswith("/audio"):
            route.fulfill(body=output.getvalue(), content_type="audio/wav")
        elif path.endswith("ocr-job"):
            route.fulfill(json={"state": "done", "result": {"text": "" if empty else text, "uncertain": False}})
        else:
            route.fulfill(json={"state": "done", "result": {"voice": "Piper"}})
    page.route("**/api/**", route_request)
    return calls


def ready_camera(page, viewer_server, route="/remote"):
    page.goto(viewer_server + route)
    if route == "/remote":
        inject_remote_frame(page)
    else:
        page.wait_for_function("document.getElementById('video').readyState >= 2")


@pytest.mark.parametrize("route", ["/samples", "/remote"])
def test_read_text_restores_camera_and_keeps_preferences(page, viewer_server, route):
    calls = mock_reader(page)
    ready_camera(page, viewer_server, route)
    set_range(page, "#zoom-slider", 2)
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-text').textContent.length > 0")
    assert page.locator("#reader-text").inner_text() == READING
    assert calls["images"][0].startswith(b"\x89PNG")
    assert calls["snapshots"] == (1 if route == "/remote" else 0)
    page.keyboard.press("+")
    assert page.locator("#zoom-slider").input_value() == "2"
    page.locator("#reader-larger").click()
    page.locator("#reader-filter-button").click()
    page.locator('[data-reader-color="yellow"]').click()
    assert page.locator("#reader-size-label").inner_text() == "36 px"
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('reader-dialog').open && activeFrameURLs.size === 0")
    assert page.locator("#read-text-btn").evaluate("el => el === document.activeElement")
    assert page.locator("#zoom-slider").input_value() == "2"
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-text').textContent.length > 0")
    assert page.locator('[data-reader-color="yellow"]').get_attribute("aria-pressed") == "true"
    assert page.locator("#reader-size-label").inner_text() == "36 px"


@pytest.mark.parametrize("source_size,expected_size", [((1600, 900), (600, 450)), ((3200, 1800), (1200, 900))])
def test_remote_capture_follows_crop_and_ignores_filters_and_mask(page, viewer_server, source_size, expected_size):
    calls = mock_reader(page, snapshot_size=source_size)
    page.set_viewport_size({"width": 800, "height": 600})
    ready_camera(page, viewer_server)
    page.evaluate("""() => {
        document.getElementById('stream-canvas').style.transition = 'none';
        zoomSlider.value = 2; adjustZoom(); translateX = 200; applyTransform();
        applyInverted(); enableBarsMask();
    }""")
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-text').textContent.length > 0")
    image = Image.open(BytesIO(calls["images"][0])).convert("RGB")
    assert image.size == expected_size
    red, blue = image.getpixel((50, image.height // 2)), image.getpixel((image.width - 50, image.height // 2))
    assert red[0] > 240 and red[1] < 15
    assert blue[2] > 240 and blue[1] < 15


def test_remote_snapshot_failure_is_shown_without_scanning_stale_preview(page, viewer_server):
    calls = mock_reader(page)
    page.route("**/api/reader/snapshot", lambda route: route.fulfill(
        status=503, json={"error": "Wait for the camera to connect, then scan again."}))
    ready_camera(page, viewer_server)
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-status').textContent.includes('camera to connect')")
    assert not calls["images"]


def test_cancelling_snapshot_does_not_start_ocr(page, viewer_server):
    calls = mock_reader(page)
    held = []
    def hold_snapshot(route):
        held.append(route)
        page.evaluate("window.testSnapshotHeld = true")
    page.route("**/api/reader/snapshot", hold_snapshot)
    ready_camera(page, viewer_server)
    page.locator("#read-text-btn").click()
    page.wait_for_function("window.testSnapshotHeld === true")
    assert held
    with page.expect_event("requestfailed", predicate=lambda request: request.url.endswith("/reader/snapshot")):
        page.locator("#reader-close").click()
    held[0].fulfill(body=remote_image(), content_type="image/jpeg")
    page.wait_for_function("activeFrameURLs.size === 0")
    assert not calls["images"]
    assert not page.locator("#reader-dialog").evaluate("dialog => dialog.open")


def test_reader_keeps_untrusted_ocr_as_plain_text(page, viewer_server):
    dangerous = '<img src=x onerror="window.ocrInjected=true">'
    mock_reader(page, text=dangerous)
    ready_camera(page, viewer_server)
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-text').textContent.length > 0")
    assert page.locator("#reader-text").inner_text() == dangerous
    assert page.locator("#reader-text img").count() == 0
    assert not page.evaluate("Boolean(window.ocrInjected)")


def test_late_scan_submission_is_cancelled_and_cannot_reopen_reader(page, viewer_server):
    calls = mock_reader(page)
    held = []
    def hold_submission(route):
        held.append(route)
        page.evaluate("window.testScanHeld = true")
    page.route("**/api/ocr", hold_submission)
    ready_camera(page, viewer_server)
    page.locator("#read-text-btn").click()
    page.wait_for_function("window.testScanHeld === true")
    assert held
    page.locator("#reader-close").click()
    with page.expect_response(lambda response: response.url.endswith('/late-job') and response.request.method == 'DELETE'):
        held[0].fulfill(status=202, json={"id": "late-job", "state": "running"})
    page.wait_for_function("activeFrameURLs.size === 0")
    assert "late-job" in calls["deleted"]
    assert not page.locator("#reader-dialog").evaluate("dialog => dialog.open")
    assert page.locator("#reader-text").inner_text() == ""


@pytest.mark.parametrize("size", [(1280, 720), (390, 600)])
def test_piper_recording_supports_pause_resume_speed_and_cleanup(page, viewer_server, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    calls = mock_reader(page)
    page.add_init_script("""
      const NativeAudio = window.Audio;
      window.Audio = function(...args) { window.testReaderAudio = new NativeAudio(...args); return testReaderAudio; };
      speechSynthesis.speak = () => { throw new Error('Browser voices must not be used'); };
    """)
    ready_camera(page, viewer_server)
    page.locator("#read-text-btn").click()
    page.wait_for_function("!document.getElementById('reader-speak').disabled")
    page.locator("#reader-speak").click()
    page.wait_for_function("!document.getElementById('reader-pause').hidden")
    assert calls["speech"] == [{"text": READING}]
    assert page.evaluate("testReaderAudio.src.startsWith('blob:') && !testReaderAudio.paused")
    for selector in ("#reader-pause", "#reader-stop", "#reader-rescan"):
        bounds = page.locator(selector).bounding_box()
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= size[0]
        assert bounds["y"] + bounds["height"] <= size[1]
    page.locator("#reader-pause").click()
    assert page.evaluate("testReaderAudio.paused")
    assert page.locator("#reader-pause").inner_text() == "Resume"
    page.locator("#reader-speed").select_option("0.75")
    assert page.evaluate("testReaderAudio.playbackRate") == 0.75
    page.locator("#reader-pause").click()
    page.wait_for_function("!testReaderAudio.paused")
    page.locator("#reader-stop").click()
    assert page.evaluate("testReaderAudio.paused && testReaderAudio.currentTime === 0")
    page.locator("#reader-close").click()
    page.wait_for_function("activeFrameURLs.size === 0 && !testReaderAudio.getAttribute('src')")


@pytest.mark.parametrize("empty,speech", [(True, True), (False, False)])
def test_empty_scan_and_unavailable_voice_have_clear_states(page, viewer_server, empty, speech):
    mock_reader(page, empty=empty, speech=speech)
    ready_camera(page, viewer_server)
    page.locator("#read-text-btn").click()
    page.wait_for_function("!document.getElementById('reader-actions').hidden")
    assert page.locator("#reader-speak").is_disabled()
    if empty:
        assert "No readable text" in page.locator("#reader-status").inner_text()
    else:
        assert "not available" in page.locator("#reader-notice").inner_text()


def test_missing_ocr_explains_installation_update_and_returns_to_camera(page, viewer_server):
    mock_reader(page)
    page.route("**/api/reader/status", lambda route: route.fulfill(json={"ocr": False, "speech": True}))
    ready_camera(page, viewer_server)
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-status').textContent.includes('installation needs updating')")
    assert page.locator("#reader-speak").is_disabled()
    page.locator("#reader-close").click()
    assert not page.locator("#reader-dialog").evaluate("dialog => dialog.open")


@pytest.mark.parametrize("size", [(1280, 720), (800, 480), (390, 600)])
def test_reader_layout_and_touch_controls_fit_screen(page, viewer_server, size):
    mock_reader(page)
    page.set_viewport_size({"width": size[0], "height": size[1]})
    ready_camera(page, viewer_server)
    # Force all camera toolbar controls visible to check the new button's fit.
    page.evaluate("zoomSlider.value = 2; adjustZoom(); translateX = 20; applyTransform();")
    for selector in ("#read-text-btn", "#reset-btn", "#center-btn"):
        bounds = page.locator(selector).bounding_box()
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= size[0]
    page.locator("#mask-btn").click()
    page.wait_for_function("document.getElementById('mask-controls').getBoundingClientRect().bottom + 8 <= document.getElementById('controls').getBoundingClientRect().top")
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-text').textContent.length > 0")
    assert page.locator("#reader-body").evaluate("el => el.scrollWidth <= el.clientWidth")
    for selector in ("#reader-close", "#reader-speak", "#reader-rescan", "#reader-larger"):
        bounds = page.locator(selector).bounding_box()
        assert bounds["height"] >= 48
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= size[0]
        assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= size[1]
    reports = Path(__file__).resolve().parents[1] / ".reports"
    reports.mkdir(exist_ok=True)
    page.screenshot(path=str(reports / f"reader-{size[0]}x{size[1]}.png"))


@pytest.mark.skipif(not reader.availability()["ocr"], reason="Install OCR for end-to-end check")
@pytest.mark.parametrize("read_aloud", [False, True])
def test_real_camera_image_to_ocr_and_optional_piper_audio(page, viewer_server, read_aloud):
    if read_aloud and not reader.availability()["speech"]:
        pytest.skip("Install Piper and its voice for the audio check")
    from test_reader import page_image
    page.set_viewport_size({"width": 1300, "height": 500})
    page.add_init_script("""
      const NativeAudio = window.Audio;
      window.Audio = function(...args) { window.testReaderAudio = new NativeAudio(...args); return testReaderAudio; };
      speechSynthesis.speak = () => { throw new Error('Browser voices must not be used'); };
    """)
    page.goto(viewer_server + "/remote")
    frame = cv2.imdecode(np.frombuffer(page_image(), dtype=np.uint8), cv2.IMREAD_COLOR)
    encoded = cv2.imencode(".jpg", frame)[1]
    page.route("**/api/reader/snapshot", lambda route: route.fulfill(body=encoded.tobytes(), content_type="image/jpeg"))
    page.evaluate("data => testSocket.receive('frame', {data: new Uint8Array(data)})", encoded.tolist())
    page.wait_for_function("readerRemoteFrame !== null")
    page.locator("#read-text-btn").click()
    page.wait_for_function("document.getElementById('reader-text').textContent.includes('magnifier')", timeout=45000)
    assert "students learn" in page.locator("#reader-text").inner_text()
    if read_aloud:
        page.locator("#reader-speak").click()
        page.wait_for_function("!document.getElementById('reader-pause').hidden", timeout=125000)
        assert page.evaluate("testReaderAudio.duration > 2 && !testReaderAudio.paused")
    page.locator("#reader-close").click()
    page.wait_for_function("activeFrameURLs.size === 0")
