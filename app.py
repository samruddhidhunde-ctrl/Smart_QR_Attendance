from flask import Flask, render_template, request

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/teacher")
def teacher():
    return render_template("teacher.html")

@app.route("/student")
def student():
    return render_template("student.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
