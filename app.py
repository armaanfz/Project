import os
import subprocess
from flask import Flask, render_template, request

app = Flask(__name__)

# Generate a new token with: python3 -c "import secrets; print(secrets.token_hex(32))"
SHUTDOWN_TOKEN = "replace-this-with-a-strong-secret"

@app.route("/")
def index():
    return render_template("index.html", shutdown_token=SHUTDOWN_TOKEN)

@app.route("/shutdown", methods=["POST"])
def shutdown():
    token = request.headers.get("X-Shutdown-Token")
    if token != SHUTDOWN_TOKEN:
        return "Forbidden", 403
    subprocess.Popen(["sudo", "shutdown", "-h", "now"])
    return "Shutting down...", 200

@app.route("/home-tab-content")
def home_tab_content():
    return render_template("home_tab_content.html")

@app.route("/samples")
def samples():
    return render_template("samples.html")

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug)
