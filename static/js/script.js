const pageContent = {
    home: `
        <h2>How to Use This Website</h2>
        <p class="section-subtitle">A quick and easy guide for students</p>

        <section>
            <h3>Welcome!</h3>
            <p>This website helps you read books and pages more clearly. Follow the steps below one at a time. There is no rush.</p>
        </section>

        <section>
            <h3>Step 1: Go to the Samples Page</h3>
            <ul>
                <li>Click the big <strong>Start Samples</strong> button to begin.</li>
                <li>You will go to the samples page where you can start using the tools.</li>
            </ul>
        </section>

        <section>
            <h3>Step 2: Place your page under the camera</h3>
            <ul>
                <li>Put your book or worksheet where the camera can see it.</li>
                <li>Make sure the text is not too dark or too blurry.</li>
            </ul>
        </section>

        <section>
            <h3>Step 3: Use the tools</h3>
            <ul>
                <li><strong>Zoom In / Zoom Out:</strong> Make letters bigger or smaller.</li>
                <li><strong>Color Filters:</strong> Try different color modes to find what feels best for your eyes.</li>
                <li><strong>Toggle Screen:</strong> Make the reading area bigger on your screen.</li>
            </ul>
        </section>

        <section>
            <h3>Step 4: Find your best view</h3>
            <ul>
                <li>Try one tool at a time.</li>
                <li>Keep the settings that make reading easiest for you.</li>
                <li>If something looks wrong, go back and adjust again.</li>
            </ul>
        </section>

        <section>
            <h3>Helpful Tips</h3>
            <ul>
                <li>Move slowly when changing settings.</li>
                <li>If you feel stuck, ask a teacher, parent, or helper.</li>
                <li>Take short breaks if your eyes feel tired.</li>
            </ul>
        </section>
    `,
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

function showInfo(infoType) {
    const infoBox = document.getElementById('info-box');
    infoBox.innerHTML = pageContent[infoType] || '<h2>Info</h2><p>No information available.</p>';
}

window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('a[data-tab]').forEach((tabLink) => {
        tabLink.addEventListener('click', (event) => {
            event.preventDefault();
            showInfo(tabLink.dataset.tab);
        });
    });

    const startButton = document.getElementById('start-samples-btn');
    if (startButton) {
        startButton.addEventListener('click', () => {
            window.location.href = startButton.dataset.samplesUrl;
        });
    }

    showInfo('home');
});
