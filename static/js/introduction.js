/**
 * Introduction page – lightweight helpers (e.g. accessibility, focus).
 * This page is primarily static content; add any intro-specific behavior here.
 */
document.addEventListener('DOMContentLoaded', () => {
    // Ensure main content is focusable for keyboard/screen reader users
    const main = document.querySelector('main.introduction');
    if (main && !main.hasAttribute('tabindex')) {
        main.setAttribute('tabindex', '-1');
    }
});
