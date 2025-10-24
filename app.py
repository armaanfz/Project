from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/introduction")
def introduction():
    return render_template("introduction.html")

@app.route("/samples")
def samples():
    return render_template("samples.html")

if __name__ == "__main__":
    app.run(debug=True)
