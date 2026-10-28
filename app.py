from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "attendance-demo-key-change-later"

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
        else:
            error = "Invalid username or password. Please try again."

    return render_template("teacher.html", error=error)

@app.route("/teacher/dashboard")
def teacher_dashboard():
    if not session.get("teacher_logged_in"):
        return redirect(url_for("teacher"))

    return """
        <h1>Teacher Dashboard</h1>
        <p>Welcome to SamruddhiAttendX!</p>
        <p>Teacher login successful.</p>
        <a href="/teacher/logout">Logout</a>
    """

@app.route("/teacher/logout")
def teacher_logout():
    session.pop("teacher_logged_in", None)
    return redirect(url_for("teacher"))

@app.route("/student")
def student():
    return render_template("student.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
