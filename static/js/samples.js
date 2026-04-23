const videoElement = document.getElementById('video');
const remoteCanvasElement = document.getElementById('stream-canvas');
const remoteCanvasContext = remoteCanvasElement?.getContext('2d') ?? null;
const viewerElement = videoElement || remoteCanvasElement;
const isRemoteCanvasMode = !videoElement && !!remoteCanvasElement;

// WeakSet used by _ensureMaskUIExists to track which mask buttons already have
// their event listener attached, without polluting DOM element properties.
const _barsMaskHookedButtons = new WeakSet();
const videoContainer = document.getElementById('video-container');
const menu = document.getElementById('menu');
const zoomSlider = document.getElementById('zoom-slider');

let scale = 1; // scale
let translateX = 0; // X-axis translation
let translateY = 0; // Y-axis translation
const CENTER_TOLERANCE_PX = 1;

// Default values for custom filters
const customFilters = {
    hue: 0,
    brightness: 100,
    contrast: 100,
    saturation: 100,
};

// ── Settings persistence ──────────────────────────────────────────────────────
const _SETTINGS_KEY = 'magnifier_settings';

function _saveSettings() {
    try {
        localStorage.setItem(_SETTINGS_KEY, JSON.stringify({
            zoom: scale,
            filterKey: (document.querySelector('.filter-btn[data-filter].active') || {}).dataset?.filter ?? 'normal',
            customFilters: { ...customFilters },
            mask: {
                enabled: _barsMaskState.enabled,
                barPct: _barsMaskState.barPct,
                orientation: _barsMaskState.orientation,
                inverted: _barsMaskState.inverted,
            },
        }));
    } catch (_) { /* localStorage unavailable (private/incognito mode) */ }
}

function _restoreSettings() {
    let saved;
    try {
        const raw = localStorage.getItem(_SETTINGS_KEY);
        if (!raw) return;
        saved = JSON.parse(raw);
    } catch (_) { return; }

    // Restore zoom
    if (typeof saved.zoom === 'number' && saved.zoom >= 1) {
        if (zoomSlider) zoomSlider.value = String(saved.zoom);
        adjustZoom();
    }

    // Restore predefined filter
    if (saved.filterKey) {
        const filterFunctions = {
            'normal': applyNormal,
            'protanopia': applyProtanopia,
            'deuteranopia': applyDeuteranopia,
            'tritanopia': applyTritanopia,
            'grayscale': applyGrayscale,
            'inverted': applyInverted,
            'inverted-grayscale': applyInvertedGrayscale,
            'blue-on-yellow': applyBlueOnYellow,
            'orange-on-black': applyNeonOrangeOnBlack,
            'green-on-black': applyNeonGreenOnBlack,
            'yellow-on-black': applyYellowOnBlack,
            'purple-on-black': applyPurpleOnBlack,
        };
        const fn = filterFunctions[saved.filterKey];
        if (fn) {
            fn();
            _setActiveFilterBtn(saved.filterKey);
        }
    }

    // Restore custom filter sliders
    if (saved.customFilters) {
        ['hue', 'brightness', 'contrast', 'saturation'].forEach(key => {
            if (typeof saved.customFilters[key] !== 'undefined') {
                customFilters[key] = saved.customFilters[key];
                const el = document.getElementById(key);
                if (el) el.value = saved.customFilters[key];
            }
        });
        applyCombinedFilters();
    }

    // Restore mask state
    if (saved.mask) {
        _barsMaskState.barPct = saved.mask.barPct ?? _barsMaskState.barPct;
        _barsMaskState.orientation = saved.mask.orientation ?? _barsMaskState.orientation;
        _barsMaskState.inverted = saved.mask.inverted ?? _barsMaskState.inverted;
        const radiusEl = document.getElementById('mask-radius');
        if (radiusEl) radiusEl.value = String(_barsMaskState.barPct);
        updateMaskOrientationButton();
        updateMaskInvertButton();
        if (saved.mask.enabled) enableBarsMask();
    }
}

function _setActiveFilterBtn(key) {
    document.querySelectorAll('.filter-btn[data-filter]').forEach(btn => {
        const isActive = btn.dataset.filter === key;
        btn.classList.toggle('active', isActive);
        btn.classList.toggle('selected', isActive);
        btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
}
// ── End settings persistence ──────────────────────────────────────────────────

function wireTouchFriendlyRangeInput(input) {
  if (!input || input.dataset.touchGuardWired === 'true') return;

  const stopPropagation = (event) => {
    event.stopPropagation();
  };

  ['touchstart', 'touchmove', 'touchend', 'touchcancel', 'pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach((type) => {
    input.addEventListener(type, stopPropagation, { passive: true });
  });

  input.dataset.touchGuardWired = 'true';
}

const orientationBtn = document.getElementById('mask-orientation-btn');
if (orientationBtn) {
  orientationBtn.addEventListener('click', () => {
    _barsMaskState.orientation = 'horizontal';
    updateMaskOrientationButton();
    drawBarsMask();
    _saveSettings();
  });
}

const verticalBtn = document.getElementById('mask-vertical-btn');
if (verticalBtn) {
  verticalBtn.addEventListener('click', () => {
    _barsMaskState.orientation = 'vertical';
    updateMaskOrientationButton();
    drawBarsMask();
    _saveSettings();
  });
}

function updateMaskOrientationButton() {
  const hBtn = document.getElementById('mask-orientation-btn');
  const vBtn = document.getElementById('mask-vertical-btn');
  if (hBtn) hBtn.classList.toggle('active', _barsMaskState.orientation === 'horizontal');
  if (vBtn) vBtn.classList.toggle('active', _barsMaskState.orientation === 'vertical');
}

// Default filter (none)
let currentFilter = 'none';

let isDragging = false; // Track dragging state
let startX = 0; // Initial X position on drag start
let startY = 0; // Initial Y position on drag start

let _panRafId     = null; // rAF handle for batched pan updates
let _pendingPanDx = 0;    // accumulated horizontal delta since last rAF
let _pendingPanDy = 0;    // accumulated vertical   delta since last rAF

// Pinch-to-zoom state (two-finger touch)
let _pinching       = false;
let _pinchStartDist = 0;
let _pinchStartZoom = 1;

/* ---------- Camera / 1080p helpers ---------- */
/**
 * startCamera(videoEl, opts)
 *  - requests camera with preferred 1920x1080 resolution.
 *  - opts: { preferExact1080: boolean }  // default false (uses ideal: 1920x1080)
 *  - returns the MediaStream that was obtained.
 */
async function startCamera(videoEl, opts = {}) {
  if (!videoEl || !(videoEl instanceof HTMLVideoElement)) {
    throw new Error('startCamera: videoEl must be a HTMLVideoElement');
  }

  const preferExact = !!opts.preferExact1080;
  const widthConstraint = preferExact ? { exact: 1920 } : { ideal: 1920 };
  const heightConstraint = preferExact ? { exact: 1080 } : { ideal: 1080 };

  const constraints = {
    audio: false,
    video: {
      width: widthConstraint,
      height: heightConstraint,
      frameRate: { ideal: 30, max: 60 }
    }
  };

  try {
    // Stop existing stream if any (avoid leak when re-initializing)
    if (videoEl.srcObject && typeof videoEl.srcObject.getTracks === 'function') {
      videoEl.srcObject.getTracks().forEach((t) => t.stop());
    }
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    videoEl.srcObject = stream;
    videoEl.autoplay = true;
    videoEl.playsInline = true;
    videoEl.muted = true; // recommended for autoplay

    // Wait for metadata so video.videoWidth/video.videoHeight are available.
    // Race against a 5-second timeout so we don't hang indefinitely on slow cameras.
    await Promise.race([
      new Promise((resolve) => {
        if (videoEl.readyState >= 1 && videoEl.videoWidth && videoEl.videoHeight) {
          return resolve();
        }
        function onMeta() {
          videoEl.removeEventListener('loadedmetadata', onMeta);
          resolve();
        }
        videoEl.addEventListener('loadedmetadata', onMeta);
      }),
      new Promise((_, reject) =>
        setTimeout(
          () => reject(new Error('Camera metadata timed out after 5 s')),
          5000,
        )
      ),
    ]);

    console.log('Camera started. Negotiated resolution:', videoEl.videoWidth, 'x', videoEl.videoHeight);
    return stream;
  } catch (err) {
    console.error('startCamera: getUserMedia failed', err);
    throw err;
  }
}

function setCanvasToVideoSize(canvas, videoEl, scale = 1.0) {
  if (!canvas || !videoEl) return;

  // Prefer intrinsic video pixel size; fallback to CSS layout size
  const videoPixelW = videoEl.videoWidth || Math.round(videoEl.getBoundingClientRect().width);
  const videoPixelH = videoEl.videoHeight || Math.round(videoEl.getBoundingClientRect().height);

  const w = Math.max(1, Math.round(videoPixelW * scale));
  const h = Math.max(1, Math.round(videoPixelH * scale));

  // Pixel buffer size used for processing
  canvas.width = w;
  canvas.height = h;

  // CSS size (how big the canvas appears on the page) — match layout to preserve appearance
  canvas.style.width = `${Math.round(videoPixelW)}px`;
  canvas.style.height = `${Math.round(videoPixelH)}px`;
}

function resizeRemoteCanvas() {
  if (!remoteCanvasElement) return;
  remoteCanvasElement.width = window.innerWidth;
  remoteCanvasElement.height = window.innerHeight;
}

function updateRemoteStatus(text, state = 'default') {
  const badge = document.getElementById('remote-status-badge');
  if (!badge) return;
  badge.textContent = text;
  badge.dataset.state = state;
}

function formatRemoteStatus(baseText, latencyMs = null) {
  if (typeof latencyMs !== 'number' || Number.isNaN(latencyMs)) {
    return baseText;
  }
  return `${baseText} (${Math.max(0, Math.round(latencyMs))}ms)`;
}

function initializeRemoteSocketStream() {
  if (!remoteCanvasElement || !remoteCanvasContext || typeof window.io !== 'function') {
    updateRemoteStatus('Streaming unavailable', 'error');
    return;
  }

  resizeRemoteCanvas();
  window.addEventListener('resize', resizeRemoteCanvas);

  const socket = window.io('/stream', {
    transports: ['websocket'],
    reconnectionDelay: 1000,
    reconnectionAttempts: Infinity,
    closeOnBeforeunload: true,
  });
  const frameImage = new Image();
  let _prevFrameUrl = null;
  const remoteStatusState = {
    baseText: 'Remote Feed - Connecting...',
    state: 'default',
    latencyMs: null,
  };

  window.remoteStreamSocket = socket;

  function renderRemoteStatus() {
    updateRemoteStatus(
      formatRemoteStatus(remoteStatusState.baseText, remoteStatusState.latencyMs),
      remoteStatusState.state,
    );
  }

  socket.on('connect', () => {
    // Clear any stale frame from a previous session before live frames arrive.
    remoteCanvasContext.clearRect(0, 0, remoteCanvasElement.width, remoteCanvasElement.height);
    if (_prevFrameUrl) { URL.revokeObjectURL(_prevFrameUrl); _prevFrameUrl = null; }
    remoteStatusState.baseText = 'Remote Feed - Connected';
    remoteStatusState.state = 'connected';
    remoteStatusState.latencyMs = null;
    renderRemoteStatus();
  });

  socket.on('disconnect', () => {
    remoteStatusState.baseText = 'Remote Feed - Reconnecting...';
    remoteStatusState.state = 'error';
    remoteStatusState.latencyMs = null;
    renderRemoteStatus();
  });

  socket.on('stream_status', (payload) => {
    if (payload?.state === 'error') {
      remoteStatusState.baseText = `Remote Feed - ${payload.message || 'Camera unavailable'}`;
      remoteStatusState.state = 'error';
      remoteStatusState.latencyMs = null;
      renderRemoteStatus();
    }
  });

  socket.on('frame', (payload) => {
    if (typeof payload?.server_ts_ms === 'number') {
      remoteStatusState.baseText = 'Remote Feed - Connected';
      remoteStatusState.state = 'connected';
      remoteStatusState.latencyMs = Date.now() - payload.server_ts_ms;
      renderRemoteStatus();
    }

    frameImage.onload = () => {
      remoteCanvasContext.clearRect(0, 0, remoteCanvasElement.width, remoteCanvasElement.height);
      remoteCanvasContext.drawImage(frameImage, 0, 0, remoteCanvasElement.width, remoteCanvasElement.height);
      if (_prevFrameUrl) {
        URL.revokeObjectURL(_prevFrameUrl);
        _prevFrameUrl = null;
      }
    };
    const frameBlob = new Blob([payload.data], { type: 'image/jpeg' });
    const frameUrl = URL.createObjectURL(frameBlob);
    _prevFrameUrl = frameUrl;
    frameImage.src = frameUrl;
  });
}

function stopRemoteSocketStream() {
  if (window.remoteStreamSocket && typeof window.remoteStreamSocket.disconnect === 'function') {
    window.remoteStreamSocket.disconnect();
    window.remoteStreamSocket = null;
  }
}

function stopLocalCameraStream() {
  if (videoElement?.srcObject && typeof videoElement.srcObject.getTracks === 'function') {
    videoElement.srcObject.getTracks().forEach((track) => track.stop());
    videoElement.srcObject = null;
  }
}

function cleanupViewerResources() {
  stopLocalCameraStream();
  stopRemoteSocketStream();
}

/* Camera is started once in the async IIFE below; no duplicate DOMContentLoaded start here. */
/* ---------- end camera / 1080p helpers ---------- */


// Add event listeners to enable drag panning
videoContainer.addEventListener('mousedown', (e) => {
    isDragging = true;
    startX = e.clientX; // Record the starting X position
    startY = e.clientY; // Record the starting Y position
    videoContainer.style.cursor = 'grabbing';
});

videoContainer.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    _pendingPanDx += e.clientX - startX;
    _pendingPanDy += e.clientY - startY;
    startX = e.clientX;
    startY = e.clientY;
    if (!_panRafId) {
        _panRafId = requestAnimationFrame(() => {
            translateX    += _pendingPanDx;
            translateY    += _pendingPanDy;
            _pendingPanDx  = 0;
            _pendingPanDy  = 0;
            _panRafId      = null;
            applyTransform();
        });
    }
});

videoContainer.addEventListener('mouseup', () => {
    isDragging = false;
    videoContainer.style.cursor = 'grab';
});

videoContainer.addEventListener('mouseleave', () => {
    isDragging = false;
    videoContainer.style.cursor = 'grab';
});

videoContainer.addEventListener('touchstart', (e) => {
    if (e.target?.closest?.('input[type="range"]')) return;
    if (e.touches.length === 2) {
        _pinching       = true;
        isDragging      = false;
        _pinchStartDist = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY,
        );
        _pinchStartZoom = scale;
    } else {
        _pinching  = false;
        isDragging = true;
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
    }
});

videoContainer.addEventListener('touchmove', (e) => {
    if (e.target?.closest?.('input[type="range"]')) return;
    e.preventDefault();
    if (_pinching && e.touches.length === 2) {
        const dist = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY,
        );
        const minZ = parseFloat(zoomSlider?.min) || 1;
        const maxZ = parseFloat(zoomSlider?.max) || 5;
        const newZ = Math.round(
            Math.max(minZ, Math.min(maxZ, _pinchStartZoom * (dist / _pinchStartDist))) * 10
        ) / 10;
        if (zoomSlider) zoomSlider.value = newZ;
        adjustZoom();
    } else if (isDragging && e.touches.length === 1) {
        _pendingPanDx += e.touches[0].clientX - startX;
        _pendingPanDy += e.touches[0].clientY - startY;
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        if (!_panRafId) {
            _panRafId = requestAnimationFrame(() => {
                translateX    += _pendingPanDx;
                translateY    += _pendingPanDy;
                _pendingPanDx  = 0;
                _pendingPanDy  = 0;
                _panRafId      = null;
                applyTransform();
            });
        }
    }
}, { passive: false });

videoContainer.addEventListener('touchend', (e) => {
    if (e.target?.closest?.('input[type="range"]')) return;
    if (e.touches.length < 2)  _pinching  = false;
    if (e.touches.length === 0) isDragging = false;
});

// Constrain movement within bounds
function constrainMovement() {
    const containerWidth = videoContainer.offsetWidth;
    const containerHeight = videoContainer.offsetHeight;
    const videoWidth = viewerElement.offsetWidth * scale;
    const videoHeight = viewerElement.offsetHeight * scale;

    // Determine the max translations to keep the video within bounds
    const maxTranslateX = (videoWidth - containerWidth) / 2;
    const maxTranslateY = (videoHeight - containerHeight) / 2;

    // Constrain translateX and translateY within the calculated boundaries
    translateX = Math.max(-maxTranslateX, Math.min(maxTranslateX, translateX));
    translateY = Math.max(-maxTranslateY, Math.min(maxTranslateY, translateY));
}

function isViewCentered() {
    return Math.abs(translateX) <= CENTER_TOLERANCE_PX && Math.abs(translateY) <= CENTER_TOLERANCE_PX;
}

function updateCenterButtonVisibility() {
    const centerBtn = document.getElementById('center-btn');
    if (!centerBtn) return;
    const isZoomedIn = scale > 1.01;
    centerBtn.style.display = isZoomedIn && !isViewCentered() ? 'inline-block' : 'none';
}

function centerView() {
    translateX = 0;
    translateY = 0;
    applyTransform();
}

window.centerView = centerView;

// Apply transformations (zoom and pan)
function applyTransform() {
    constrainMovement(); // Ensure panning stays within bounds
    viewerElement.style.transform = `translate(-50%, -50%) translate(${translateX}px, ${translateY}px) scale(${scale})`;
    updateCenterButtonVisibility();
}

// Zoom using the vertical slider; update aria for screen readers
function adjustZoom() {
    scale = parseFloat(zoomSlider.value);
    applyTransform();
    const resetBtn = document.getElementById('reset-btn');
    if (resetBtn) {
        if (scale > 1.01) {
            resetBtn.style.display = 'inline-block';
        } else {
            resetBtn.style.display = 'none';
        }
    }
    updateCenterButtonVisibility();
    if (zoomSlider) {
        zoomSlider.setAttribute('aria-valuenow', String(scale));
        zoomSlider.setAttribute('aria-valuetext', `Zoom ${scale.toFixed(1)}x`);
    }
    const zoomLabel = document.querySelector('.zoom-label');
    if (zoomLabel) zoomLabel.textContent = `${scale % 1 === 0 ? scale : scale.toFixed(1)}×`;
    _saveSettings();
}

// Change zoom via + / - buttons by delta (e.g., 0.1)
function changeZoom(delta) {
    const resetBtn = document.getElementById('reset-btn');
    if (!zoomSlider) return;

    const min = parseFloat(zoomSlider.min) || 1;
    const max = parseFloat(zoomSlider.max) || 5;
    const step = parseFloat(zoomSlider.step) || 0.1;

    let newZoom = parseFloat(zoomSlider.value) + delta;

    // round to nearest step precision
    const precision = (step.toString().split('.')[1] || '').length;
    const factor = Math.pow(10, precision);
    newZoom = Math.round(newZoom * factor) / factor;

    // clamp
    newZoom = Math.max(min, Math.min(max, newZoom));

    zoomSlider.value = newZoom;
    // call your existing adjustZoom to apply the change
    if (typeof adjustZoom === 'function') {
        adjustZoom();
    } else {
        // fallback: trigger change event
        zoomSlider.dispatchEvent(new Event('change', { bubbles: true }));
    }

    if (resetBtn) {
        if (newZoom > 1.01) {
        resetBtn.style.display = 'inline-block';
        } else {
        resetBtn.style.display = 'none';
        }
    }
    updateCenterButtonVisibility();
}

// Combine Predefined and Adjustable Custom Filters
function applyCombinedFilters() {
    const predefinedFilter = currentFilter !== 'none' ? currentFilter : '';
    const adjustableFilter = `hue-rotate(${customFilters.hue}deg) brightness(${customFilters.brightness}%) contrast(${customFilters.contrast}%) saturate(${customFilters.saturation}%)`;

    viewerElement.style.filter = `${predefinedFilter} ${adjustableFilter}`.trim();
}

// Adjustable Custom Filters
function applyCustomFilter() {
    customFilters.hue        = document.getElementById('hue').value;
    customFilters.brightness = document.getElementById('brightness').value;
    customFilters.contrast   = document.getElementById('contrast').value;
    customFilters.saturation = document.getElementById('saturation').value;
    applyCombinedFilters();
    // B — keep aria-valuetext in sync for screen readers
    const hueEl        = document.getElementById('hue');
    const brightnessEl = document.getElementById('brightness');
    const contrastEl   = document.getElementById('contrast');
    const saturationEl = document.getElementById('saturation');
    if (hueEl)        hueEl.setAttribute('aria-valuetext',        `${customFilters.hue}\u00b0`);
    if (brightnessEl) brightnessEl.setAttribute('aria-valuetext', `${customFilters.brightness}%`);
    if (contrastEl)   contrastEl.setAttribute('aria-valuetext',   `${customFilters.contrast}%`);
    if (saturationEl) saturationEl.setAttribute('aria-valuetext', `${customFilters.saturation}%`);
    _saveSettings();
}

// Predefined Filters
function applyFilter(filter) {
    currentFilter = filter;
    applyCombinedFilters();
}

(async () => {
    if (isRemoteCanvasMode) {
        applyTransform();
        initializeRemoteSocketStream();
        return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.error('getUserMedia is not supported in this browser');
        return;
    }

    try {
        // startCamera will set videoElement.srcObject and wait for loadedmetadata
        await startCamera(videoElement, { preferExact1080: false });

        // Guard: if the element was removed while the async camera start was in progress, bail out.
        if (!document.body.contains(videoElement)) return;

        // Stop camera when leaving the page (e.g. Back button) so the camera LED turns off
        // Optional: after camera starts, align any overlay / processing canvases to the native video pixels
        const overlayIds = ['overlay-canvas', 'tritanopia-overlay-canvas'];
        overlayIds.forEach(id => {
            const c = document.getElementById(id);
            if (c instanceof HTMLCanvasElement) setCanvasToVideoSize(c, videoElement, 1.0);
        });

        console.log('Camera stream active. Negotiated resolution (videoElement):', videoElement.videoWidth, 'x', videoElement.videoHeight);
    } catch (err) {
        console.error('Camera startup failed:', err);

        const isPermissionDenied = err?.name === 'NotAllowedError';
        const isNoDevice = err?.name === 'NotFoundError' || err?.name === 'NotReadableError';
        const title = isPermissionDenied
            ? 'Camera access was denied'
            : isNoDevice
            ? 'No camera found'
            : 'Camera error';
        const message = isPermissionDenied
            ? 'Please allow camera access in your browser settings, then reload the page.'
            : isNoDevice
            ? 'Make sure the camera is connected and not in use by another app.'
            : 'The camera could not be started. Try reloading the page.';

        if (videoContainer) {
            const errCard = document.createElement('div');
            errCard.className = 'camera-error';
            const h2 = document.createElement('h2');
            h2.textContent = title;
            const p = document.createElement('p');
            p.textContent = message;
            const retryBtn = document.createElement('button');
            retryBtn.className = 'btn';
            retryBtn.textContent = 'Retry';
            retryBtn.addEventListener('click', () => window.location.reload());
            errCard.append(h2, p, retryBtn);
            videoContainer.appendChild(errCard);
        }
    }
})();

function resetFilterSliders() {
    // Default values (must match the defaults used when page first loads)
    const defaultHue = 0;
    const defaultBrightness = 100;
    const defaultContrast = 100;
    const defaultSaturation = 100;

    // Update the DOM slider inputs if they exist
    const hueEl = document.getElementById('hue');
    const brightnessEl = document.getElementById('brightness');
    const contrastEl = document.getElementById('contrast');
    const saturationEl = document.getElementById('saturation');

    if (hueEl) hueEl.value = defaultHue;
    if (brightnessEl) brightnessEl.value = defaultBrightness;
    if (contrastEl) contrastEl.value = defaultContrast;
    if (saturationEl) saturationEl.value = defaultSaturation;

    // Update the in-memory customFilters object so code uses the new values
    if (typeof customFilters === 'object') {
        customFilters.hue = defaultHue;
        customFilters.brightness = defaultBrightness;
        customFilters.contrast = defaultContrast;
        customFilters.saturation = defaultSaturation;
    }

    // Apply the combined filters (this will apply 'none' for predefined filter and the adjusted sliders)
    applyCombinedFilters();

    // If you have any UI that depends on slider change events (labels, preview, etc.), optionally dispatch 'input' events:
    [hueEl, brightnessEl, contrastEl, saturationEl].forEach(el => {
        if (el) el.dispatchEvent(new Event('input', { bubbles: true }));
    });
}

// Replace your applyNormal function with this (or update its body to call resetFilterSliders)
function applyNormal() {
    // Set predefined filter to 'none'
    applyFilter('none');

    // Reset slider UI and values to defaults
    resetFilterSliders();
    _setActiveFilterBtn('normal');
    _saveSettings();
}

function applyProtanopia() {
    applyFilter('url(#filter-protanopia)');
}

function applyDeuteranopia() {
    applyFilter('url(#filter-deuteranopia)');
}

function applyTritanopia() {
    applyFilter('url(#filter-tritanopia)');
}

function applyGrayscale() {
    applyFilter('grayscale(100%)');
}

function applyInverted() {
    applyFilter('invert(100%)');
}

function applyInvertedGrayscale() {
    applyFilter('grayscale(100%) invert(100%)');
}

function applyBlueOnYellow() {
    applyFilter('sepia(100%) hue-rotate(180deg) saturate(300%) brightness(50%)');
}

function applyNeonOrangeOnBlack() {
    applyFilter('invert(100%) sepia(100%) saturate(500%) hue-rotate(330deg) brightness(50%) contrast(200%)');
}

function applyNeonGreenOnBlack() {
    applyFilter('invert(100%) sepia(100%) saturate(500%) hue-rotate(90deg) brightness(50%) contrast(200%)');
}

function applyYellowOnBlack() {
    applyFilter('invert(100%) brightness(80%) contrast(200%) sepia(100%) hue-rotate(60deg)');
}

function applyPurpleOnBlack() {
    applyFilter('invert(100%) brightness(70%) contrast(200%) sepia(100%) hue-rotate(300deg)');
}

function isFilterMenuOpen() {
    return !!menu?.classList.contains('active');
}

function setFilterMenuPosition() {
    // Position is handled entirely by CSS (fixed top:80px left:50% translateX(-50%)).
    // Nothing to override here.
}

function showFilterMenu() {
    if (!menu) return;
    hideMaskControls();
    setFilterMenuPosition();
    menu.classList.add('active');
    const filterButton = document.getElementById('filter-button');
    if (filterButton) filterButton.classList.add('active');
}

function hideFilterMenu() {
    if (!menu) return;
    menu.classList.remove('active');
    const filterButton = document.getElementById('filter-button');
    if (filterButton) filterButton.classList.remove('active');
}

function toggleFilterMenu() {
    if (isFilterMenuOpen()) {
        hideFilterMenu();
    } else {
        showFilterMenu();
    }
}

function isMaskControlsOpen() {
    const controls = document.getElementById('mask-controls');
    return !!controls && controls.style.display !== 'none';
}

function showMaskControls() {
    hideFilterMenu();
    if (!_barsMaskState.enabled) {
        enableBarsMask();
    }

    const controls = document.getElementById('mask-controls');
    if (controls) controls.style.display = 'flex';
    const btn = document.getElementById('mask-btn');
    if (btn) btn.classList.add('active'), btn.setAttribute('aria-pressed', 'true');
}

function hideMaskControls() {
    const controls = document.getElementById('mask-controls');
    if (controls) controls.style.display = 'none';
    const btn = document.getElementById('mask-btn');
    if (btn) btn.classList.remove('active'), btn.setAttribute('aria-pressed', 'false');
}

function toggleMaskControls() {
    if (isMaskControlsOpen()) {
        hideMaskControls();
    } else {
        showMaskControls();
    }
}

function closeAllPanels() {
    hideFilterMenu();
    hideMaskControls();
}

function isTutorialOpen() {
    return !!document.querySelector('.tutorial-overlay');
}

/* ---------- Reset Zoom Button Logic ---------- */

// reference slider and button once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const slider = document.getElementById('zoom-slider');
    const resetBtn = document.getElementById('reset-btn');

    if (!slider || !resetBtn) return;

    // Show / hide Reset Zoom button depending on zoom level
    function updateResetButtonVisibility() {
        const val = parseFloat(slider.value) || 1;
        if (val > 1.01) {
            resetBtn.style.display = 'inline-block';
        } else {
            resetBtn.style.display = 'none';
        }
        updateCenterButtonVisibility();
    }

    // Hook into existing slider behaviour (zoom + reset button visibility + aria)
    function onZoomInput() {
        adjustZoom();
        updateResetButtonVisibility();
    }
    slider.addEventListener('input', onZoomInput);
    slider.addEventListener('change', onZoomInput);

    // Button listeners (no inline handlers)
    document.getElementById('back-btn')?.addEventListener('click', goHome);
    document.getElementById('filter-button')?.addEventListener('click', toggleFilterMenu);
    document.getElementById('center-btn')?.addEventListener('click', centerView);
    resetBtn.addEventListener('click', () => window.resetZoom());

    document.getElementById('zoom-in')?.addEventListener('click', () => changeZoom(0.1));
    document.getElementById('zoom-out')?.addEventListener('click', () => changeZoom(-0.1));

    // Filter buttons by data-filter
    const filterMap = {
        'normal': applyNormal,
        'protanopia': applyProtanopia,
        'deuteranopia': applyDeuteranopia,
        'tritanopia': applyTritanopia,
        'grayscale': applyGrayscale,
        'inverted': applyInverted,
        'inverted-grayscale': applyInvertedGrayscale,
        'blue-on-yellow': applyBlueOnYellow,
        'orange-on-black': applyNeonOrangeOnBlack,
        'green-on-black': applyNeonGreenOnBlack,
        'yellow-on-black': applyYellowOnBlack,
        'purple-on-black': applyPurpleOnBlack
    };
    document.querySelectorAll('.filter-btn[data-filter]').forEach((btn) => {
        const key = btn.dataset.filter;
        const fn = filterMap[key];
        if (fn) btn.addEventListener('click', () => {
            fn();
            _setActiveFilterBtn(key);
            _saveSettings();
        });
    });

    // Custom filter sliders
    ['hue', 'brightness', 'contrast', 'saturation'].forEach((id) => {
        document.getElementById(id)?.addEventListener('input', applyCustomFilter);
        document.getElementById(id)?.addEventListener('change', applyCustomFilter);
    });

    // Actual Reset Zoom function
    window.resetZoom = function () {
        scale = 1;
        translateX = 0;
        translateY = 0;
        slider.value = '1';
        applyTransform();
        resetBtn.style.display = 'none';
        updateCenterButtonVisibility();
        if (slider) {
            slider.setAttribute('aria-valuenow', '1');
            slider.setAttribute('aria-valuetext', 'Zoom 1x');
        }
    };

    // Initialize button state and zoom aria on page load
    updateResetButtonVisibility();
    adjustZoom();

    // Persist save on resetZoom too
    const _origResetZoom = window.resetZoom;
    window.resetZoom = function () {
        _origResetZoom();
        _saveSettings();
    };
});

// Back button function
function goHome() {
    cleanupViewerResources();
    window.location.href = "/";
}

window.addEventListener('pagehide', cleanupViewerResources);
window.addEventListener('beforeunload', cleanupViewerResources);
/* ---------- Robust letterbox mask (top + bottom bars) feature ----------
   Drop this whole block into samples.js after videoElement / video-container are defined.
   It will create missing UI if needed and ensures the mask canvas is inserted under UI.
--------------------------------------------------------------------- */

const _barsMaskState = {
  enabled: false,
  canvas: null,
  ctx: null,

  // percentage of dimension (0–50)
  barPct: 5,

  // orientation: 'horizontal' = top/bottom, 'vertical' = left/right
  orientation: 'horizontal',
  inverted: false,

  resizeObserver: null
};

const _DEFAULT_MASK_STATE = {
  barPct: 5,
  orientation: 'horizontal',
  inverted: false,
};

function _ensureMaskUIExists() {
  // Ensure #controls exists
  let controls = document.getElementById('controls');
  const videoContainer = document.getElementById('video-container') || viewerElement?.parentElement;

  // If no #controls, create one at bottom center of video-container
  if (!controls && videoContainer) {
    controls = document.createElement('div');
    controls.id = 'controls';
    controls.style.position = 'absolute';
    controls.style.bottom = '10px';
    controls.style.left = '50%';
    controls.style.transform = 'translateX(-50%)';
    controls.style.display = 'flex';
    controls.style.gap = '10px';
    videoContainer.appendChild(controls);
  }

  // Create mask button if missing
  let maskBtn = document.getElementById('mask-btn');
  if (!maskBtn && controls) {
    maskBtn = document.createElement('button');
    maskBtn.className = 'btn';
    maskBtn.id = 'mask-btn';
    maskBtn.type = 'button';
    maskBtn.textContent = 'Mask';
    maskBtn.setAttribute('aria-pressed', 'false');
    controls.appendChild(maskBtn);
  }

  // Create mask-controls panel if missing
  let maskControls = document.getElementById('mask-controls');
  if (!maskControls && videoContainer) {
    maskControls = document.createElement('div');
    maskControls.id = 'mask-controls';
    // Fix 3: start hidden; enableBarsMask / disableBarsMask manage visibility
    maskControls.style.display = 'none';
    maskControls.style.position = 'absolute';
    maskControls.style.bottom = '80px';
    maskControls.style.left = '50%';
    maskControls.style.transform = 'translateX(-50%)';
    maskControls.style.zIndex = '600';
    maskControls.style.padding = '8px 12px';
    maskControls.style.background = 'rgba(0,0,0,0.56)';
    maskControls.style.borderRadius = '10px';
    maskControls.style.gap = '8px';
    videoContainer.appendChild(maskControls);
  }

  // Add input to mask-controls if missing
  if (maskControls) {
    if (!document.getElementById('mask-radius')) {
      const input = document.createElement('input');
      input.type = 'range';
      input.id = 'mask-radius';
      input.min = '0';
      input.max = '48';
      input.value = String(_barsMaskState.barPct ?? 5);
      input.style.width = '380px';
      input.style.maxWidth = '60vw';
      input.addEventListener('input', (e) => {
        _barsMaskState.barPct = Math.max(0, Math.min(48, Number(e.target.value) || 0));
        drawBarsMask();
        _saveSettings();
      });
      wireTouchFriendlyRangeInput(input);
      maskControls.appendChild(input);
    }
  }

  // Hook button events if not hooked
  maskBtn = document.getElementById('mask-btn');
  if (maskBtn && !_barsMaskHookedButtons.has(maskBtn)) {
    maskBtn.addEventListener('click', () => toggleMaskControls());
    _barsMaskHookedButtons.add(maskBtn);
  }
}

// Robust createBarsMaskCanvas() that forces siblings to be above the mask.
// Replace your previous version with this.
function createBarsMaskCanvas() {
  if (_barsMaskState.canvas) return;

  const parent = document.getElementById('video-container') || viewerElement?.parentElement;
  if (!parent) {
    console.warn('createBarsMaskCanvas: parent container not found');
    return;
  }

  // Ensure video is behind
  try {
    if (viewerElement && viewerElement.style) {
      viewerElement.style.setProperty('z-index', '0', 'important');
      // ensure it's positioned so z-index takes effect
      if (getComputedStyle(viewerElement).position === 'static') {
        viewerElement.style.position = 'absolute';
      }
    }
  } catch (e) { /* ignore */ }

  // Create canvas and set basic styles
  const canvas = document.createElement('canvas');
  canvas.id = 'mask-overlay';
  canvas.style.position = 'absolute';
  canvas.style.left = '0px';
  canvas.style.top = '0px';
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.style.pointerEvents = 'none'; // don't block clicks

  // Size pixel buffer to parent
  const rect = parent.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width));
  canvas.height = Math.max(1, Math.round(rect.height));

  // Ensure parent is positioned so absolute canvas aligns correctly
  if (getComputedStyle(parent).position === 'static') {
    parent.style.position = 'relative';
  }

  // Insert canvas before known UI elements so the canvas is underneath them visually
  const controlsEl = parent.querySelector('#controls') || parent.querySelector('.zoom-container') || parent.querySelector('#menu');
  if (controlsEl) {
    parent.insertBefore(canvas, controlsEl);
  } else {
    parent.insertBefore(canvas, parent.firstChild);
  }

  // Compute maximum z-index among sibling UI elements
  let maxZ = -Infinity;
  Array.from(parent.children).forEach((child) => {
    if (child === canvas) return;
    // ignore text nodes/comments (only elements)
    if (!(child instanceof HTMLElement)) return;
    const style = getComputedStyle(child);

    // If child is the video element, skip (we want video behind)
    if (child === viewerElement) return;

    // Some elements have 'auto' z-index (NaN), treat as 0
    const z = parseInt(style.zIndex, 10);
    const zVal = Number.isNaN(z) ? 0 : z;
    maxZ = Math.max(maxZ, zVal);
  });

  // Decide canvas z-index: use maxZ (if finite) or default 1
  let canvasZ;
  if (maxZ === -Infinity) canvasZ = 1;
  else canvasZ = Math.max(1, maxZ - 1);

  // Defensive: if maxZ is very small (0), place canvas at 1
  if (canvasZ < 1) canvasZ = 1;

  // Apply z-index with !important to override stylesheet rules
  canvas.style.setProperty('z-index', String(canvasZ), 'important');

  // Now ensure every sibling UI element (except the video) has z-index >= canvasZ+1
  const neededZ = canvasZ + 1;
  Array.from(parent.children).forEach((child) => {
    if (!(child instanceof HTMLElement)) return;
    if (child === canvas || child === viewerElement) return;

    // Ensure positioned so z-index applies
    const computed = getComputedStyle(child);
    if (computed.position === 'static') {
      child.style.setProperty('position', 'relative', 'important');
    }

    // Set z-index if it's less than neededZ or 'auto'
    const currentZ = parseInt(computed.zIndex, 10);
    const curr = Number.isNaN(currentZ) ? 0 : currentZ;
    if (curr < neededZ) {
      child.style.setProperty('z-index', String(neededZ), 'important');
    }
  });

  // Save to state
  _barsMaskState.canvas = canvas;
  _barsMaskState.ctx = canvas.getContext('2d');

  // Observe size changes on the parent so canvas can resize with layout changes
  _barsMaskState.resizeObserver = new ResizeObserver(() => {
    resizeBarsMaskCanvas();
    drawBarsMask();
  });
  _barsMaskState.resizeObserver.observe(parent);

  // Initial draw
  drawBarsMask();
}

function resizeBarsMaskCanvas() {
  if (!_barsMaskState.canvas) return;
  const parent = document.getElementById('video-container') || viewerElement?.parentElement;
  if (!parent) return;
  const rect = parent.getBoundingClientRect();
  // update canvas pixel buffer
  _barsMaskState.canvas.width = Math.max(1, Math.round(rect.width));
  _barsMaskState.canvas.height = Math.max(1, Math.round(rect.height));
  _barsMaskState.canvas.style.width = `${rect.width}px`;
  _barsMaskState.canvas.style.height = `${rect.height}px`;
}

function drawBarsMask() {
  if (!_barsMaskState.canvas || !_barsMaskState.ctx) return;

  const ctx = _barsMaskState.ctx;
  const w = _barsMaskState.canvas.width;
  const h = _barsMaskState.canvas.height;

  // K — skip drawing if the canvas has zero dimensions (avoids divide-by-zero)
  if (w <= 0 || h <= 0) return;

  const pct = Math.max(0, Math.min(50, Number(_barsMaskState.barPct) || 0));

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(0,0,0,1)';

  if (!_barsMaskState.inverted) {
    // NORMAL: mask edges
    if (_barsMaskState.orientation === 'horizontal') {
      const barH = Math.round((pct / 100) * h);
      if (barH > 0) {
        ctx.fillRect(0, 0, w, barH);           // top
        ctx.fillRect(0, h - barH, w, barH);   // bottom
      }
    } else {
      const barW = Math.round((pct / 100) * w);
      if (barW > 0) {
        ctx.fillRect(0, 0, barW, h);           // left
        ctx.fillRect(w - barW, 0, barW, h);    // right
      }
    }
  } else {
    // INVERTED: mask center
    if (_barsMaskState.orientation === 'horizontal') {
      const centerH = Math.round((pct * 2 / 100) * h);
      const y = Math.round((h - centerH) / 2);
      if (centerH > 0) ctx.fillRect(0, y, w, centerH);
    } else {
      const centerW = Math.round((pct * 2 / 100) * w);
      const x = Math.round((w - centerW) / 2);
      if (centerW > 0) ctx.fillRect(x, 0, centerW, h);
    }
  }
}

function enableBarsMask() {
  if (_barsMaskState.enabled) return;
  _ensureMaskUIExists();
  createBarsMaskCanvas();
  _barsMaskState.enabled = true;
  drawBarsMask();
  updateMaskOrientationButton();
  updateMaskInvertButton();
  _saveSettings();
}

function disableBarsMask() {
  if (!_barsMaskState.enabled) return;
  if (_barsMaskState.canvas && _barsMaskState.canvas.parentElement) {
    _barsMaskState.canvas.parentElement.removeChild(_barsMaskState.canvas);
  }
  if (_barsMaskState.resizeObserver) {
    _barsMaskState.resizeObserver.disconnect();
    _barsMaskState.resizeObserver = null;
  }
  _barsMaskState.canvas = null;
  _barsMaskState.ctx = null;
  _barsMaskState.enabled = false;
  hideMaskControls();
  _saveSettings();
}

function resetMaskSettings() {
  _barsMaskState.barPct = _DEFAULT_MASK_STATE.barPct;
  _barsMaskState.orientation = _DEFAULT_MASK_STATE.orientation;
  _barsMaskState.inverted = _DEFAULT_MASK_STATE.inverted;

  const radiusEl = document.getElementById('mask-radius');
  if (radiusEl) radiusEl.value = String(_barsMaskState.barPct);

  updateMaskOrientationButton();
  updateMaskInvertButton();
  disableBarsMask();
}

function resetTutorialViewerState() {
  applyNormal();
  hideFilterMenu();
  resetMaskSettings();
}

function updateMaskInvertButton() {
  const btn = document.getElementById('mask-invert-btn');
  if (!btn) return;
  btn.classList.toggle('active', _barsMaskState.inverted);
}

// Setup on DOM ready (safe to call multiple times)
function setupBarsMaskFeature() {
  try {
    _ensureMaskUIExists();
    // Sync slider attributes with current state (listener already wired by _ensureMaskUIExists).
    const radiusEl = document.getElementById('mask-radius');
    if (radiusEl) {
      radiusEl.min = '0';
      radiusEl.max = '48';
      radiusEl.value = String(_barsMaskState.barPct || 5);
    }
  } catch (err) {
    console.warn('setupBarsMaskFeature error', err);
  }
}

const invertBtn = document.getElementById('mask-invert-btn');
if (invertBtn) {
  invertBtn.addEventListener('click', () => {
    _barsMaskState.inverted = !_barsMaskState.inverted;
    updateMaskInvertButton();
    drawBarsMask();
    _saveSettings();
  });
}

// Wire the mask-radius slider for pages that already have it in the HTML.
// _ensureMaskUIExists() only attaches the listener when it creates the element
// dynamically; if the element exists in the HTML it is skipped, so we wire it
// here at module scope (script is deferred, so the DOM is ready).
const _maskRadiusEl = document.getElementById('mask-radius');
if (_maskRadiusEl) {
  wireTouchFriendlyRangeInput(_maskRadiusEl);
  _maskRadiusEl.addEventListener('input', (e) => {
    _barsMaskState.barPct = Math.max(0, Math.min(48, Number(e.target.value) || 0));
    drawBarsMask();
    _saveSettings();
  });
}

// initialize (call once)
document.addEventListener('DOMContentLoaded', () => {
  setupBarsMaskFeature();
  _restoreSettings();
  if (!document.querySelector('.filter-btn.active')) {
    _setActiveFilterBtn('normal');
  }
  wireTouchFriendlyRangeInput(document.getElementById('zoom-slider'));

  let overlay, box, textEl, highlight;
  let stepIndex = 0;
  let backBtn, nextBtn, skipBtn, finishBtn;
  const tutorialParams = new URLSearchParams(window.location.search);
  const shouldAutoStartTutorial =
    window.location.pathname === '/samples' && tutorialParams.get('tutorial') === '1';

  const steps = [
    {
      text: "Welcome! This tutorial will show you how to use the tools.",
      target: null
    },
    {
      text: "This is the camera view. Point it at something you want to see.",
      target: "#video-container"
    },
    {
      text: "Use these controls to zoom in and out.",
      target: ".zoom-control"
    },
    {
      text: "This is the Filters menu. It changes how colors look.",
      target: "#menu",
      before: () => showFilterMenu()
    },
    {
      // Fix 2: target changed from ".custom-slider-col" to null so renderStep does not
      // overwrite the multi-element highlight that before() sets via highlightMultiple.
      text: "These sliders adjust brightness and contrast.",
      target: null,
      before: () => {
        showFilterMenu();
        requestAnimationFrame(() => {
          highlightMultiple([".custom-slider-col"]);
        });
      }
    },
    {
      text: "This is the Mask button. It hides parts of the screen.",
      target: "#mask-btn",
      before: () => {
        if (typeof showMaskControls === "function") {
          showMaskControls();
        }
      } 
    },
    {
      text: "This slider controls how much is hidden.",
      target: "#mask-controls",
      before: () => {
        if (typeof showMaskControls === "function") {
          showMaskControls();
        }
      }
    },
    {
      text: "You're all set! You can explore anytime.",
      target: null
    }
  ];

  function createTutorial() {
    // overlay
    overlay = document.createElement("div");
    overlay.className = "tutorial-overlay";

    // box
    box = document.createElement("div");
    box.className = "tutorial-box";

    textEl = document.createElement("div");

    const btnRow = document.createElement("div");
    btnRow.className = "tutorial-buttons";

    backBtn = document.createElement("button");
    backBtn.className = "btn tutorial-back-btn";
    backBtn.textContent = "Back";

    nextBtn = document.createElement("button");
    nextBtn.className = "btn tutorial-next-btn";
    nextBtn.textContent = "Next";

    skipBtn = document.createElement("button");
    skipBtn.className = "btn tutorial-exit-btn";
    skipBtn.textContent = "Exit";

    finishBtn = document.createElement("button");
    finishBtn.className = "btn tutorial-finish-btn";
    finishBtn.textContent = "Finish";

    btnRow.append(backBtn, nextBtn, skipBtn, finishBtn);
    box.append(textEl, btnRow);
    overlay.append(box);
    document.body.append(overlay);

    // highlight
    highlight = document.createElement("div");
    highlight.className = "tutorial-highlight";
    highlight.style.display = "none";
    document.body.append(highlight);

    backBtn.addEventListener('click', () => {
      if (stepIndex > 0) stepIndex--;
      renderStep();
    });

    nextBtn.addEventListener('click', () => {
      if (stepIndex < steps.length - 1) {
        stepIndex++;
        renderStep();
      } else {
        endTutorial();
      }
    });

    skipBtn.addEventListener('click', endTutorial);
    finishBtn.addEventListener('click', endTutorial);

    renderStep();
  }

  function updateTutorialButtons() {
    if (!backBtn || !nextBtn || !skipBtn || !finishBtn) return;

    const isFirstStep = stepIndex === 0;
    const isLastStep = stepIndex === steps.length - 1;

    backBtn.classList.toggle('tutorial-hidden', isFirstStep);
    nextBtn.classList.toggle('tutorial-hidden', isLastStep);
    skipBtn.classList.toggle('tutorial-hidden', isLastStep);
    finishBtn.classList.toggle('tutorial-hidden', !isLastStep);
  }

  function highlightMultiple(selectors) {
    const highlight = document.querySelector(".tutorial-highlight");
    if (!highlight) return;

    const elements = selectors
      .map(sel => Array.from(document.querySelectorAll(sel)))
      .flat()
      .filter(el => el && el.getBoundingClientRect);

    if (elements.length === 0) {
      highlight.style.display = "none";
      return;
    }

    // Compute combined bounding box
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;

    elements.forEach(el => {
      const r = el.getBoundingClientRect();
      left = Math.min(left, r.left);
      top = Math.min(top, r.top);
      right = Math.max(right, r.right);
      bottom = Math.max(bottom, r.bottom);
    });

    highlight.style.display = "block";
    highlight.style.left = `${left - 12}px`;
    highlight.style.top = `${top - 12}px`;
    highlight.style.width = `${right - left + 24}px`;
    highlight.style.height = `${bottom - top + 24}px`;
  }

  function renderStep() {
    const step = steps[stepIndex];
    if (!step) return;
    textEl.textContent = step.text;
    updateTutorialButtons();

    if (typeof step.before === "function") {
      step.before();
    }

    if (!step.target) {
      highlight.style.display = "none";
      return;
    }

    requestAnimationFrame(() => {
      const el = document.querySelector(step.target);
      if (!el) {
        highlight.style.display = "none";
        return;
      }

      const r = el.getBoundingClientRect();
      highlight.style.display = "block";
      highlight.style.left = `${r.left - 12}px`;
      highlight.style.top = `${r.top - 12}px`;
      highlight.style.width = `${r.width + 24}px`;
      highlight.style.height = `${r.height + 24}px`;
    });
  }

  function endTutorial() {
    resetTutorialViewerState();
    overlay?.remove();
    highlight?.remove();
    overlay = box = textEl = highlight = null;
    backBtn = nextBtn = skipBtn = finishBtn = null;
    stepIndex = 0;
  }

  if (shouldAutoStartTutorial) {
    createTutorial();
    tutorialParams.delete('tutorial');
    const nextQuery = tutorialParams.toString();
    const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ''}${window.location.hash}`;
    window.history.replaceState({}, '', nextUrl);
  }
});

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  // Do not fire shortcuts when focus is inside a text input or slider
  const tag = (e.target?.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;

  switch (e.key) {
    case '+':
    case '=':
      e.preventDefault();
      changeZoom(0.1);
      break;
    case '-':
      e.preventDefault();
      changeZoom(-0.1);
      break;
    case '0':
      e.preventDefault();
      if (typeof window.resetZoom === 'function') window.resetZoom();
      break;
    case 'f':
    case 'F':
      e.preventDefault();
      if (typeof toggleFilterMenu === 'function') toggleFilterMenu();
      break;
    case 'm':
    case 'M':
      e.preventDefault();
      if (typeof toggleMaskControls === 'function') toggleMaskControls();
      break;
    case 'Escape':
      if (isFilterMenuOpen() || isMaskControlsOpen()) {
        e.preventDefault();
        closeAllPanels();
      }
      break;
  }
});

document.addEventListener('pointerdown', (e) => {
  if (isTutorialOpen()) return;

  const target = e.target;
  const filterButton = document.getElementById('filter-button');
  const maskButton = document.getElementById('mask-btn');
  const maskControls = document.getElementById('mask-controls');

  if (isFilterMenuOpen()) {
    const insideFilterMenu = !!menu?.contains(target);
    const onFilterButton = !!filterButton?.contains(target);
    if (!insideFilterMenu && !onFilterButton) {
      hideFilterMenu();
    }
  }

  if (isMaskControlsOpen()) {
    const insideMaskControls = !!maskControls?.contains(target);
    const onMaskButton = !!maskButton?.contains(target);
    if (!insideMaskControls && !onMaskButton) {
      hideMaskControls();
    }
  }
});
