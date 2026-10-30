
import os
import io
import csv
import math
import sqlite3
import secrets
import base64
from datetime import datetime, timedelta
from functools import wraps

import qrcode
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DATABASE = "attendance.db"
ALLOWED_RADIUS_METRES = 50
QR_EXPIRY_MINUTES = 5

# Temporary QR data. QR codes expire after five minutes.
active_qr = {}


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL UNIQUE,
            student_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            subject TEXT NOT NULL,
            teacher_id INTEGER,
            attendance_time TEXT NOT NULL,
            latitude REAL,
            longitude REAL
        )
    """)

    # Add teacher_id to older attendance databases if necessary.
    columns = [
        row["name"]
        for row in cur.execute("PRAGMA table_info(attendance)").fetchall()
    ]
    if "teacher_id" not in columns:
        cur.execute("ALTER TABLE attendance ADD COLUMN teacher_id INTEGER")

    conn.commit()
    conn.close()


init_db()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "teacher_id" not in session:
            return redirect(url_for("teacher"))
        return func(*args, **kwargs)
    return wrapper


def distance_metres(lat1, lon1, lat2, lon2):
    radius = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def valid_coordinate(value):
    try:
        number = float(value)
        return math.isfinite(number)
    except (TypeError, ValueError):
        return False


def qr_image_data(url):
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return "data:image/png;base64," + encoded


# ---------------- HOME ----------------

@app.route("/")
def home():
    return render_template("index.html")


# ---------------- TEACHER REGISTRATION ----------------

@app.route("/teacher/register", methods=["GET", "POST"])
def teacher_register():
    error = None

    if request.method == "POST":
        teacher_name = request.form.get("teacher_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not teacher_name or not username or not password:
            error = "Please fill in all fields."
        elif len(password) < 8:
            error = "Password must contain at least 8 characters."
        else:
            conn = get_db()
            try:
                conn.execute("""
                    INSERT INTO teachers
                    (teacher_name, username, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    teacher_name,
                    username,
                    generate_password_hash(password),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()
                conn.close()
                flash("Account created successfully. Please log in.")
                return redirect(url_for("teacher"))

            except sqlite3.IntegrityError:
                conn.close()
                error = "This username already exists. Choose another username."

    return render_template("teacher_register.html", error=error)


# ---------------- TEACHER LOGIN ----------------

@app.route("/teacher", methods=["GET", "POST"])
def teacher():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        teacher_record = conn.execute(
            "SELECT * FROM teachers WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if teacher_record and check_password_hash(
            teacher_record["password_hash"], password
        ):
            session.clear()
            session["teacher_id"] = teacher_record["id"]
            session["teacher_name"] = teacher_record["teacher_name"]
            session["username"] = teacher_record["username"]
            return redirect(url_for("dashboard"))

        error = "Invalid username or password."

    return render_template("teacher.html", error=error)


# ---------------- TEACHER DASHBOARD ----------------

@app.route("/teacher/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    qr_data = None
    error = None

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        lat = request.form.get("teacher_latitude", "")
        lon = request.form.get("teacher_longitude", "")

        if not subject:
            error = "Please enter the subject."
        elif not valid_coordinate(lat) or not valid_coordinate(lon):
            error = "Please capture the teacher's location first."
        else:
            lat = float(lat)
            lon = float(lon)

            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                error = "Invalid location coordinates."
            else:
                token = secrets.token_urlsafe(24)
                active_qr[token] = {
                    "subject": subject,
                    "teacher_id": session["teacher_id"],
                    "latitude": lat,
                    "longitude": lon,
                    "expires": datetime.now() + timedelta(
                        minutes=QR_EXPIRY_MINUTES
                    )
                }

                student_url = url_for(
                    "student",
                    token=token,
                    _external=True
                )
                qr_data = qr_image_data(student_url)

    conn = get_db()
    records = conn.execute("""
        SELECT student_id, student_name, subject, attendance_time
        FROM attendance
        WHERE teacher_id = ?
        ORDER BY id DESC
    """, (session["teacher_id"],)).fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        records=records,
        qr_data=qr_data,
        error=error,
        teacher_name=session.get("teacher_name")
    )


# ---------------- STUDENT REGISTRATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    student_id = None

    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip()

        if not student_name:
            error = "Please enter your name."
        else:
            conn = get_db()
            next_number = conn.execute(
                "SELECT COUNT(*) AS total FROM students"
            ).fetchone()["total"] + 1

            student_id = "STU" + str(next_number).zfill(4)

            try:
                conn.execute("""
                    INSERT INTO students
                    (student_id, student_name, created_at)
                    VALUES (?, ?, ?)
                """, (
                    student_id,
                    student_name,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()
            except sqlite3.IntegrityError:
                error = "Registration failed. Please try again."
                student_id = None

            conn.close()

    return render_template(
        "register.html",
        error=error,
        student_id=student_id
    )


# ---------------- STUDENT ATTENDANCE ----------------

@app.route("/student", methods=["GET", "POST"])
def student():
    token = request.args.get("token") or request.form.get("token", "")
    message = None
    valid = False
    subject = ""

    qr = active_qr.get(token)

    if not qr:
        message = "Invalid or expired QR code."
        return render_template(
            "student.html", token=token,
            message=message, valid=False, subject=subject
        )

    if datetime.now() > qr["expires"]:
        active_qr.pop(token, None)
        message = "QR code has expired. Ask your teacher to generate a new one."
        return render_template(
            "student.html", token=token,
            message=message, valid=False, subject=subject
        )

    subject = qr["subject"]

    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        lat = request.form.get("latitude", "")
        lon = request.form.get("longitude", "")

        if not student_id:
            message = "Please enter your Student ID."
        elif not valid_coordinate(lat) or not valid_coordinate(lon):
            message = "Please allow location access and try again."
        else:
            lat = float(lat)
            lon = float(lon)

            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                message = "Invalid location coordinates."
            else:
                distance = distance_metres(
                    qr["latitude"], qr["longitude"], lat, lon
                )

                if distance > ALLOWED_RADIUS_METRES:
                    message = (
                        "Attendance rejected. You are outside the "
                        "50-metre allowed area."
                    )
                else:
                    conn = get_db()

                    student_record = conn.execute(
                        "SELECT * FROM students WHERE student_id = ?",
                        (student_id,)
                    ).fetchone()

                    if not student_record:
                        message = "Student ID not found. Register first."
                    else:
                        already_marked = conn.execute("""
                            SELECT id FROM attendance
                            WHERE student_id = ?
                            AND subject = ?
                            AND teacher_id = ?
                            AND attendance_time >= ?
                        """, (
                            student_id,
                            subject,
                            qr["teacher_id"],
                            datetime.now().strftime("%Y-%m-%d") + " 00:00:00"
                        )).fetchone()

                        if already_marked:
                            message = "Attendance already marked for this subject today."
                        else:
                            conn.execute("""
                                INSERT INTO attendance
                                (student_id, student_name, subject,
                                 teacher_id, attendance_time, latitude, longitude)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                student_record["student_id"],
                                student_record["student_name"],
                                subject,
                                qr["teacher_id"],
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                lat,
                                lon
                            ))
                            conn.commit()
                            message = "Attendance marked successfully!"
                            valid = True

                    conn.close()

    return render_template(
        "student.html",
        token=token,
        message=message,
        valid=valid,
        subject=subject
    )


# ---------------- DOWNLOAD CSV ----------------

@app.route("/teacher/download")
@login_required
def download_attendance():
    conn = get_db()
    records = conn.execute("""
        SELECT student_id, student_name, subject, attendance_time
        FROM attendance
        WHERE teacher_id = ?
        ORDER BY id DESC
    """, (session["teacher_id"],)).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Student ID", "Student Name", "Subject", "Attendance Time"
    ])

    for record in records:
        writer.writerow([
            record["student_id"],
            record["student_name"],
            record["subject"],
            record["attendance_time"]
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=attendance.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("teacher"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
