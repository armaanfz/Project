/* On-demand OCR and Piper audio. Browser speech synthesis is never used. */
(() => {
    'use strict';
    const byId = id => document.getElementById(id);
    const dialog = byId('reader-dialog');
    const trigger = byId('read-text-btn');
    if (!dialog || !trigger) return;
    const status = byId('reader-status');
    const text = byId('reader-text');
    const preview = byId('reader-preview');
    const notice = byId('reader-notice');
    const speak = byId('reader-speak');
    const pause = byId('reader-pause');
    const stop = byId('reader-stop');
    const audio = new Audio();
    audio.preload = 'auto';
    audio.preservesPitch = true;
    const preferenceKey = 'magnifier_reader_settings';
    const colors = ['dark', 'light', 'yellow', 'blue'];
    const speeds = [0.75, 1, 1.25, 1.5];
    let preferences = { fontSize: 32, colors: 'dark', speed: 1 };
    try {
        const saved = JSON.parse(localStorage.getItem(preferenceKey));
        if (saved && typeof saved === 'object') {
            if (Number.isFinite(saved.fontSize)) preferences.fontSize = Math.max(24, Math.min(96, saved.fontSize));
            if (colors.includes(saved.colors)) preferences.colors = saved.colors;
            if (speeds.includes(saved.speed)) preferences.speed = saved.speed;
        }
    } catch (_) { /* Preferences are optional. */ }

    let operation = 0;
    let activeJob = null;
    let controller = null;
    let previewURL = null;
    let audioURL = null;
    let speechAvailable = false;

    function applyPreferences() {
        text.style.fontSize = `${preferences.fontSize}px`;
        text.dataset.colors = preferences.colors;
        byId('reader-size-label').textContent = `${preferences.fontSize} px`;
        byId('reader-smaller').disabled = preferences.fontSize <= 24;
        byId('reader-larger').disabled = preferences.fontSize >= 96;
        byId('reader-colors').value = preferences.colors;
        byId('reader-speed').value = String(preferences.speed);
        audio.playbackRate = preferences.speed;
        try { localStorage.setItem(preferenceKey, JSON.stringify(preferences)); } catch (_) { /* optional */ }
    }
    applyPreferences();

    function message(value) { status.textContent = value; }
    function current(token) { return token === operation && dialog.open; }
    function cancelled() { return new DOMException('Cancelled', 'AbortError'); }

    function discardJob(id) {
        if (!id) return;
        void fetch(`/api/reader/jobs/${encodeURIComponent(id)}`, {
            method: 'DELETE', headers: { 'X-Magnifier-Reader': '1' }, keepalive: true,
        }).catch(() => {});
    }

    function cancelOperation() {
        operation += 1;
        controller?.abort();
        controller = null;
        discardJob(activeJob);
        activeJob = null;
    }

    function clearAudio() {
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
        if (audioURL) URL.revokeObjectURL(audioURL);
        audioURL = null;
    }

    function clearPreview() {
        preview.hidden = true;
        preview.removeAttribute('src');
        if (previewURL) URL.revokeObjectURL(previewURL);
        previewURL = null;
    }

    function idleSpeech() {
        speak.hidden = false;
        speak.disabled = !speechAvailable || !text.textContent;
        speak.textContent = 'Read Aloud';
        pause.hidden = true;
        pause.textContent = 'Pause';
        stop.hidden = true;
    }

    async function responseJSON(response) {
        let value;
        try { value = await response.json(); }
        catch (_) { throw new Error('The reader could not connect. Please try again.'); }
        if (!response.ok) throw new Error(value.error || 'The reader could not finish. Please try again.');
        return value;
    }

    async function runJob(path, options, token, withAudio = false) {
        // Keep the short submission alive on Cancel so a late job ID can still
        // be deleted. Only polling/audio downloads use the operation controller.
        const submitted = await responseJSON(await fetch(path, {
            ...options, headers: { ...options.headers, 'X-Magnifier-Reader': '1' },
            signal: AbortSignal.timeout(15000),
        }));
        const id = submitted.id;
        if (!current(token)) { discardJob(id); throw cancelled(); }
        activeJob = id;
        const localController = new AbortController();
        controller = localController;
        const deadline = Date.now() + 135000;
        try {
            while (current(token)) {
                if (Date.now() > deadline) throw new Error('Reading took too long. Try scanning a smaller area.');
                const job = await responseJSON(await fetch(`/api/reader/jobs/${encodeURIComponent(id)}`, {
                    signal: AbortSignal.any([localController.signal, AbortSignal.timeout(15000)]),
                }));
                if (!current(token)) throw cancelled();
                if (job.state === 'error') throw new Error(job.error);
                if (job.state === 'done') {
                    if (!withAudio) return job.result;
                    const response = await fetch(`/api/reader/jobs/${encodeURIComponent(id)}/audio`, {
                        signal: AbortSignal.any([localController.signal, AbortSignal.timeout(30000)]),
                    });
                    if (!response.ok) await responseJSON(response);
                    const blob = await response.blob();
                    if (!current(token)) throw cancelled();
                    return blob;
                }
                await new Promise(resolve => setTimeout(resolve, 300));
            }
            throw cancelled();
        } finally {
            discardJob(id);
            if (activeJob === id) activeJob = null;
            if (controller === localController) controller = null;
        }
    }

    async function openReader() {
        if (dialog.open || document.querySelector('.tutorial-overlay')) return;
        cancelOperation();
        const token = operation;
        clearAudio();
        clearPreview();
        text.textContent = '';
        text.hidden = true;
        notice.hidden = true;
        byId('reader-settings').hidden = true;
        byId('reader-actions').hidden = true;
        byId('reader-close').textContent = 'Cancel';
        if (typeof closeAllPanels === 'function') closeAllPanels();
        dialog.showModal();
        trigger.setAttribute('aria-expanded', 'true');
        message('Recognizing text…');
        byId('reader-body').scrollTop = 0;
        const captureController = new AbortController();
        controller = captureController;
        try {
            const [blob, capabilities] = await Promise.all([
                window.captureReaderImage({ signal: captureController.signal }),
                fetch('/api/reader/status', {
                    signal: AbortSignal.any([captureController.signal, AbortSignal.timeout(10000)]),
                }).then(responseJSON),
            ]);
            if (!current(token)) return;
            speechAvailable = capabilities.speech;
            if (!capabilities.ocr) throw new Error("Text recognition is unavailable. The magnifier's installation needs updating.");
            previewURL = URL.createObjectURL(blob);
            preview.src = previewURL;
            preview.hidden = false;
            const form = new FormData();
            form.append('image', blob, 'page.png');
            const result = await runJob('/api/ocr', { method: 'POST', body: form }, token);
            if (!current(token)) return;
            clearPreview();
            byId('reader-close').textContent = 'Back to Camera';
            byId('reader-actions').hidden = false;
            if (!result.text?.trim()) {
                message('No readable text found. Try moving the page closer or improving the lighting.');
                idleSpeech();
                return;
            }
            text.textContent = result.text;
            text.hidden = false;
            byId('reader-settings').hidden = false;
            const notes = [];
            if (result.truncated) notes.push('This scan is too long to show in full. Scan a smaller area.');
            else if (result.uncertain) notes.push('Some words may be incorrect. Check them against the page.');
            if (!speechAvailable) notes.push('Read Aloud is not available on this device yet.');
            notice.textContent = notes.join(' ');
            notice.hidden = !notes.length;
            message('Text ready.');
            idleSpeech();
            text.focus();
        } catch (error) {
            if (!current(token) || error.name === 'AbortError') return;
            clearPreview();
            message(error.name === 'TimeoutError' ? 'The reader could not connect. Please try again.' : error.message);
            byId('reader-close').textContent = 'Back to Camera';
            byId('reader-actions').hidden = false;
            idleSpeech();
        } finally {
            captureController.abort();
            if (controller === captureController) controller = null;
        }
    }

    async function playAudio(token) {
        try {
            await audio.play();
            if (!current(token)) return;
            speak.hidden = true;
            pause.hidden = false;
            pause.textContent = 'Pause';
            stop.hidden = false;
            message('Reading aloud.');
        } catch (error) {
            if (!current(token)) return;
            idleSpeech();
            if (error.name === 'NotAllowedError') {
                speak.textContent = 'Play';
                message('Audio is ready. Tap Play to listen.');
            } else {
                clearAudio();
                message('Could not play the audio. Tap Read Aloud to try again.');
            }
        }
    }

    async function readAloud() {
        if (!speechAvailable || !text.textContent) return;
        cancelOperation();
        const token = operation;
        if (audioURL) { await playAudio(token); return; }
        speak.disabled = true;
        speak.textContent = 'Preparing voice…';
        stop.hidden = false;
        message('Preparing the reading…');
        try {
            const blob = await runJob('/api/reader/speech', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text.textContent }),
            }, token, true);
            if (!current(token)) return;
            audioURL = URL.createObjectURL(blob);
            audio.src = audioURL;
            audio.playbackRate = preferences.speed;
            await playAudio(token);
        } catch (error) {
            if (!current(token) || error.name === 'AbortError') return;
            idleSpeech();
            message(error.name === 'TimeoutError' ? 'The voice could not connect. Please try again.' : error.message);
        }
    }

    function stopReading() {
        cancelOperation();
        audio.pause();
        if (audioURL) audio.currentTime = 0;
        idleSpeech();
        message('Reading stopped.');
        speak.focus();
    }

    function cleanup() {
        cancelOperation();
        clearAudio();
        clearPreview();
        text.textContent = '';
        trigger.setAttribute('aria-expanded', 'false');
    }

    function closeReader() { if (dialog.open) dialog.close(); }
    dialog.addEventListener('close', () => { cleanup(); trigger.focus(); });
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeReader(); });
    window.addEventListener('pagehide', () => { closeReader(); cleanup(); });
    trigger.addEventListener('click', openReader);
    byId('reader-close').addEventListener('click', closeReader);
    byId('reader-rescan').addEventListener('click', closeReader);
    speak.addEventListener('click', readAloud);
    stop.addEventListener('click', stopReading);
    pause.addEventListener('click', async () => {
        if (audio.paused) await playAudio(operation);
        else { audio.pause(); pause.textContent = 'Resume'; message('Reading paused.'); }
    });
    audio.addEventListener('ended', () => {
        if (!dialog.open) return;
        audio.currentTime = 0;
        idleSpeech();
        message('Finished reading.');
        speak.focus();
    });
    byId('reader-smaller').addEventListener('click', () => { preferences.fontSize = Math.max(24, preferences.fontSize - 4); applyPreferences(); });
    byId('reader-larger').addEventListener('click', () => { preferences.fontSize = Math.min(96, preferences.fontSize + 4); applyPreferences(); });
    byId('reader-colors').addEventListener('change', event => { preferences.colors = event.target.value; applyPreferences(); });
    byId('reader-speed').addEventListener('change', event => { preferences.speed = Number(event.target.value); applyPreferences(); });
})();
