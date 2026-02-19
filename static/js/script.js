const pageContent = {
    home: "",
    team: `
        <h2>Team</h2>
        <p class="section-subtitle">The people building this project together</p>

        <section>
            <h3>KARE Team</h3>
            <p><strong>Faculty:</strong> Dr. Abishek Tripathi</p>
            <p><strong>Student Team Members:</strong></p>
            <ul>
                <li>Gautham Sankar V</li>
                <li>Hariram S</li>
                <li>Mohammed Sulthan Ishaq</li>
                <li>Kothamasu Nikhil</li>
                <li>K V S S Ram Santosh Babu</li>
                <li>Setu Sai Ram Y</li>
                <li>B Vikram</li>
                <li>Sethu Madhavan R</li>
                <li>D Varsha</li>
            </ul>
        </section>

        <section>
            <h3>Purdue Team</h3>
            <p><strong>Faculty Advisors:</strong></p>
            <ul>
                <li>Dr. Willim Oakes</li>
                <li>Adam Renie</li>
                <li>Aiden Gonzalez</li>
                <li>Scott Malloy</li>
            </ul>
            <p><strong>Student Team:</strong></p>
            <ul>
                <li>Pooja Anil</li>
                <li>Drew Sheedy</li>
                <li>Thomas Sherman</li>
            </ul>
        </section>
    `,
    about: `
        <h2>About</h2>
        <p class="section-subtitle">Why this website exists</p>

        <section>
            <h3>Our Goal</h3>
            <p>We built this website to help students read small text more comfortably. The tools are designed to be simple, clear, and easy to use in class or at home.</p>
        </section>

        <section>
            <h3>What the Website Can Do</h3>
            <ul>
                <li>Make text bigger with zoom controls.</li>
                <li>Change colors to improve reading comfort.</li>
                <li>Use toggle screen to focus on the reading area.</li>
            </ul>
        </section>

        <section>
            <h3>Who It Helps</h3>
            <p>This website is made to support partially visually impaired students by giving them more control over how they view learning materials.</p>
        </section>
    `
};

let homeContentCache = "";

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

    infoBox.innerHTML = pageContent[infoType] || '<h2>Info</h2><p>No information available.</p>';
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
