import os
import requests
from flask import Flask, request, jsonify, make_response

app = Flask(__name__)

APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL", "").strip()
SIGNAL_ADMIN_CODE = os.environ.get("SIGNAL_ADMIN_CODE", "").strip()
SIGNAL_GATEWAY_URL = os.environ.get("SIGNAL_GATEWAY_URL", "https://signal-gateway.onrender.com").strip()
ALLOWED_ORIGINS = {
    x.strip() for x in os.environ.get("SIGNAL_ALLOWED_ORIGINS", "").split(",") if x.strip()
}

def cors(resp):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS, GET"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.after_request
def add_headers(resp):
    return cors(resp)

@app.get("/health")
def health():
    return jsonify(ok=True, service="signal-private-backend")

@app.post("/owner-feed")
def owner_feed():
    origin = request.headers.get("Origin", "")
    if origin and origin not in ALLOWED_ORIGINS:
        return jsonify(ok=False, error="ORIGIN_DENIED"), 403

    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "").strip()
    if not token:
        return jsonify(ok=False, error="LOGIN_REQUIRED"), 401

    try:
        check = requests.post(
            SIGNAL_GATEWAY_URL + "/check",
            json={"token": token},
            timeout=(3, 8),
        )
        if check.status_code != 200 or not check.json().get("ok"):
            return jsonify(ok=False, error="INVALID_SESSION"), 401
    except Exception:
        return jsonify(ok=False, error="AUTH_UNREACHABLE"), 502

    if not APPS_SCRIPT_URL or not SIGNAL_ADMIN_CODE:
        return jsonify(ok=False, error="OWNER_FEED_NOT_CONFIGURED"), 503

    try:
        upstream = requests.post(
            APPS_SCRIPT_URL,
            data={"action": "adminSignals", "adminCode": SIGNAL_ADMIN_CODE},
            timeout=(4, 35),
            allow_redirects=True,
        )
        data = upstream.json()
    except requests.RequestException:
        return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
    except ValueError:
        return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

    if not data.get("ok"):
        return jsonify(data), 200

    alerts = []
    for s in data.get("signals") or []:
        if str(s.get("publicationStatus") or "") == "withdrawn":
            continue
        alerts.append({
            "league": s.get("league") or "",
            "home": s.get("home") or "",
            "away": s.get("away") or "",
            "favoriteSide": s.get("favoriteSide") or "",
            "alert": s.get("publicAlert") or s.get("internalAlert") or "",
            "internalAlert": s.get("internalAlert") or "",
            "publicSymbol": s.get("publicSymbol") or "",
            "publicLevel": s.get("publicLevel") or 0,
            "rating": s.get("rating") or "",
            "leagueRecord": s.get("leagueRecord") or "",
            "allStatsRecord": s.get("allStatsRecord") or "",
            "kickoff": s.get("kickoff") or "",
            "selectionId": s.get("selectionId") or "",
            "controlId": s.get("controlId") or "",
            "customerPick": s.get("customerPick") or "",
            "customerTeam": s.get("customerTeam") or "",
            "played": False,
        })

    return jsonify(
        ok=True,
        username="Signal",
        alerts=alerts,
        slips=[],
        count=len(alerts),
        updatedAt=data.get("updatedAt"),
    ), 200


@app.route("/api", methods=["POST", "OPTIONS"])
def api():
    if request.method == "OPTIONS":
        return make_response("", 204)

    origin = request.headers.get("Origin", "")
    if origin and origin not in ALLOWED_ORIGINS:
        return jsonify(ok=False, error="ORIGIN_DENIED"), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict(flat=True)

    if not APPS_SCRIPT_URL:
        return jsonify(ok=False, error="BACKEND_NOT_CONFIGURED"), 500

    try:
        upstream = requests.post(
            APPS_SCRIPT_URL,
            data={k: "" if v is None else str(v) for k, v in payload.items()},
            timeout=(4, 35),
            allow_redirects=True,
        )
        data = upstream.json()
    except requests.RequestException:
        return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
    except ValueError:
        return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502

    return jsonify(data), 200
