Work Integrated Learning (WIL) Check-In System






A secure full-stack web application that streamlines Work Integrated Learning (WIL) management.
Students can record daily check-ins, submit logbooks, and upload monthly timesheets, while mentors, coordinators, and MICTSETA staff monitor progress via real-time dashboards with analytics.

🔹 Features

Student Portal

Daily check-ins (3x per day)

Upload logbooks & timesheets

View attendance history

Mentor & Coordinator Portal

Real-time monitoring of student activity

Review submissions, approve or provide feedback

Analytics dashboards

Admin Portal

Manage users and roles

Oversee all submissions

Export reports

Security

Role-based access control

Two-Factor Authentication (2FA)

Secure file uploads

🛠️ Technology Stack

Backend: Python, Flask

Frontend: HTML, CSS, Bootstrap, JavaScript

Database: SQLite / MySQL

Security: Flask-Login, PyOTP (2FA), hashed passwords

Reporting: Pandas for Excel reports, Chart.js for analytics

⚡ Installation

Clone the repository

git clone https://github.com/Napster-12/check-in-UPDATES-V02.git
cd check-in-UPDATES-V02

Create a virtual environment

python -m venv env
source env/bin/activate   # Linux / macOS
env\Scripts\activate      # Windows

Install dependencies

pip install -r requirements.txt

Initialize the database & run

python app.py

Open in your browser: http://127.0.0.1:5000/

🎨 Screenshots


🚀 Usage

Register Users: Students, mentors, coordinators, and admins

2FA Setup: Scan QR code to enable two-factor authentication

Student Actions: Check in, submit logbooks, and timesheets

Mentor/Coordinator Actions: Monitor dashboards, approve/reject submissions

Admin Actions: Manage users and export reports

🤝 Contributing

Fork the repository

Create a branch (git checkout -b feature-name)

Commit your changes (git commit -m "Add new feature")

Push to your branch (git push origin feature-name)

Open a pull request

📄 License

This project is licensed under the MIT License – see the LICENSE
 file for details.
