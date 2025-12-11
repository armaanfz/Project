const videoElement = document.getElementById('video');
const videoContainer = document.getElementById('video-container');
const menu = document.getElementById('menu');
const zoomSlider = document.getElementById('zoom-slider');

let scale = 1; // scale
let translateX = 0; // X-axis translation
let translateY = 0; // Y-axis translation

// Default values for custom filters
const customFilters = {
    hue: 0,
    brightness: 100,
    contrast: 100,
    saturation: 100,
};

// Default filter (none)
let currentFilter = 'none';

let isDragging = false; // Track dragging state
let startX = 0; // Initial X position on drag start
let startY = 0; // Initial Y position on drag start

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
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    videoEl.srcObject = stream;
    videoEl.autoplay = true;
    videoEl.playsInline = true;
    videoEl.muted = true; // recommended for autoplay

    // Wait for metadata so video.videoWidth/video.videoHeight are available
    await new Promise((resolve) => {
      if (videoEl.readyState >= 1 && videoEl.videoWidth && videoEl.videoHeight) {
        return resolve();
      }
      function onMeta() {
        videoEl.removeEventListener('loadedmetadata', onMeta);
        resolve();
      }
      videoEl.addEventListener('loadedmetadata', onMeta);
    });

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

/* Optional: auto-start camera when DOM is ready. If you start camera manually elsewhere, remove this block. */
document.addEventListener('DOMContentLoaded', async () => {
  try {
    const vid = document.getElementById('video');
    if (!vid) return;
    // Change preferExact1080 to true if you want the getUserMedia call to fail when 1080p not available.
    await startCamera(vid, { preferExact1080: false });

    // Example: if you already have overlay canvas(s), align them to the negotiated size:
    const overlay = document.getElementById('overlay-canvas') || document.getElementById('tritanopia-overlay-canvas');
    if (overlay instanceof HTMLCanvasElement) {
      // If you want full native processing, use scale = 1.0
      setCanvasToVideoSize(overlay, vid, 1.0);
    }
  } catch (e) {
    console.warn('Camera auto-start failed or was denied:', e);
  }
});
/* ---------- end camera / 1080p helpers ---------- */


// Add event listeners to enable drag panning
videoContainer.addEventListener('mousedown', (e) => {
    isDragging = true;
    startX = e.clientX; // Record the starting X position
    startY = e.clientY; // Record the starting Y position
    videoContainer.style.cursor = 'grabbing';
});

videoContainer.addEventListener('mousemove', (e) => {
    if (isDragging) {
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;

        translateX += dx;
        translateY += dy;

        applyTransform(); // Apply transformations with constraints

        startX = e.clientX;
        startY = e.clientY;
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
    isDragging = true;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
});

videoContainer.addEventListener('touchmove', (e) => {
    if (isDragging) {
        const dx = e.touches[0].clientX - startX;
        const dy = e.touches[0].clientY - startY;

        translateX += dx;
        translateY += dy;

        applyTransform();

        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
    }
});

videoContainer.addEventListener('touchend', () => {
    isDragging = false;
});

// Constrain movement within bounds
function constrainMovement() {
    const containerWidth = videoContainer.offsetWidth;
    const containerHeight = videoContainer.offsetHeight;
    const videoWidth = videoElement.offsetWidth * scale;
    const videoHeight = videoElement.offsetHeight * scale;

    // Determine the max translations to keep the video within bounds
    const maxTranslateX = (videoWidth - containerWidth) / 2;
    const maxTranslateY = (videoHeight - containerHeight) / 2;

    // Constrain translateX and translateY within the calculated boundaries
    translateX = Math.max(-maxTranslateX, Math.min(maxTranslateX, translateX));
    translateY = Math.max(-maxTranslateY, Math.min(maxTranslateY, translateY));
}

// Apply transformations (zoom and pan)
function applyTransform() {
    constrainMovement(); // Ensure panning stays within bounds
    videoElement.style.transform = `translate(-50%, -50%) translate(${translateX}px, ${translateY}px) scale(${scale})`;
}

//Zoom using the vertical slider
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
}

// Change zoom via + / - buttons by delta (e.g., 0.1)
function changeZoom(delta) {
    const zoomSlider = document.getElementById('zoom-slider');
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
}

// Combine Predefined and Adjustable Custom Filters
function applyCombinedFilters() {
    const predefinedFilter = currentFilter !== 'none' ? currentFilter : '';
    const adjustableFilter = `hue-rotate(${customFilters.hue}deg) brightness(${customFilters.brightness}%) contrast(${customFilters.contrast}%) saturate(${customFilters.saturation}%)`;

    videoElement.style.filter = `${predefinedFilter} ${adjustableFilter}`.trim();
}

// Adjustable Custom Filters
function applyCustomFilter() {
    customFilters.hue = document.getElementById('hue').value;
    customFilters.brightness = document.getElementById('brightness').value;
    customFilters.contrast = document.getElementById('contrast').value;
    customFilters.saturation = document.getElementById('saturation').value;
    applyCombinedFilters();
}

// Predefined Filters
function applyFilter(filter) {
    currentFilter = filter;
    applyCombinedFilters();
}

(async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.error('getUserMedia is not supported in this browser');
        return;
    }

    try {
        // startCamera will set videoElement.srcObject and wait for loadedmetadata
        const stream = await startCamera(videoElement, { preferExact1080: false });

        // Optional: after camera starts, align any overlay / processing canvases to the native video pixels
        // If you use different canvas ids, add them here or call setCanvasToVideoSize wherever you create canvases.
        const overlayIds = ['overlay-canvas', 'tritanopia-overlay-canvas'];
        overlayIds.forEach(id => {
            const c = document.getElementById(id);
            if (c instanceof HTMLCanvasElement) setCanvasToVideoSize(c, videoElement, 1.0);
        });

        // Log final negotiated resolution
        console.log('Camera stream active. Negotiated resolution (videoElement):', videoElement.videoWidth, 'x', videoElement.videoHeight);

        // If you need to switch to environment-facing camera specifically, you can select a deviceId from enumerateDevices
        // and pass deviceId: { exact: '...'} to startCamera by adding support for deviceId in startCamera constraints.
    } catch (err) {
        console.error('Camera startup failed:', err);
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

// Toggle the filter menu
function toggleMenu() {
    if (document.fullscreenElement) {
        menu.style.position = 'absolute';
        menu.style.top = '10px';
        menu.style.right = '10px';
    } else {
        menu.style.position = 'fixed';
        menu.style.top = '0';
        menu.style.right = '0';
    }
    menu.classList.toggle('active');
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
    }

    // Hook into existing slider behaviour
    slider.addEventListener('input', updateResetButtonVisibility);
    slider.addEventListener('change', updateResetButtonVisibility);

    // Actual Reset Zoom function
    window.resetZoom = function () {
        // Reset numeric state
        scale = 1;
        translateX = 0;
        translateY = 0;
        // Reset slider UI
        slider.value = '1';
        // Re-apply transform so video recenters and zoom resets
        applyTransform();
        // Hide the button again
        resetBtn.style.display = 'none';
    };

    // Initialize button state on page load
    updateResetButtonVisibility();
});

// Back button function
function goHome() {
    window.location.href = "/";
}
/* ---------- Robust letterbox mask (top + bottom bars) feature ----------
   Drop this whole block into samples.js after videoElement / video-container are defined.
   It will create missing UI if needed and ensures the mask canvas is inserted under UI.
--------------------------------------------------------------------- */

const _barsMaskState = {
  enabled: false,
  canvas: null,
  ctx: null,
  barHeight: 100,    // default px
  resizeObserver: null
};

function _ensureMaskUIExists() {
  // Ensure #controls exists
  let controls = document.getElementById('controls');
  const videoContainer = document.getElementById('video-container') || videoElement.parentElement;

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
    maskControls.style.display = 'flex';
    videoContainer.appendChild(maskControls);
  }

  // Add label + input to mask-controls if missing
  if (maskControls) {
    if (!document.getElementById('mask-radius-label')) {
      const label = document.createElement('label');
      label.id = 'mask-radius-label';
      label.htmlFor = 'mask-radius';
      label.style.color = '#fff';
      label.style.marginRight = '8px';
      label.textContent = 'Bar height (px)';
      maskControls.appendChild(label);
    }
    if (!document.getElementById('mask-radius')) {
      const input = document.createElement('input');
      input.type = 'range';
      input.id = 'mask-radius';
      input.min = '0';
      input.max = '500';
      input.value = String(_barsMaskState.barHeight);
      input.style.width = '280px';
      input.addEventListener('input', (e) => {
        _barsMaskState.barHeight = Math.round(Number(e.target.value) || 0);
        drawBarsMask();
      });
      maskControls.appendChild(input);
    }
  }

  // Hook button events if not hooked
  maskBtn = document.getElementById('mask-btn');
  if (maskBtn && !maskBtn._barsMaskHooked) {
    maskBtn.addEventListener('click', () => toggleBarsMask());
    maskBtn._barsMaskHooked = true;
  }
}

// Robust createBarsMaskCanvas() that forces siblings to be above the mask.
// Replace your previous version with this.
function createBarsMaskCanvas() {
  if (_barsMaskState.canvas) return;

  const parent = document.getElementById('video-container') || videoElement.parentElement;
  if (!parent) {
    console.warn('createBarsMaskCanvas: parent container not found');
    return;
  }

  // Ensure video is behind
  try {
    if (videoElement && videoElement.style) {
      videoElement.style.setProperty('z-index', '0', 'important');
      // ensure it's positioned so z-index takes effect
      if (getComputedStyle(videoElement).position === 'static') {
        videoElement.style.position = 'absolute';
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
    if (child === videoElement) return;

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
    if (child === canvas || child === videoElement) return;

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
  const parent = document.getElementById('video-container') || videoElement.parentElement;
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

  // _barsMaskState.barPct is percent (0..50). If code still uses barHeight (px), keep backward compat:
  let pct = (typeof _barsMaskState.barPct === 'number') ? _barsMaskState.barPct : null;
  if (pct === null) {
    // backward compatibility: if barHeight exists, convert to percent relative to current height
    const bh = Number(_barsMaskState.barHeight) || 0;
    pct = Math.round((bh / Math.max(1, h)) * 100);
    // clamp
    pct = Math.max(0, Math.min(50, pct));
    _barsMaskState.barPct = pct;
  }

  // Compute pixel bar height from percentage
  const barH = Math.round((pct / 100) * h);

  // Clear
  ctx.clearRect(0,0,w,h);

  // Draw top bar (solid black)
  if (barH > 0) {
    ctx.fillStyle = 'rgba(0,0,0,1)';
    ctx.fillRect(0, 0, w, barH);

    // Draw bottom bar
    ctx.fillRect(0, h - barH, w, barH);

    // subtle divider lines
    ctx.fillStyle = 'rgba(255,255,255,0.03)';
    ctx.fillRect(0, barH - 1, w, 1); // top divider
    ctx.fillRect(0, h - barH, w, 1); // bottom divider
  }
}

function enableBarsMask() {
  if (_barsMaskState.enabled) return;
  _ensureMaskUIExists();
  createBarsMaskCanvas();
  _barsMaskState.enabled = true;
  const controls = document.getElementById('mask-controls');
  if (controls) controls.style.display = 'flex';
  const btn = document.getElementById('mask-btn');
  if (btn) btn.classList.add('active'), btn.setAttribute('aria-pressed','true');
  drawBarsMask();
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
  const controls = document.getElementById('mask-controls');
  if (controls) controls.style.display = 'none';
  const btn = document.getElementById('mask-btn');
  if (btn) btn.classList.remove('active'), btn.setAttribute('aria-pressed','false');
}

function toggleBarsMask() {
  if (_barsMaskState.enabled) disableBarsMask(); else enableBarsMask();
}

// Setup on DOM ready (safe to call multiple times)
function setupBarsMaskFeature() {
  try {
    _ensureMaskUIExists();
    // ensure slider event already wired by _ensureMaskUIExists, but double-check:
    const radiusEl = document.getElementById('mask-radius');
    if (radiusEl) {
      // ensure slider min/max are 0..50 (percent)
      radiusEl.min = '0';
      radiusEl.max = '50';
      // default value (percent)
      if (!radiusEl.value) radiusEl.value = String(_barsMaskState.barPct || 10);

      // on input: store percentage and redraw
      radiusEl.addEventListener('input', (e) => {
        const pct = Math.max(0, Math.min(50, Number(e.target.value) || 0));
        _barsMaskState.barPct = pct;
        // keep legacy numeric barHeight if other code reads it
        _barsMaskState.barHeight = Math.round((pct / 100) * (_barsMaskState.canvas ? _barsMaskState.canvas.height : (videoElement ? videoElement.clientHeight : 0)));
        drawBarsMask();
      });
    }
  } catch (err) {
    console.warn('setupBarsMaskFeature error', err);
  }
}

// initialize (call once)
document.addEventListener('DOMContentLoaded', () => {
  setupBarsMaskFeature();
});
/* ---------- end letterbox mask block ---------- */