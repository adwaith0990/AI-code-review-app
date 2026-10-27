import json
import os

from flask import Flask, Response, render_template, request

from reviewer import review, to_txt

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_100_000


@app.route("/", methods=["GET", "POST"])
def index():
    result = error = None
    code = ""
    if request.method == "POST":
        f = request.files.get("file")
        if f and f.filename:
            if not f.filename.lower().endswith(".py"):
                error = "Only .py files are supported."
            else:
                try:
                    code = f.read().decode("utf-8")
                except UnicodeDecodeError:
                    error = "File must be UTF-8 encoded."
        else:
            code = request.form.get("code", "")
        if not error:
            r = review(code)
            error, result = r.get("error"), (None if r.get("error") else r)
    return render_template("index.html", result=result, error=error, code=code,
                           result_json=json.dumps(result) if result else "")


@app.post("/download/<fmt>")
def download(fmt):
    r = json.loads(request.form["result"])
    if fmt == "json":
        return Response(json.dumps(r, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": "attachment; filename=review.json"})
    return Response(to_txt(r), mimetype="text/plain",
                    headers={"Content-Disposition": "attachment; filename=review.txt"})


@app.errorhandler(413)
def too_large(_):
    return render_template("index.html", error="File is larger than 1 MB.",
                           result=None, code="", result_json=""), 413


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
