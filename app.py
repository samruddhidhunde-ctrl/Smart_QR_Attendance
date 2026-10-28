from flask import Flask, render_template, request, redirect, url_for, session
import qrcode
import io
import base64
import secrets
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "demo-key-change-before-production"

# Store the active QR session for this demo
active_qr = {}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/teacher", methods=["GET", "POST"])
def teacher():
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "")
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
                "expires": datetime.utcnow() + timedelta(minutes=5)
            })

            qr_data = url_for(
                "student",
                token=token,
                _external=True
            )

            qr = qrcode.make(qr_data)
            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")
            qr_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return render_template(
        "dashboard.html",
        qr_image=qr_image,
        subject=subject
    )

@app.route("/teacher/logout")
def teacher_logout():
    session.pop("teacher_logged_in", None)
    return redirect(url_for("teacher"))

@app.route("/student")
def student():
    token = request.args.get("token", "")
    message = ""

    if token:
        if (
            token == active_qr.get("token")
            and datetime.utcnow() < active_qr.get("expires", datetime.min)
        ):
            message = "Valid QR code for " + active_qr["subject"]
        else:
            message = "This QR code is invalid or has expired."

    return render_template("student.html", message=message)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
