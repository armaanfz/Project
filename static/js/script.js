function showInfo(infoType) {
    var infoBox = document.getElementById("info-box");
    infoBox.style.display = "block";

    switch (infoType) {
        case 'home':
            infoBox.innerHTML = `<h1>Home</h1> 
                <div class="home-container"> 
                    <p>Welcome to our innovative project website, where cutting-edge technology meets user-friendly design to provide an exceptional adjustable webcam experience. Our platform allows users to effortlessly control their webcam's zoom level and apply various visual filters, enhancing both professional and personal video interactions. Whether you're attending virtual meetings, participating in online classes, or connecting with loved ones, our intuitive interface ensures that you can customize your video settings to suit any scenario.</p>
                    <p>Our project is dedicated to making webcam usage more versatile and accessible for everyone. We prioritize user convenience and visual clarity, offering a seamless integration of advanced features without compromising on simplicity. Explore our website to discover how our adjustable webcam access and zoom capabilities can transform your digital communication, providing you with the tools to stay connected in a way that best fits your needs.</p>
                </div>`;
            break;
        case 'team':
            infoBox.innerHTML = `<h1>Team</h1>
                <div class="team-container">
                    <div class="team-column">
                        <p>KARE TEAM</p>
                        <p>Faculty: DR. ABISHEK TRIPATHI</p>
                        <p>Student Team Members:</p>
                        <ul>
                            <li>GAUTHAM SANKAR V</li>
                            <li>HARIRAM S</li>
                            <li>MOHAMMED SULTHAN ISHAQ</li>
                            <li>KOTHAMASU NIKHIL</li>
                            <li>K V S S RAM SANTOSH BABU</li>
                            <li>SETU SAI RAM Y</li>
                            <li>B VIKRAM</li>
                            <li>SETHU MADHAVAN R</li>
                            <li>D VARSHA</li>
                        </ul>
                    </div>
                    <div class="team-column">
                        <p>PURDUE TEAM</p>
                        <p>Faculty Advisors</p>
                        <ul>
                            <li>Dr. Willim Oakes (Advisor)</li>
                            <li>Adam Renie (Advisor)</li>
                            <li>Aiden Gonzalez (Advisor)</li>
                            <li>Scott Malloy (Project Manager)</li>
                        </ul>
                        <p>Student Team</p>
                        <ul>
                            <li>Pooja Anil (Project Manager)</li>
                            <li>Drew Sheedy (Team member)</li>
                            <li>Thomas Sherman (Team member)</li>
                        </ul>
                    </div>
                </div>`;
            break;
        case 'collaboration':
            infoBox.innerHTML = `<h1>Collaboration</h1>
                <div class="collaboration-container"> 
                    <p>This project is a collaborative effort between Purdue University and Kalasalingam University, working together to achieve the goal of creating an app or website that helps partially impaired people to read books by using some features given in the app or website.</p>
                    <p>The software that has been created by the KARE students should take the input of live streaming video of the book that the students want to read using the camera (Intel D415) that has been connected to Raspberry Pi and that input should be transferred to the software through Bluetooth or WiFi. The software contains features to apply color filters, zoom in and zoom out for the input video that can be helpful to the students to convert the video as they need using different filters and can view the image closer using the zoom option. The icons of all these features will be larger in size so that they can easily find their requirements, and also we added an option named toggle screen that can help them to maximize the video.</p>
                </div>`;
            break;
        case 'about':
            infoBox.innerHTML = `<h1>About the Project</h1>
                <div class="about-container">
                    <p>Our project is about bringing a change to the way users interact with their webcams so that they can take this experience to an uncharted level, where they have control over everything that is possible. With advanced zoom functionalities and a range of visual filters, we help the user create their own video experience based on preferences and needs. From tweaking the clarity of professional meetings, optimizing visual settings for online classes, and even making video calls with friends and family more personalized, our solution ensures that webcam settings can be easily adjusted.</p>
                    <p>The initiative was born out of a desire to bridge the gap between technology and accessibility. We understand how much video communication is becoming key in the lives of people today, and we do our best to create an instrument that will serve both technology geeks and very ordinary people who are not so accustomed to digital devices. We are continuing to make research and development work to deliver a product that will match expectations concerning performance, usability, and adaptability. We want to ensure that we offer inclusivity and benefits to everyone by having such features as color blindness filters and easy zoom adjustments. At the core of our project is the commitment to innovation and meeting users' needs, and thus we are always striving to adapt the technology to new advances in the field that emerge with user feedback. We want to make high-quality video communication accessible to everyone and create a new standard for webcam functionality. Explore our project, see how we shape the future of digital interaction, and join in embracing a more connected, visually enriched world.</p>
                </div>`;
            break;
        case 'media':
            infoBox.innerHTML = `<h1>Media</h1>
                <div class="media-container">
                    <img src="https://online.kalasalingam.ac.in/images/0-master/logo-kare.webp" width="500" height="100">
                    <img src="https://th.bing.com/th/id/OIP.F__7_XNzjZMzktrHD7YTuAAAAA?rs=1&pid=ImgDetMain" width="500" height="100">
                    <img src="https://media.licdn.com/dms/image/D4E22AQGzjhxatcexzQ/feedshare-shrink_2048_1536/0/1706637205192?e=1723680000&v=beta&t=b52ks1IjUpKJkfkXQ0kcVH99fqY_yXtWj7GpNhk673k" width="600" height="500">
                    <img src="https://static.wixstatic.com/media/870ce1_6e17d70ce7cf4616808641988252e0ca~mv2.png/v1/fill/w_987,h_576,al_c,q_90,usm_0.66_1.00_0.01,enc_auto/Full_Assembly_Spring_22_2022-Apr-05_07-42-33PM-000_CustomizedView19710368133.png" width="600" height="400">
                </div>`;
            break;
        default:
            infoBox.innerHTML = `<h1>Info</h1>
                <div>
                    <p>No information available.</p>
                </div>`;
    }
}

function openIntroduction() {
    window.open("introduction.html", "_self");
}

