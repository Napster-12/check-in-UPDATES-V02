import random
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ----------------------------
# CONFIG
# ----------------------------
DATABASE_FILE = "moepi.db"
STUDENT_COUNT = 50  # Number of dummy students to generate
CHECKIN_SLOTS = ["11:00", "13:00", "16:00"]
START_DATE = datetime.now() - timedelta(days=90)
END_DATE = datetime.now()

# ----------------------------
# RANDOM NAMES
# ----------------------------
first_names = ["Thabo", "Mpho", "Sipho", "Lerato", "Nandi", "Karabo", "Ayanda", "Musa", "Precious", "Linda", "Junior", "Palesa", "Thando"]
last_names = ["Mokoena", "Dlamini", "Sithole", "Nkosi", "Mashaba", "Baloyi", "Mabaso", "Khumalo", "Mavuso", "Ndlovu", "Maluleka", "Mulaudzi"]

comments = ["SQL injecting", "Meeting", "Prototype discussion", "Frontend development", "Database maintenance", "Backend maintenance"]

universities = ["University of Johannesburg", "University of Pretoria", "Rhodes University", "University of Cape Town", "Cape Peninsula University of Technology", "Tshwane University of Technology"]

def email_format(f, l, i=None):
    if i is not None:
        return f"{f.lower()}.{l.lower()}{i}@tekete.co.za"
    return f"{f.lower()}.{l.lower()}@tekete.co.za"

# ----------------------------
# DATABASE SETUP
# ----------------------------
engine = create_engine(f"sqlite:///{DATABASE_FILE}")
Session = sessionmaker(bind=engine)
session = Session()

# ----------------------------
# ENSURE TABLES EXIST
# ----------------------------
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fullname TEXT, email TEXT UNIQUE, password_hash TEXT, role TEXT, is_admin INTEGER,
            organization TEXT, student_number TEXT, department TEXT, institution_type TEXT,
            mentor_id INTEGER, wil_coordinator_id INTEGER, created_at DATETIME
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS check_in (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, slot TEXT, timestamp DATETIME, date DATE, comment TEXT
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS assignment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, title TEXT, submitted_at DATETIME
        )
    """))
    conn.commit()

# ----------------------------
# GET EXISTING MENTORS
# ----------------------------
mentors = [r[0] for r in session.execute(text("SELECT id FROM user WHERE role='Mentor'")).fetchall()]
if not mentors:
    raise Exception("No existing mentors found. Please create at least one mentor.")

# ----------------------------
# CREATE DUMMY WIL COORDINATOR IF NONE EXISTS
# ----------------------------
wil_cos = [r[0] for r in session.execute(text("SELECT id FROM user WHERE role='wil_coordinator'")).fetchall()]

if not wil_cos:
    password_hash = generate_password_hash("Password123")
    session.execute(text("""
        INSERT INTO user (
            fullname, email, password_hash, role, is_admin, organization,
            student_number, department, institution_type, mentor_id, wil_coordinator_id, created_at
        ) VALUES (
            'Default WIL Coordinator', 'coordinator@tekete.co.za', :password, 'wil_coordinator', 0, 'Tekete',
            NULL, 'IT', 'University', NULL, NULL, :created
        )
    """), {"password": password_hash, "created": datetime.now()})
    session.commit()
    wil_cos = [r[0] for r in session.execute(text("SELECT id FROM user WHERE role='wil_coordinator'")).fetchall()]
    print("✔ Dummy WIL Coordinator created.")

# ----------------------------
# DELETE PREVIOUS DUMMY STUDENTS
# ----------------------------
session.execute(text("DELETE FROM check_in WHERE user_id IN (SELECT id FROM user WHERE role='Student')"))
session.execute(text("DELETE FROM assignment WHERE user_id IN (SELECT id FROM user WHERE role='Student')"))
session.execute(text("DELETE FROM user WHERE role='Student'"))
session.commit()
print("✔ Previous dummy students removed.")

# ----------------------------
# CREATE DUMMY STUDENTS
# ----------------------------
password_hash = generate_password_hash("Password123")

for i in range(STUDENT_COUNT):
    fname = random.choice(first_names)
    lname = random.choice(last_names)
    email = email_format(fname, lname, i + 1000)
    mentor_id = random.choice(mentors)
    wil_id = random.choice(wil_cos)
    org = random.choice(universities)

    session.execute(text("""
        INSERT INTO user (
            fullname, email, password_hash, role, is_admin, organization,
            student_number, department, institution_type, mentor_id, wil_coordinator_id, created_at
        ) VALUES (
            :fullname, :email, :password, 'Student', 0, :org,
            :stu_num, 'IT', 'University', :mentor, :wil, :created
        )
    """), {
        "fullname": f"{fname} {lname}",
        "email": email,
        "password": password_hash,
        "org": org,
        "stu_num": f"STU{1000+i}",
        "mentor": mentor_id,
        "wil": wil_id,
        "created": datetime.now()
    })

session.commit()

# ----------------------------
# GENERATE DUMMY CHECK-INS
# ----------------------------
students = [r[0] for r in session.execute(text("SELECT id FROM user WHERE role='Student'")).fetchall()]

day = START_DATE
while day <= END_DATE:
    for stu in students:
        for slot in CHECKIN_SLOTS:
            if random.random() < 0.85:  # 85% attendance
                slot_time = datetime.strptime(slot, "%H:%M").time()
                timestamp = datetime.combine(day.date(), slot_time)
                comment = random.choice(comments)
                session.execute(text("""
                    INSERT INTO check_in (user_id, slot, timestamp, date, comment)
                    VALUES (:uid, :slot, :ts, :date, :comment)
                """), {"uid": stu, "slot": slot, "ts": timestamp, "date": day.date(), "comment": comment})
    day += timedelta(days=1)

session.commit()
print(f"✔ Created {STUDENT_COUNT} dummy students linked to existing mentors & WIL coordinators.")
print(f"✔ Dummy check-ins generated for the last 3 months.")
