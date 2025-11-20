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