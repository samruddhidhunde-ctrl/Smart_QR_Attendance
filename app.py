
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, Response
)
import sqlite3
import qrcode
import io
import base64
import csv
import secrets
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.secret_key = "demo-key-change-before-production"

DATABASE = "attendance.db"
QR_EXPIRY_MINUTES = 5

# Active QR codes are stored temporarily in memory.
active_qr = {}


# ---------------- DATABASE ----------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE,
            student_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            subject TEXT NOT NULL,
            token TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            UNIQUE(student_id, token)
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    return render_template("index.html")


# ---------------- STUDENT REGISTRATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    student_id = None
    error = None

    if request.method == "POST":
        student_name = request.form.get(
            "student_name", ""
        ).strip()

        if not student_name:
            error = "Please enter your full name."
        else:
            conn = get_db()

            cursor = conn.execute(
                """
                INSERT INTO students
                (student_name, created_at)
                VALUES (?, ?)
                """,
                (
                    student_name,
                    datetime.now(timezone.utc).isoformat()
                )
            )

            student_number = cursor.lastrowid
            student_id = f"STU{student_number:04d}"

            conn.execute(
                """
                UPDATE students
                SET student_id = ?
                WHERE id = ?
                """,
                (student_id, student_number)
            )

            conn.commit()
            conn.close()

    return render_template(
        "register.html",
        student_id=student_id,
        error=error
    )


# ---------------- TEACHER LOGIN ----------------

@app.route("/teacher", methods=["GET", "POST"])
def teacher():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == "teacher" and password == "teach123":
            session["teacher_logged_in"] = True
            return redirect(url_for("dashboard"))

        error = "Invalid username or password."

    return render_template("teacher.html", error=error)


# ---------------- TEACHER DASHBOARD ----------------

@app.route("/teacher/dashboard", methods=["GET", "POST"])
def dashboard():
    if not session.get("teacher_logged_in"):
        return redirect(url_for("teacher"))

    qr_image = None
    qr_subject = None
    qr_expires_at = None
    error = None

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()

        if not subject:
            error = "Please enter a subject name."
        else:
            token = secrets.token_urlsafe(24)
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(minutes=QR_EXPIRY_MINUTES)
            )

            active_qr[token] = {
                "subject": subject,
                "expires_at": expires_at
            }

            student_url = (
                request.url_root.rstrip("/")
                + url_for("student", token=token)
            )

            qr = qrcode.QRCode(
                version=1,
                box_size=8,
                border=4
            )
            qr.add_data(student_url)
            qr.make(fit=True)

            qr_image_object = qr.make_image(
                fill_color="black",
                back_color="white"
            )

            image_buffer = io.BytesIO()
            qr_image_object.save(image_buffer, format="PNG")

            qr_image = base64.b64encode(
                image_buffer.getvalue()
            ).decode("utf-8")

            qr_subject = subject
            qr_expires_at = expires_at.strftime("%H:%M:%S UTC")

    conn = get_db()

    records = conn.execute("""
        SELECT student_id, student_name, subject, recorded_at
        FROM attendance
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        records=records,
        qr_image=qr_image,
        qr_subject=qr_subject,
        qr_expires_at=qr_expires_at,
        error=error
    )


# ---------------- STUDENT ATTENDANCE ----------------

@app.route("/student", methods=["GET", "POST"])
def student():
    token = request.args.get("token") or request.form.get("token")
    valid = False
    message = None

    qr_info = active_qr.get(token) if token else None

    if qr_info:
        if datetime.now(timezone.utc) < qr_info["expires_at"]:
            valid = True
        else:
            active_qr.pop(token, None)
            message = "This QR code has expired. Please ask your teacher for a new one."
    else:
        message = "Invalid or expired QR code. Please scan a new QR code."

    if request.method == "POST" and valid:
        student_id = request.form.get("student_id", "").strip().upper()

        if not student_id:
            message = "Please enter your Student ID."
        else:
            conn = get_db()

            student_record = conn.execute(
                """
                SELECT student_id, student_name
                FROM students
                WHERE student_id = ?
                """,
                (student_id,)
            ).fetchone()

            if not student_record:
                message = "Student ID not found. Please register first."
            else:
                try:
                    conn.execute(
                        """
                        INSERT INTO attendance
                        (student_id, student_name, subject, token, recorded_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            student_record["student_id"],
                            student_record["student_name"],
                            qr_info["subject"],
                            token,
                            datetime.now(timezone.utc).strftime(
                                "%Y-%m-%d %H:%M:%S UTC"
                            )
                        )
                    )

                    conn.commit()
                    message = (
                        "Attendance marked successfully for "
                        + student_record["student_name"]
                        + "!"
                    )

                except sqlite3.IntegrityError:
                    message = "Your attendance has already been marked for this QR code."

            conn.close()

    return render_template(
        "student.html",
        valid=valid,
        token=token,
        message=message,
        subject=qr_info["subject"] if qr_info else None
    )


# ---------------- DOWNLOAD ATTENDANCE CSV ----------------

@app.route("/teacher/download")
def download_attendance():
    if not session.get("teacher_logged_in"):
        return redirect(url_for("teacher"))

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Student ID",
        "Student Name",
        "Subject",
        "Attendance Time"
    ])

    conn = get_db()

    records = conn.execute("""
        SELECT student_id, student_name, subject, recorded_at
        FROM attendance
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    for record in records:
        writer.writerow([
            record["student_id"],
            record["student_name"],
            record["subject"],
            record["recorded_at"]
        ])

    csv_content = "\ufeff" + output.getvalue()

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=attendance_sheet.csv"
        }
    )


# ---------------- TEACHER LOGOUT ----------------

@app.route("/teacher/logout")
def logout():
    session.pop("teacher_logged_in", None)
    return redirect(url_for("teacher"))


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
