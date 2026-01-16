from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, send_from_directory,
    session, abort, send_file, make_response
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user, UserMixin
)
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import Column, Integer, String, DateTime, func
from datetime import datetime, timedelta
import pytz
import os
import random
import csv

# =========================================================
# APP CONFIG
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'replace_this_with_a_strong_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'moepi.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Uploads
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# =========================================================
# MAIL CONFIG (CPANEL)
# =========================================================

app.config['MAIL_SERVER'] = 'mail.tekete.co.za'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'check-in@tekete.co.za'
app.config['MAIL_PASSWORD'] = 'Publishing@2025'
app.config['MAIL_DEFAULT_SENDER'] = ('Check-In System', 'check-in@tekete.co.za')

mail = Mail(app)

# =========================================================
# DB + LOGIN
# =========================================================

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Token serializer
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# =========================================================
# MODELS
# =========================================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    role = db.Column(db.String(50), nullable=False)
    organization = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Student fields
    student_number = db.Column(db.String(50))
    department = db.Column(db.String(100))
    institution_type = db.Column(db.String(100))
    wil_coordinator_id = Column(Integer)

    # Mentor mapping
    mentor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    students = db.relationship(
        'User',
        backref=db.backref('mentor', remote_side=[id]),
        lazy='dynamic'
    )

    # Relationships
    checkins = db.relationship('CheckIn', backref='user', lazy=True)
    timesheets = db.relationship('Timesheet', backref='user', lazy=True)
    assignments = db.relationship('Assignment', backref='user', lazy=True)

    # Password helpers
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class CheckIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slot = db.Column(db.String(10), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    date = db.Column(db.Date, nullable=False)
    comment = db.Column(db.String(255))


class Timesheet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(400), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    filename = db.Column(db.String(200))
    filepath = db.Column(db.String(400))
    upload_date = db.Column(db.DateTime)
    wb1_submitted = db.Column(db.Boolean, default=False)
    wbl2_submitted = db.Column(db.Boolean, default=False)
    wbl3_submitted = db.Column(db.Boolean, default=False)

# =========================================================
# LOGIN MANAGER
# =========================================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# =========================================================
# EMAIL OTP HELPERS (NEW 2FA)
# =========================================================

def generate_email_otp():
    """Generate 6-digit numeric OTP"""
    return str(random.randint(100000, 999999))


def send_login_otp(email, otp):
    """Send OTP to user email"""
    msg = Message(
        subject="Your Login Verification Code",
        recipients=[email],
        body=f"""
Your login verification code is:

{otp}

This code will expire in 5 minutes.

If you did not attempt to log in, please ignore this email.
"""
    )
    mail.send(msg)


def store_otp_in_session(user_id, otp):
    session['email_otp'] = otp
    session['otp_user_id'] = user_id
    session['otp_expires_at'] = (
        datetime.utcnow() + timedelta(minutes=5)
    ).isoformat()


def verify_session_otp(entered_otp):
    stored_otp = session.get('email_otp')
    expires_at = session.get('otp_expires_at')
    user_id = session.get('otp_user_id')

    if not stored_otp or not expires_at or not user_id:
        return None

    if datetime.utcnow() > datetime.fromisoformat(expires_at):
        return None

    if entered_otp != stored_otp:
        return None

    # Cleanup
    session.pop('email_otp', None)
    session.pop('otp_expires_at', None)
    session.pop('otp_user_id', None)

    return User.query.get(user_id)

# =========================================================
# CONSTANTS
# =========================================================

CHECKIN_SLOTS = ["11:00", "13:00", "16:00"]
ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'csv', 'docx', 'png', 'jpg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# -------------------- Routes --------------------
@app.route('/')
def home():
    return render_template('home.html')



# -------------------- Registration --------------------
# -------------------- Registration --------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # ------------------- Common Fields -------------------
        fullname = request.form.get('fullname', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')

        if not fullname or not email or not password or not confirm:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for('register'))

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('register'))

        # Only allow certain domains
        allowed_domains = ('@tekete.co.za', '@vut.ac.za', '@micseta.org.za', '@edu.vut.ac.za', 
                           '@tut.ac.za', '@moepipublishing.co.za', '@tut4life.ac.za',
                           '@mylife.unisa.ac.za', '@tuks.ac.za','@myturf.ul.ac.za', 
                           '@student.uj.ac.za', '@students.wits.ac.za', '@sun.ac.za', 
                           '@students.nwu.ac.za','@stu.ukzn.ac.za', '@campus.ru.ac.za', 
                           '@ufs4life.ac.za', '@univen.ac.za', '@spu.ac.za', '@wsu.ac.za', 
                           '@dut4life.ac.za', '@mycput.ac.za', '@smu.ac.za', '@ufh.ac.za', 
                           '@mut.ac.za', '@ul.ac.za', '@cput.ac.za')
        if not email.endswith(allowed_domains):
            flash('Only organization emails allowed.', 'danger')
            return redirect(url_for('register'))

        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Account with this email already exists.', 'danger')
            return redirect(url_for('register'))

        # ------------------- Identify User Category -------------------
        user_category = request.form.get('user_category', '').strip()  # Student / Graduate / Admin

        # ------------------- Student Registration -------------------
        if user_category == 'Student':
            student_number = request.form.get('student_number', '').strip()
            institution_type = request.form.get('institution_type', '').strip()
            institution_name = request.form.get('institution_name', '').strip()
            department = request.form.get('department', '').strip()
            mentor_id = request.form.get('mentor_id', None)

            if not student_number or not institution_type or not institution_name or not department:
                flash("Please fill in all student fields.", "danger")
                return redirect(url_for('register'))

            user = User(
                fullname=fullname,
                email=email,
                role="Student",
                organization=institution_name,
                student_number=student_number,
                department=department,
                institution_type=institution_type,
                mentor_id=int(mentor_id) if mentor_id else None,
                is_admin=False
            )

        # ------------------- Graduate Registration -------------------
        elif user_category == 'Graduate':
            department = request.form.get('department', '').strip()
            qualification = request.form.get('qualification', '').strip()

            if not department or not qualification:
                flash("Please fill in all graduate fields.", "danger")
                return redirect(url_for('register'))

            user = User(
                fullname=fullname,
                email=email,
                role="Graduate",
                department=department,
                qualification=qualification,
                is_admin=False
            )

        # ------------------- Admin Registration -------------------
        elif user_category == 'Admin':
            user_type_form = request.form.get('user_type', '').strip()  # Admin type
            organization = request.form.get('organization', '').strip()

            if not user_type_form or not organization:
                flash("Please fill in all admin fields.", "danger")
                return redirect(url_for('register'))

            user = User(
                fullname=fullname,
                email=email,
                role=user_type_form,
                organization=organization,
                is_admin=user_type_form in ['Mentor', 'WIL Co-ordinator', 'Administrator']
            )

        else:
            flash("Please select a valid user category.", "danger")
            return redirect(url_for('register'))

        # ------------------- Set Password & Save -------------------
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created successfully! You can now log in.", "success")
        return redirect(url_for('login'))



    # ------------------- GET Request -------------------
    # Provide list of mentors for student dropdown
    mentors = User.query.filter(User.role.in_(['Mentor', 'MICSETA Mentor']), User.is_admin == True).order_by(User.fullname.asc()).all()
    return render_template('register.html', mentors=mentors)





# -------------------- Login with 2FA --------------------
import pyotp
import qrcode
import io
import base64

from flask import session

@app.route('/login', methods=['GET', 'POST'])
def login():
    # -------------------------------------------------
    # Already logged in → redirect by role
    # -------------------------------------------------
    if current_user.is_authenticated:
        if current_user.role == "Administrator":
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == "Mentor":
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == "WIL Co-ordinator":
            return redirect(url_for('wil_coordinator_dashboard'))
        elif current_user.role == "MICSETA Mentor":
            return redirect(url_for('mictseta_dashboard'))
        else:
            return redirect(url_for('dashboard'))

    # -------------------------------------------------
    # STEP 1: Email + Password → Send Email OTP
    # -------------------------------------------------
    if request.method == 'POST' and 'otp' not in request.form:
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        allowed_domains = (
            '@tekete.co.za', '@vut.ac.za', '@micseta.org.za',
            '@edu.vut.ac.za', '@tut.ac.za', '@moepipublishing.co.za',
            '@tut4life.ac.za', '@mylife.unisa.ac.za', '@tuks.ac.za',
            '@myturf.ul.ac.za', '@student.uj.ac.za', '@students.wits.ac.za',
            '@sun.ac.za', '@students.nwu.ac.za', '@stu.ukzn.ac.za',
            '@campus.ru.ac.za', '@ufs4life.ac.za', '@univen.ac.za',
            '@spu.ac.za', '@wsu.ac.za', '@dut4life.ac.za',
            '@mycput.ac.za', '@smu.ac.za', '@ufh.ac.za', '@mut.ac.za',
            '@ul.ac.za', '@cput.ac.za'
        )

        if not email.endswith(allowed_domains):
            flash('Only organization emails are allowed.', 'danger')
            return redirect(url_for('login'))

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('login'))

        # ---------------- Email OTP ----------------
        otp = generate_email_otp()

        session['email_otp'] = otp
        session['otp_user_id'] = user.id
        session['otp_expires_at'] = (
            datetime.utcnow() + timedelta(minutes=5)
        ).isoformat()

        send_login_otp(user.email, otp)

        flash('A verification code has been sent to your email.', 'info')
        return render_template('verify_email_otp.html', email=user.email)

    # -------------------------------------------------
    # STEP 2: Verify Email OTP
    # -------------------------------------------------
    if request.method == 'POST' and 'otp' in request.form:
        entered_otp = request.form.get('otp', '').strip()

        stored_otp = session.get('email_otp')
        expires_at = session.get('otp_expires_at')
        user_id = session.get('otp_user_id')

        if not stored_otp or not expires_at or not user_id:
            flash('Session expired. Please log in again.', 'danger')
            return redirect(url_for('login'))

        if datetime.utcnow() > datetime.fromisoformat(expires_at):
            flash('Verification code expired.', 'danger')
            return redirect(url_for('login'))

        if entered_otp != stored_otp:
            flash('Invalid verification code.', 'danger')
            return redirect(url_for('login'))

        # ---------------- SUCCESS ----------------
        user = User.query.get(user_id)
        login_user(user)

        # Clean session
        session.pop('email_otp', None)
        session.pop('otp_expires_at', None)
        session.pop('otp_user_id', None)

        flash('Logged in successfully ✅', 'success')

        # Role-based redirect
        if user.role == "Administrator":
            return redirect(url_for('mentor_dashboard'))
        elif user.role == "Mentor":
            return redirect(url_for('mentor_dashboard'))
        elif user.role == "WIL Co-ordinator":
            return redirect(url_for('wil_coordinator_dashboard'))
        elif user.role == "MICSETA Mentor":
            return redirect(url_for('mictseta_dashboard'))
        else:
            return redirect(url_for('dashboard'))

    # -------------------------------------------------
    # GET request
    # -------------------------------------------------
    return render_template('login.html')


@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    """
    Handles 2FA verification.
    Regenerates QR on refresh so it never disappears.
    """

    user_id = session.get('pre_2fa_user_id')
    if not user_id:
        flash("Session expired. Please log in again.", "danger")
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('login'))

    # Ensure user has a secret
    if not user.two_factor_secret:
        user.two_factor_secret = pyotp.random_base32()
        db.session.commit()

    # Always generate QR from user's existing secret
    qr_b64 = None
    totp = pyotp.TOTP(user.two_factor_secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="Moepi Publishing")

    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_b64 = base64.b64encode(buffer.getvalue()).decode()

    # Handle POST (OTP submission)
    if request.method == 'POST':
        otp_input = request.form.get('otp', '').strip()
        if not otp_input:
            flash("Please enter the 6-digit code.", "danger")
            return redirect(url_for('verify_otp'))

        if totp.verify(otp_input, valid_window=1):
            login_user(user)
            session.pop('pre_2fa_user_id', None)
            flash("Two-factor authentication successful!", "success")

            # Role-based redirect
            if user.role == "Administrator":
                return redirect(url_for('mentor_dashboard'))
            elif user.role == "Mentor":
                return redirect(url_for('mentor_dashboard'))
            elif user.role == "WIL Co-ordinator":
                return redirect(url_for('wil_coordinator_dashboard'))
            elif user.role == "MICSETA Mentor":
                return redirect(url_for('mictseta_dashboard'))
            else:
                return redirect(url_for('dashboard'))

        flash("Invalid OTP. Please try again.", "danger")
        return redirect(url_for('verify_otp'))

    # Render page with QR ALWAYS included
    return render_template("verify_otp.html", qr_b64=qr_b64)






# -------------------- Logout --------------------
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'info')
    return redirect(url_for('home'))


# -------------------- Forgot / Reset Password --------------------
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = s.dumps(user.email, salt='password-reset-salt')
            reset_link = url_for('reset_password', token=token, _external=True)
            msg = Message('Password Reset Request', recipients=[user.email])
            msg.body = f"Hi {user.fullname},\n\nClick the link to reset your password:\n{reset_link}"
            mail.send(msg)
        flash('If this email exists, a reset link has been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except:
        flash('Invalid or expired link.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm = request.form.get('confirm')
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('reset_password', token=token))
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(password)
            db.session.commit()
            flash('Password reset successful.', 'success')
            return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)


# -------------------- Employee Dashboard --------------------
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))

    now = datetime.now()
    slot_states = {}
    for slot in CHECKIN_SLOTS:
        already = CheckIn.query.filter_by(user_id=current_user.id, slot=slot, date=now.date()).first()
        slot_states[slot] = {'already': bool(already), 'comment': already.comment if already else None}

    recent = CheckIn.query.filter_by(user_id=current_user.id).order_by(CheckIn.timestamp.desc()).limit(20).all()
    last_timesheet = Timesheet.query.filter_by(user_id=current_user.id).order_by(Timesheet.upload_date.desc()).first()
    return render_template('dashboard.html', slot_states=slot_states, now=now, recent=recent, last_timesheet=last_timesheet)


# -------------------- Check-in --------------------
@app.route('/checkin/<slot>', methods=['POST'])
@login_required
def checkin(slot):
    # South African timezone
    sa_tz = pytz.timezone("Africa/Johannesburg")
    now = datetime.now(sa_tz)  # Always use S.A. time

    if slot not in CHECKIN_SLOTS:
        flash('Invalid check-in slot.', 'danger')
        return redirect(url_for('dashboard'))

    comment = request.form.get('comment', '').strip()

    # Convert slot time to a datetime in SA timezone
    slot_time = datetime.strptime(slot, "%H:%M").time()
    slot_datetime = sa_tz.localize(datetime.combine(now.date(), slot_time))

    # Allowed window: exact time until +10 minutes
    start_time = slot_datetime
    end_time = slot_datetime + timedelta(minutes=10)

    # Validate check-in time
    if not (start_time <= now <= end_time):
        flash(f"⏰ Check-in for {slot} is only allowed until {end_time.strftime('%H:%M')}.", "danger")
        return redirect(url_for('dashboard'))

    # Prevent duplicate check-ins
    existing = CheckIn.query.filter_by(
        user_id=current_user.id,
        slot=slot,
        date=now.date()
    ).first()

    if existing:
        flash(f"You already checked in for {slot} today.", 'warning')
        return redirect(url_for('dashboard'))

    # Save record using SA time
    ci = CheckIn(
        user_id=current_user.id,
        slot=slot,
        timestamp=now,
        date=now.date(),
        comment=comment
    )
    db.session.add(ci)
    db.session.commit()

    flash(f"✅ Check-in for {slot} recorded successfully.", 'success')
    return redirect(url_for('dashboard'))


@app.route('/upload_timesheet', methods=['GET', 'POST'])
@login_required
def upload_timesheet_page():
    now = datetime.now()
    current_day = now.day
    current_month = now.month
    current_year = now.year

    if request.method == 'POST':
        if current_day != 28:
            flash("❌ Timesheets can only be uploaded on the 28th of each month.", "danger")
            return redirect(url_for('upload_timesheet_page'))

        file = request.files.get('timesheet')
        if not file:
            flash('⚠️ No file selected. Please choose a file.', 'warning')
            return redirect(url_for('upload_timesheet_page'))

        existing_timesheet = Timesheet.query.filter_by(user_id=current_user.id).filter(
            db.extract('month', Timesheet.upload_date) == current_month,
            db.extract('year', Timesheet.upload_date) == current_year
        ).first()

        if existing_timesheet:
            flash('❌ You have already uploaded a timesheet for this month.', 'danger')
            return redirect(url_for('upload_timesheet_page'))

        # Save file
        filename = secure_filename(file.filename)
        upload_folder = os.path.join(app.root_path, 'uploads', 'timesheets')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)

        # Save record in database
        new_timesheet = Timesheet(
            user_id=current_user.id,
            filename=filename,
            filepath=file_path,
            upload_date=now
        )
        db.session.add(new_timesheet)
        db.session.commit()

        # --- Send email to mentors ---
        mentors = User.query.filter(User.role.in_(["Mentor", "WIL Co-ordinator"])).all()
        for mentor in mentors:
            msg = Message(
                subject="New Timesheet Submitted",
                recipients=[mentor.email],
                body=f"Hello {mentor.fullname},\n\n"
                     f"Student {current_user.fullname} has uploaded their timesheet for {now.strftime('%B %Y')}.\n\n"
                     f"Login to the system to review or download the timesheet.\n\n"
                     f"Best regards,\nMoepi Attendance System"
            )
            mail.send(msg)
        # --------------------------------

        flash('✅ Timesheet uploaded successfully for this month!', 'success')
        return redirect(url_for('upload_timesheet_page'))

    last_timesheet = (
        Timesheet.query.filter_by(user_id=current_user.id)
        .order_by(Timesheet.upload_date.desc())
        .first()
    )

    return render_template('timsheet.html', last_timesheet=last_timesheet)




# ----------------- Serve Uploaded Timesheets -----------------
@app.route('/uploads/timesheets/<path:filename>')
@login_required
def uploaded_timesheet(filename):
    ts = Timesheet.query.filter(Timesheet.filepath.like(f"%{filename}")).first()
    if not ts or (ts.user_id != current_user.id and not getattr(current_user, 'is_admin', False)):
        flash("Access denied or file not found.", "danger")
        return redirect(url_for('dashboard'))

    folder = os.path.join(app.root_path, 'uploads', 'timesheets')
    return send_from_directory(folder, filename, as_attachment=True)




PER_PAGE = 10  # pagination size

@app.route('/mentor', methods=['GET'])
@login_required
def mentor_dashboard():

    if current_user.role not in ["Mentor", "WIL Co-ordinator"]:
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    # Filters
    name_filter = request.args.get('name', '')
    month_filter = request.args.get('month', '')
    year_filter = request.args.get('year', '')
    day_filter = request.args.get('day', '')

    # Page numbers
    page = request.args.get('page', 1, type=int)
    logpage = request.args.get('logpage', 1, type=int)
    timesheet_page = request.args.get('timesheet_page', 1, type=int)

    # Students
    students = User.query.filter_by(role="Student").all()

    # Check-ins
    checkins_query = CheckIn.query.join(User).filter(User.role=="Student")
    if name_filter:
        checkins_query = checkins_query.filter(CheckIn.user_id==int(name_filter))
    if month_filter:
        checkins_query = checkins_query.filter(db.extract('month', CheckIn.timestamp)==int(month_filter))
    if year_filter:
        checkins_query = checkins_query.filter(db.extract('year', CheckIn.timestamp)==int(year_filter))
    if day_filter:
        date_obj = datetime.fromisoformat(day_filter)
        checkins_query = checkins_query.filter(db.func.date(CheckIn.timestamp) == date_obj.date())
    checkins_paginated = checkins_query.order_by(CheckIn.timestamp.desc()).paginate(page=page, per_page=PER_PAGE)

    # Assignments
    assignments_query = Assignment.query.join(User).filter(User.role=="Student")
    if name_filter:
        assignments_query = assignments_query.filter(Assignment.user_id==int(name_filter))
    assignments_paginated = assignments_query.order_by(Assignment.upload_date.desc()).paginate(page=logpage, per_page=PER_PAGE)

    # Timesheets
    timesheets_query = Timesheet.query.join(User).filter(User.role=="Student")
    if name_filter:
        timesheets_query = timesheets_query.filter(Timesheet.user_id==int(name_filter))
    if month_filter:
        timesheets_query = timesheets_query.filter(db.extract('month', Timesheet.upload_date)==int(month_filter))
    if year_filter:
        timesheets_query = timesheets_query.filter(db.extract('year', Timesheet.upload_date)==int(year_filter))
    timesheets_paginated = timesheets_query.order_by(Timesheet.upload_date.desc()).paginate(page=timesheet_page, per_page=PER_PAGE)

    # Stats
    filtered_students = students
    if name_filter:
        filtered_students = [s for s in filtered_students if str(s.id) == name_filter]

    total_checkins = sum(len(s.checkins) for s in filtered_students)
    most_active_student = max(filtered_students, key=lambda s: len(s.checkins), default=None)
    least_active_student = min(filtered_students, key=lambda s: len(s.checkins), default=None)
    all_checkins = CheckIn.query.all()
    earliest_checkin = min(all_checkins, key=lambda c: c.timestamp, default=None)

    # Charts
    month_counts = [0]*12
    student_counts = {}
    attendance_labels = []
    attendance_counts = []

    for s in filtered_students:
        student_counts[s.fullname] = len(s.checkins)
        attendance_labels.append(s.fullname)
        attendance_counts.append(len(s.checkins))
        for c in s.checkins:
            month_counts[c.timestamp.month-1] += 1

    return render_template(
        "mentor_dashboard.html",
        employees=students,
        name_filter=name_filter,
        month_filter=month_filter,
        year_filter=year_filter,
        day_filter=day_filter,
        total_checkins=total_checkins,
        earliest_checkin=earliest_checkin,
        most_active_student_name=most_active_student.fullname if most_active_student else "-",
        least_active_student_name=least_active_student.fullname if least_active_student else "-",
        checkins_paginated=checkins_paginated,
        assignments_paginated=assignments_paginated,
        timesheets_paginated=timesheets_paginated,  # <-- added
        month_counts=month_counts,
        student_counts=student_counts,
        attendance_labels=attendance_labels,
        attendance_counts=attendance_counts,
        now=datetime.now()
    )


    

@app.route('/mentor/export_checkins')
@login_required
def export_checkins():
    if current_user.role not in ["Mentor", "WIL Co-ordinator"]:
        flash("Access denied.", "danger")
        return redirect(url_for('mentor_dashboard'))

    # Get filter parameters from query string
    name_filter = request.args.get('name', '')
    month_filter = request.args.get('month', '')
    year_filter = request.args.get('year', '')
    day_filter = request.args.get('day', '')

    # Query students
    students = User.query.filter_by(role="Student").all()

    # Query check-ins with filters
    checkins_query = CheckIn.query.join(User).filter(User.role=="Student")
    if name_filter:
        checkins_query = checkins_query.filter(CheckIn.user_id==int(name_filter))
    if month_filter:
        checkins_query = checkins_query.filter(db.extract('month', CheckIn.timestamp)==int(month_filter))
    if year_filter:
        checkins_query = checkins_query.filter(db.extract('year', CheckIn.timestamp)==int(year_filter))
    if day_filter:
        date_obj = datetime.fromisoformat(day_filter)
        checkins_query = checkins_query.filter(db.func.date(CheckIn.timestamp) == date_obj.date())

    checkins = checkins_query.order_by(CheckIn.timestamp.desc()).all()

    # Create CSV
    si = []
    header = ['Student Name', 'Date', 'Time', 'Comment']
    si.append(header)

    for c in checkins:
        row = [
            c.user.fullname,
            c.timestamp.strftime('%Y-%m-%d'),
            c.timestamp.strftime('%H:%M:%S'),
            c.comment or ''
        ]
        si.append(row)

    # Convert to CSV string
    output = ""
    for row in si:
        output += ','.join(f'"{str(i)}"' for i in row) + '\n'

    # Send as file response
    response = make_response(output)
    response.headers["Content-Disposition"] = "attachment; filename=checkins.csv"
    response.headers["Content-Type"] = "text/csv"
    return response

# Download route for assignments
@app.route('/mentor_download/<int:assignment_id>')
@login_required
def mentor_download(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)

    # Construct file path from UPLOAD_FOLDER + filename
    file_path = os.path.join(UPLOAD_FOLDER, assignment.filename)

    if os.path.exists(file_path):
        return send_from_directory(UPLOAD_FOLDER, assignment.filename, as_attachment=True)
    else:
        abort(404, description="File not found")
        
@app.route('/mentor/download_timesheet/<int:timesheet_id>')
@login_required
def mentor_download_timesheet(timesheet_id):
    # Fetch the timesheet record
    ts = Timesheet.query.get_or_404(timesheet_id)

    # Allow download if:
    # - The user is the owner of the timesheet
    # - The user is a mentor
    # - The user is an admin
    allowed_roles = ['Mentor', 'Admin']
    if current_user.id != ts.user_id and getattr(current_user, 'role', None) not in allowed_roles:
        flash("Access denied or file not found.", "danger")
        return redirect(url_for('mentor_dashboard'))

    # Extract folder path from filepath
    folder = os.path.join(app.root_path, 'uploads', 'timesheets')
    filename = os.path.basename(ts.filepath)

    # Ensure the file exists
    if not os.path.exists(os.path.join(folder, filename)):
        flash("File not found on server.", "danger")
        return redirect(url_for('mentor_dashboard'))

    # Send the file to the browser
    return send_from_directory(folder, filename, as_attachment=True)




@app.route('/admin/data', methods=['GET'])
@login_required
def admin_dashboard_data():
    # ------------------- Filters -------------------
    name_filter = request.args.get('name', '').strip()
    month_filter = request.args.get('month', '')
    year_filter = request.args.get('year', '')
    day_filter = request.args.get('day', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # ------------------- Base Query -------------------
    query = CheckIn.query.join(User).filter(User.role == "Student")

    # Restrict Mentor to only assigned students
    if current_user.role == "Mentor":
        query = query.filter(User.mentor_id == current_user.id)

    # ------------------- Apply Filters -------------------
    if name_filter:
        try:
            query = query.filter(User.id == int(name_filter))
        except ValueError:
            return jsonify({"error": "Invalid student selected."})

    if month_filter:
        try:
            query = query.filter(db.extract('month', CheckIn.date) == int(month_filter))
        except:
            pass

    if year_filter:
        try:
            query = query.filter(db.extract('year', CheckIn.date) == int(year_filter))
        except:
            pass

    if day_filter:
        try:
            day_date = datetime.strptime(day_filter, "%Y-%m-%d").date()
            query = query.filter(CheckIn.date == day_date)
        except ValueError:
            return jsonify({"error": "Invalid day filter."})

    # ------------------- Pagination -------------------
    pagination = query.order_by(CheckIn.date.desc(), CheckIn.timestamp.desc()).paginate(page=page, per_page=per_page)
    checkins = pagination.items

    # ------------------- Stats -------------------
    total_checkins = query.count()
    unique_days = len(set([c.date for c in query.all()]))
    absent_count = max(0, 22 - unique_days)

    # Employee statistics
    employee_data = (
        db.session.query(User.fullname, func.count(CheckIn.id))
        .join(CheckIn)
        .filter(User.role == "Student")
        .group_by(User.fullname)
        .order_by(User.fullname)
        .all()
    )

    # Monthly check-ins
    month_data = (
        db.session.query(func.strftime('%m', CheckIn.date).label('month'), func.count(CheckIn.id))
        .join(User)
        .filter(User.role == "Student")
        .group_by('month')
        .order_by('month')
        .all()
    )

    return jsonify({
        "page": page,
        "total_pages": pagination.pages,
        "checkins": [
            {
                "id": c.id,
                "user_id": c.user_id,
                "employee": c.user.fullname,
                "date": c.date.strftime("%Y-%m-%d"),
                "time": c.timestamp.strftime("%H:%M:%S"),
                "comment": c.comment
            } for c in checkins
        ],
        "total_checkins": total_checkins,
        "present_count": total_checkins,
        "absent_count": absent_count,
        "employee_names": [e for e, _ in employee_data],
        "employee_counts": [c for _, c in employee_data],
        "month_labels": [datetime.strptime(m, '%m').strftime('%B') for m, _ in month_data],
        "month_counts": [c for _, c in month_data],
        "most_active_employee": employee_data[0][0] if employee_data else '-',
        "least_active_employee": employee_data[-1][0] if employee_data else '-'
    })



@app.route('/upload_assignment_page', methods=['GET', 'POST'])
@login_required
def upload_assignment_page():
    flash_msg = None

    if request.method == 'POST':
        logbook_field = None
        logbook_type = None

        if 'wb1' in request.files:
            logbook_field = request.files['wb1']
            logbook_type = 'wb1'
        elif 'wbl2' in request.files:
            logbook_field = request.files['wbl2']
            logbook_type = 'wbl2'
        elif 'wbl3' in request.files:
            logbook_field = request.files['wbl3']
            logbook_type = 'wbl3'

        if not logbook_field or logbook_field.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('upload_assignment_page'))

        if not allowed_file(logbook_field.filename):
            flash('Invalid file type. Only PDF, DOCX, XLSX, PNG, JPG allowed.', 'danger')
            return redirect(url_for('upload_assignment_page'))

        # Save file
        filename = secure_filename(logbook_field.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{current_user.id}_{logbook_type}_{timestamp}_{filename}"

        upload_folder = os.path.join(BASE_DIR, 'static', 'uploads', 'assignments')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, unique_filename)
        logbook_field.save(filepath)

        # Save in database
        relative_path = os.path.relpath(filepath, BASE_DIR)
        new_assignment = Assignment(
            user_id=current_user.id,
            filename=filename,
            filepath=relative_path
        )

        # Mark the corresponding logbook as submitted
        if logbook_type == 'wb1':
            new_assignment.wb1_submitted = True
            flash_msg = "✅ WB1 submitted successfully!"
        elif logbook_type == 'wbl2':
            new_assignment.wbl2_submitted = True
            flash_msg = "✅ WBL2 submitted successfully!"
        elif logbook_type == 'wbl3':
            new_assignment.wbl3_submitted = True
            flash_msg = "✅ WBL3 submitted successfully!"

        db.session.add(new_assignment)
        db.session.commit()

        # --- Send email to all mentors / WIL coordinators ---
        mentors = User.query.filter(User.role.in_(["Mentor", "WIL Co-ordinator"])).all()
        for mentor in mentors:
            try:
                msg = Message(
                    subject=f"New {logbook_type.upper()} Uploaded by {current_user.fullname}",
                    recipients=[mentor.email]
                )
                msg.body = (
                    f"Hello {mentor.fullname},\n\n"
                    f"Student {current_user.fullname} has uploaded their {logbook_type.upper()}.\n"
                    "Please check the system for review.\n\n"
                    "Regards,\nMoepi Attendance System"
                )
                mail.send(msg)
            except Exception as e:
                print("❌ Failed to send email to mentor:", e)
        # -----------------------------------------------------

        if flash_msg:
            flash(flash_msg, 'success')

        return redirect(url_for('upload_assignment_page'))

    return render_template('projects.html')


UPLOAD_FOLDER = 'static/uploads/assignments'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Helper function to save file
def save_file(file, prefix):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{current_user.id}_{prefix}_{timestamp}_{secure_filename(file.filename)}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    return filename



@app.route('/upload/wb1', methods=['POST'])
@login_required
def upload_wb1():
    file = request.files.get('wb1_file')
    if not file or file.filename == '':
        flash("No file selected for WB1", "danger")
        return redirect(url_for('upload_assignment_page'))

    assignment = Assignment.query.filter_by(user_id=current_user.id).first()
    if assignment and assignment.wb1_submitted:
        flash("WB1 has already been submitted.", "info")
        return redirect(url_for('upload_assignment_page'))

    filename = save_file(file, 'wb1')

    if not assignment:
        assignment = Assignment(user_id=current_user.id)

    assignment.filename = filename
    assignment.upload_date = datetime.now()
    assignment.wb1_submitted = True

    db.session.add(assignment)
    db.session.commit()

    # 📧 SEND EMAIL TO MENTORS
    notify_mentors("WB1")

    flash("WB1 uploaded successfully ✅", "success")
    return redirect(url_for('upload_assignment_page'))




@app.route('/upload/wb2', methods=['POST'])
@login_required
def upload_wb2():
    file = request.files.get('wb2_file')
    if not file or file.filename == '':
        flash("No file selected for WB2", "danger")
        return redirect(url_for('upload_assignment_page'))

    assignment = Assignment.query.filter_by(user_id=current_user.id).first()
    if assignment and assignment.wbl2_submitted:
        flash("WB2 has already been submitted.", "info")
        return redirect(url_for('upload_assignment_page'))

    filename = save_file(file, 'wb2')

    if not assignment:
        assignment = Assignment(user_id=current_user.id)

    assignment.filename = filename
    assignment.upload_date = datetime.now()
    assignment.wbl2_submitted = True

    db.session.add(assignment)
    db.session.commit()

    # 📧 SEND EMAIL TO MENTORS
    notify_mentors("WB2")

    flash("WB2 uploaded successfully ✅", "success")
    return redirect(url_for('upload_assignment_page'))




@app.route('/upload/wb3', methods=['POST'])
@login_required
def upload_wb3():
    file = request.files.get('wb3_file')
    if not file or file.filename == '':
        flash("No file selected for WB3", "danger")
        return redirect(url_for('upload_assignment_page'))

    assignment = Assignment.query.filter_by(user_id=current_user.id).first()
    if assignment and assignment.wbl3_submitted:
        flash("WB3 has already been submitted.", "info")
        return redirect(url_for('upload_assignment_page'))

    filename = save_file(file, 'wb3')

    if not assignment:
        assignment = Assignment(user_id=current_user.id)

    assignment.filename = filename
    assignment.upload_date = datetime.now()
    assignment.wbl3_submitted = True

    db.session.add(assignment)
    db.session.commit()

    # 📧 SEND EMAIL TO MENTORS
    notify_mentors("WB3")

    flash("WB3 uploaded successfully ✅", "success")
    return redirect(url_for('upload_assignment_page'))



@app.route('/mentor/assignments')
@login_required
def mentor_assignments():
    if current_user.role != "Mentor":
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    
    students = User.query.filter_by(mentor_id=current_user.id, role='Student').all()
    student_ids = [s.id for s in students]

    
    assignments = Assignment.query.filter(Assignment.user_id.in_(student_ids)).order_by(Assignment.upload_date.desc()).all()
    return render_template('mentor_assignments.html', assignments=assignments, students=students)



    return send_from_directory(
        directory=os.path.join(BASE_DIR, os.path.dirname(assignment.filepath)),
        path=os.path.basename(assignment.filepath),
        as_attachment=True
    )

app.route('/mentor/download/<int:assignment_id>')
def mentor_download(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    logbook_dir = os.path.join(app.root_path, 'uploads/logbooks')  # adjust path
    file_path = os.path.join(logbook_dir, assignment.filename)
    if os.path.exists(file_path):
        return send_from_directory(logbook_dir, assignment.filename, as_attachment=True)
    else:
        abort(404)
        
@app.route('/mictseta_dashboard', methods=['GET'])
@login_required
def mictseta_dashboard():
    if current_user.role != "MICSETA Mentor":
        flash("Access denied. Only MICSETA Mentors can access this page.", "danger")
        return redirect(url_for('dashboard'))

    # ------------------- Filters -------------------
    institution_filter = request.args.get('institution', '').strip()
    student_filter = request.args.get('student', '').strip()
    month_filter = request.args.get('month', '')
    year_filter = request.args.get('year', '')
    department_filter = request.args.get('department', '')

    now = datetime.now()

    # ------------------- Students linked to this MICSETA Mentor -------------------
    students_query = User.query.filter(
        User.role == "Student",
        User.mentor_id == current_user.id
    ).order_by(User.fullname.asc())

    if institution_filter:
        students_query = students_query.filter(User.organization.ilike(f"%{institution_filter}%"))

    if student_filter:
        try:
            students_query = students_query.filter(User.id == int(student_filter))
        except ValueError:
            flash("Invalid student selected.", "warning")

    if department_filter:
        students_query = students_query.filter(User.department.ilike(f"%{department_filter}%"))

    students = students_query.all()

    student_ids = [s.id for s in students]

    # ------------------- Base CheckIn Query -------------------
    query = CheckIn.query.join(User).filter(
        User.role == "Student",
        User.id.in_(student_ids)
    )

    if month_filter:
        try:
            query = query.filter(db.extract('month', CheckIn.date) == int(month_filter))
        except:
            pass

    if year_filter:
        try:
            query = query.filter(db.extract('year', CheckIn.date) == int(year_filter))
        except:
            pass

    # ------------------- Pagination -------------------
    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(CheckIn.date.desc(), CheckIn.timestamp.desc()).paginate(page=page, per_page=20)
    checkins = pagination.items

    # ------------------- Stats -------------------
    total_checkins = query.count()
    overall_check = CheckIn.query.count()
    highest_checkin_student = (
        db.session.query(User.fullname, db.func.count(CheckIn.id).label('total'))
        .join(CheckIn)
        .filter(User.mentor_id == current_user.id)
        .group_by(User.id)
        .order_by(db.desc('total'))
        .first()
    )
    earliest_checkin = db.session.query(CheckIn).order_by(CheckIn.timestamp.asc()).first()

    # ------------------- Chart Data -------------------
    from sqlalchemy import func

    month_data = (
        db.session.query(func.strftime('%m', CheckIn.date).label('month'), func.count(CheckIn.id))
        .join(User)
        .filter(User.role == "Student", User.mentor_id == current_user.id)
        .group_by('month')
        .order_by('month')
        .all()
    )
    month_labels = [datetime.strptime(m, '%m').strftime('%B') for m, _ in month_data]
    month_counts = [c for _, c in month_data]

    department_data = (
        db.session.query(User.department, func.count(User.id))
        .filter(User.role == "Student", User.mentor_id == current_user.id)
        .group_by(User.department)
        .all()
    )
    department_names = [d for d, _ in department_data]
    department_counts = [c for _, c in department_data]

    # Attendance
    all_days = 22
    unique_days = len(set([c.date for c in query.all()]))
    absent_days = max(0, all_days - unique_days)
    attendance_labels = ['Present Days', 'Absent Days']
    attendance_data = [unique_days, absent_days]

    # ------------------- Render Template -------------------
    return render_template(
        'mictseta_dashboard.html',
        checkins=checkins,
        pagination=pagination,
        total_checkins=total_checkins,
        overall_check=overall_check,
        highest_checkin_student=highest_checkin_student,
        earliest_checkin=earliest_checkin,
        students=students,
        institution_filter=institution_filter,
        student_filter=student_filter,
        month_filter=month_filter,
        year_filter=year_filter,
        department_filter=department_filter,
        now=now,
        month_labels=month_labels,
        month_counts=month_counts,
        department_names=department_names,
        department_counts=department_counts,
        attendance_labels=attendance_labels,
        attendance_data=attendance_data
    )

@app.route('/wil_coordinator_dashboard', methods=['GET'])
@login_required
def wil_coordinator_dashboard():

    if current_user.role != "WIL Co-ordinator":
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    # ---------------- GET MENTORS ----------------
    mentors = User.query.filter_by(role="Mentor").all()

    # ---------------- GET STUDENTS ----------------
    students = User.query.filter_by(role="Student").all()

    # ---------------- GET CHECKINS ----------------
    checkins = CheckIn.query.all()

    # Attach check-ins to each student
    for s in students:
        s.checkins = [c for c in checkins if c.user_id == s.id]

    # ---------------- GET ASSIGNMENTS ----------------
    assignments = Assignment.query.all()
    assignment_counts = {}
    for a in assignments:
        assignment_counts[a.user_id] = assignment_counts.get(a.user_id, 0) + 1

    # ---------------- SERIALIZE USERS ----------------
    def serialize_user(u):
        return {
            "id": u.id,
            "fullname": u.fullname,
            "role": u.role,
            "organization": u.organization,
            "department": u.department,
            "mentor_id": u.mentor_id,
            "wil_coordinator_id": getattr(u, 'wil_coordinator_id', None)
        }

    def serialize_student(s):
        return {
            "id": s.id,
            "fullname": s.fullname,
            "mentor_id": s.mentor_id,
            "wil_coordinator_id": s.wil_coordinator_id,
            "organization": s.organization,
            "department": s.department,
            "checkins": [
                {
                    "timestamp": c.timestamp.isoformat(),
                    "date": c.date.isoformat()
                }
                for c in s.checkins
            ]
        }

    # Serialize all mentors and students
    users_serialized = [serialize_user(u) for u in mentors + students]
    students_serialized = [serialize_student(s) for s in students]

    return render_template(
        "wil_coordinator_dashboard.html",
        users=users_serialized,
        students=students_serialized,
        assignment_counts=assignment_counts
    )





# -------------------- Run --------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  
    app.run(debug=True)

