import os
import requests
from flask import Flask, request, jsonify, make_response, send_from_directory

app = Flask(__name__)

APPS_SCRIPT_URL = os.environ.get(
    "APPS_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycbwRUaBGKeUQm-L2P2mar42FXVdHAB1mNGkxCscnMMDAk_BDZXq2ADZyXo7YZI7NH89Z/exec",
)
APP_ORIGIN = os.environ.get("APP_ORIGIN", "https://match-alerts-private.onrender.com")
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = APP_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS, GET"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.after_request
def add_headers(resp):
    return cors(resp)


@app.get("/health")
def health():
    return jsonify(ok=True, service="match-alerts-api")


@app.get("/admin")
def admin_page():
    return send_from_directory(APP_DIR, "admin.html")


@app.route("/api", methods=["POST", "OPTIONS"])
def api():
    if request.method == "OPTIONS":
        return make_response("", 204)

    origin = request.headers.get("Origin", "")
    same_origin = request.host_url.rstrip("/")
    if origin and origin not in {APP_ORIGIN, same_origin}:
        return jsonify(ok=False, error="ORIGIN_DENIED"), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict(flat=True)

    # The proxy only forwards the Match Alerts action payload.
    payload.pop("bridge", None)
    payload.pop("requestId", None)

    try:
        upstream = requests.post(
            APPS_SCRIPT_URL,
            data={k: "" if v is None else str(v) for k, v in payload.items()},
            timeout=(4, 10),
            allow_redirects=True,
        )
    except requests.RequestException:
        return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502

    try:
        data = upstream.json()
    except ValueError:
        return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

    return jsonify(data), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
