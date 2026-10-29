
from flask import Flask, render_template, request, redirect, url_for, session
import qrcode
import io
import base64
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.secret_key = "demo-key-change-before-production"

DATABASE = "attendance.db"
active_qr = {}


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
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


init_db()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/teacher", methods=["GET", "POST"])
def teacher():
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == "teacher" and password == "teach123":
            session["teacher_logged_in"] = True
            return redirect(url_for("teacher_dashboard"))

        error = "Invalid username or password."

    return render_template("teacher.html", error=error)


@app.route("/teacher/dashboard", methods=["GET", "POST"])
def teacher_dashboard():
    if not session.get("teacher_logged_in"):
        return redirect(url_for("teacher"))

    qr_image = None
    subject = ""

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()

        if subject:
            token = secrets.token_urlsafe(16)

            active_qr.clear()
            active_qr.update({
                "token": token,
                "subject": subject,
                "expires": datetime.now(timezone.utc)
                + timedelta(minutes=5)
            })

            qr_data = url_for(
                "student", token=token, _external=True
            )

            qr = qrcode.make(qr_data)
            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")

            qr_image = base64.b64encode(
                buffer.getvalue()
            ).decode("utf-8")

    with get_db() as conn:
        records = conn.execute("""
            SELECT student_id, student_name, subject, recorded_at
            FROM attendance
            ORDER BY id DESC
        """).fetchall()

    return render_template(
        "dashboard.html",
        qr_image=qr_image,
        subject=subject,
        records=records
    )


@app.route("/teacher/logout")
def teacher_logout():
    session.pop("teacher_logged_in", None)
    return redirect(url_for("teacher"))


@app.route("/student", methods=["GET", "POST"])
def student():
    token = request.args.get("token", "")

    message = ""
    valid = False

    def check_token(value):
        return (
            bool(value)
            and value == active_qr.get("token")
            and datetime.now(timezone.utc)
            < active_qr.get(
                "expires",
                datetime.min.replace(tzinfo=timezone.utc)
            )
        )

    valid = check_token(token)

    if request.method == "POST":
        token = request.form.get("token", "")
        student_id = request.form.get("student_id", "").strip()
        student_name = request.form.get("student_name", "").strip()

        valid = check_token(token)

        if not valid:
            message = "QR code is invalid or expired. Scan the latest QR code."
        elif not student_id or not student_name:
            message = "Please enter your name and student ID."
        else:
            try:
                with get_db() as conn:
                    conn.execute("""
                        INSERT INTO attendance
                        (student_id, student_name, subject, token, recorded_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        student_id,
                        student_name,
                        active_qr["subject"],
                        token,
                        datetime.now(timezone.utc).isoformat()
                    ))

                message = "Attendance recorded successfully!"

            except sqlite3.IntegrityError:
                message = "Attendance is already recorded for this QR session."

        valid = check_token(token)

    subject = active_qr.get("subject", "") if valid else ""

    return render_template(
        "student.html",
        message=message,
        valid=bool(valid),
        token=token,
        subject=subject
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
