"""
FloraTrack - Web App (Flask)
----------------------------
Plant identification (Pl@ntNet) for the FloraTrack stock app. Stock records are
kept on each phone by the web page (templates/index.html); this server only
identifies photos and fetches short descriptions.

The Pl@ntNet API key lives ONLY on the server (in the .env file or in an
environment variable). It is never sent to the browser.

SETUP:
    py -m pip install -r requirements.txt
    Put your key in .env:   PLANTNET_API_KEY=your_key_here

RUN:
    py app.py   ->  http://127.0.0.1:5000
"""

import os
import time
from collections import defaultdict, deque

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

load_dotenv()  # reads .env next to this file

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # reject uploads over 8 MB

PROJECT = "all"
API_URL = f"https://my-api.plantnet.org/v2/identify/{PROJECT}"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
ALLOWED_ORGANS = {"auto", "leaf", "flower", "fruit", "bark"}
API_KEY = os.environ.get("PLANTNET_API_KEY", "").strip()

if not API_KEY:
    print("WARNING: PLANTNET_API_KEY is not set. Add it to your .env file.")

# Simple per-IP rate limit so strangers can't burn through your API quota.
RATE_LIMIT = 10      # requests
RATE_WINDOW = 60     # seconds
_hits = defaultdict(deque)


def is_rate_limited(ip):
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory("static", "service-worker.js", mimetype="application/javascript")


def fetch_plant_description(scientific_name):
    try:
        url = WIKIPEDIA_SUMMARY_URL.format(scientific_name.replace(" ", "_"))
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        return resp.json().get("extract")
    except Exception:
        return None


@app.route("/")
def index():
    return render_template("index.html")  # no key is passed to the page


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "Image is too large (max 8 MB)."}), 413


@app.errorhandler(Exception)
def handle_unexpected(e):
    """Always answer with JSON so the page can show a real message, never an empty reply."""
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    app.logger.exception("Unexpected error")
    return jsonify({"error": "Unexpected server error. Check the terminal running app.py."}), 500


@app.route("/identify", methods=["POST"])
def identify():
    if not API_KEY:
        return jsonify({"error": "Server is not configured with an API key."}), 500

    if is_rate_limited(request.remote_addr):
        return jsonify({"error": "Too many requests. Please wait a minute and try again."}), 429

    image = request.files.get("image")
    if not image:
        return jsonify({"error": "No image received"}), 400

    try:
        files = [("images", (image.filename or "photo.jpg", image.stream, image.mimetype))]
        organ = request.form.get("organ", "auto")
        if organ not in ALLOWED_ORGANS:
            organ = "auto"
        data = [("organs", organ)]
        response = requests.post(API_URL, files=files, data=data,
                                 params={"api-key": API_KEY}, timeout=25)
        if response.status_code == 404:  # Pl@ntNet uses 404 for "no species found"
            return jsonify({"matches": [], "description": None})
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.HTTPError as e:
        # Don't echo the raw error: request errors can contain the URL (and the key).
        return jsonify({"error": f"Pl@ntNet API error ({e.response.status_code})."}), 502
    except Exception:
        return jsonify({"error": "Could not reach the identification service."}), 500

    matches = []
    for s in result.get("results", [])[:5]:
        species = s["species"]
        matches.append({
            "scientific_name": species.get("scientificNameWithoutAuthor", "Unknown"),
            "common_names": species.get("commonNames", []),
            "family": (species.get("family") or {}).get("scientificNameWithoutAuthor"),
            "genus": (species.get("genus") or {}).get("scientificNameWithoutAuthor"),
            "confidence": round(s.get("score", 0) * 100, 1),
        })

    description = fetch_plant_description(matches[0]["scientific_name"]) if matches else None
    return jsonify({"matches": matches, "description": description})


if __name__ == "__main__":
    # debug=True must never be used on a public server; it's opt-in here.
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
