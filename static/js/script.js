let tabContentCache = null;

function extractTabContent(sourceRoot) {
    const contentMap = {};
    sourceRoot.querySelectorAll("[data-tab-content]").forEach((element) => {
        const tabName = element.getAttribute("data-tab-content");
        if (tabName) {
            contentMap[tabName] = element.innerHTML;
        }
    });
    return contentMap;
}

async function loadTabContent() {
    if (tabContentCache) {
        return tabContentCache;
    }

    const embeddedSource = document.getElementById("tab-content-source");
    if (embeddedSource) {
        const embeddedContent = extractTabContent(embeddedSource);
        if (Object.keys(embeddedContent).length > 0) {
            tabContentCache = embeddedContent;
            return tabContentCache;
        }
    }

    const response = await fetch('/home-tab-content', { cache: "no-store" });
    if (!response.ok) {
        throw new Error(`Failed to load tab content: ${response.status}`);
    }

    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const contentMap = extractTabContent(doc);
    if (Object.keys(contentMap).length === 0) {
        throw new Error("No tab content found in home-tab-content template.");
    }

    tabContentCache = contentMap;
    return tabContentCache;
}

async function showInfo(infoType) {
    const infoBox = document.getElementById('info-box');
    try {
        const tabContent = await loadTabContent();
        infoBox.innerHTML = tabContent[infoType] || '<h2>Info</h2><p>No information available.</p>';
    } catch (error) {
        console.error(error);
        infoBox.innerHTML = '<h2>Info</h2><p>Unable to load this section.</p><button type="button" class="retry-btn" id="tab-retry-btn">Try again</button>';
        document.getElementById('tab-retry-btn')?.addEventListener('click', () => showInfo(infoType));
    }
    setActiveTab(infoType);
}

function setActiveTab(activeTab) {
    document.querySelectorAll('a[data-tab]').forEach((link) => {
        const isActive = link.dataset.tab === activeTab;
        if (isActive) {
            link.setAttribute('aria-current', 'page');
        } else {
            link.removeAttribute('aria-current');
        }
        link.classList.toggle('nav-active', isActive);
    });
}

window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('a[data-tab]').forEach((tabLink) => {
        tabLink.addEventListener('click', async (event) => {
            event.preventDefault();
            await showInfo(tabLink.dataset.tab);
        });
    });
    setActiveTab('home');

    const startButton = document.getElementById('start-samples-btn');
    if (startButton) {
        startButton.addEventListener('click', () => {
            window.location.href = startButton.dataset.samplesUrl;
        });
    }

    const remoteButton = document.getElementById('start-remote-btn');
    if (remoteButton) {
        remoteButton.addEventListener('click', () => {
            window.location.href = remoteButton.dataset.remoteUrl;
        });
    }

    void showInfo('home');
});
