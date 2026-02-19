const pageContent = {};

let homeContentCache = "";
let tabContentCache = null;

async function loadHomeContent() {
    if (homeContentCache) {
        return homeContentCache;
    }

    const response = await fetch(`/introduction?_=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) {
        throw new Error(`Failed to load introduction content: ${response.status}`);
    }

    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const title = doc.querySelector("header.container h1")?.textContent?.trim() || "";
    const subtitle = doc.querySelector("header.container .subtitle")?.textContent?.trim() || "";
    const introBody = doc.querySelector("main.introduction")?.innerHTML || "";

    if (!introBody) {
        throw new Error("Introduction content not found in response.");
    }

    homeContentCache = `
        ${title ? `<h2>${title}</h2>` : ""}
        ${subtitle ? `<p class="section-subtitle">${subtitle}</p>` : ""}
        ${introBody}
    `;
    return homeContentCache;
}

async function loadTabContent() {
    if (tabContentCache) {
        return tabContentCache;
    }

    const response = await fetch(`/home-tab-content?_=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) {
        throw new Error(`Failed to load tab content: ${response.status}`);
    }

    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const contentMap = {};
    doc.querySelectorAll("[data-tab-content]").forEach((element) => {
        const tabName = element.getAttribute("data-tab-content");
        if (tabName) {
            contentMap[tabName] = element.innerHTML;
        }
    });

    tabContentCache = contentMap;
    return tabContentCache;
}

async function showInfo(infoType) {
    const infoBox = document.getElementById('info-box');

    if (infoType === "home") {
        try {
            infoBox.innerHTML = await loadHomeContent();
        } catch (error) {
            console.error(error);
            infoBox.innerHTML = "<h2>Home</h2><p>Unable to load introduction content.</p>";
        }
        return;
    }

    try {
        const tabContent = await loadTabContent();
        infoBox.innerHTML = tabContent[infoType] || pageContent[infoType] || '<h2>Info</h2><p>No information available.</p>';
    } catch (error) {
        console.error(error);
        infoBox.innerHTML = '<h2>Info</h2><p>Unable to load this section.</p>';
    }
}

window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('a[data-tab]').forEach((tabLink) => {
        tabLink.addEventListener('click', async (event) => {
            event.preventDefault();
            await showInfo(tabLink.dataset.tab);
        });
    });

    const startButton = document.getElementById('start-samples-btn');
    if (startButton) {
        startButton.addEventListener('click', () => {
            window.location.href = startButton.dataset.samplesUrl;
        });
    }

    void showInfo('home');
});
