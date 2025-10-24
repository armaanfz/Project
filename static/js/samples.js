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

// Access user's camera
if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
    }).then(function (stream) {
        videoElement.srcObject = stream;
    }).catch(function (error) {
        console.error('Error accessing the camera:', error);
    });
} else {
    console.error('getUserMedia is not supported in this browser');
}

// Example predefined filters
function applyNormal() {
    applyFilter('none');
}

function applyProtanopia() {
    applyFilter('grayscale(100%) sepia(100%) hue-rotate(270deg)');
}

function applyDeuteranopia() {
    applyFilter('grayscale(100%) sepia(100%) hue-rotate(90deg)');
}

function applyTritanopia() {
    applyFilter('grayscale(100%) sepia(100%) hue-rotate(180deg)');
}

function applyLightBlue() {
    applyFilter('brightness(150%) contrast(100%) sepia(20%) hue-rotate(180deg)');
}

function applyLightGreen() {
    applyFilter('brightness(130%) saturate(200%) hue-rotate(100deg)');
}

function applyLightPink() {
    applyFilter('brightness(120%) contrast(100%) sepia(30%) hue-rotate(330deg)');
}

function applyLightYellow() {
    applyFilter('brightness(140%) contrast(150%) hue-rotate(60deg)');
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

function applyYellowOnBlue() {
    applyFilter('invert(100%) sepia(100%) hue-rotate(180deg) saturate(300%) brightness(50%)');
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