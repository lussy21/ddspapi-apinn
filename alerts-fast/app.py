import os
import requests
from flask import Flask, request, jsonify, send_from_directory
app = Flask(__name__, static_folder="public")
GATEWAY = os.getenv("FAST_GATEWAY_URL", "https://signal-gateway.onrender.com").rstrip("/")
FEED = os.getenv("FAST_FEED_URL", "https://signal-private-backend.onrender.com").rstrip("/")
@app.get("/")
def index():
    return send_from_directory("public", "index.html")
@app.get("/health")
def health():
    return jsonify(ok=True, service="alerts-fast", readOnly=True)
def forward(base, path, payload):
    try:
        response = requests.post(base + path, json=payload, timeout=(4, 28))
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid JSON type")
        return jsonify(data), response.status_code
    except (requests.RequestException, ValueError):
        return jsonify(ok=False, error="UPSTREAM_UNAVAILABLE"), 502
@app.post("/fast/login")
def login():
    code = str((request.get_json(silent=True) or {}).get("code") or "").strip()
    if not code or len(code) > 256:
        return jsonify(ok=False,error="INVALID_CODE"), 400
    return forward(GATEWAY, "/login-lite", {"code": code})
@app.post("/fast/alerts")
def alerts():
    token = str((request.get_json(silent=True) or {}).get("token") or "").strip()
    if not token or len(token) > 2048:
        return jsonify(ok=False,error="LOGIN_REQUIRED"), 401
    return forward(FEED, "/owner-lite-feed", {"token": token})
@app.after_request
def headers(response):
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
    return response
