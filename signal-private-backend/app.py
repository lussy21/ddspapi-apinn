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



@app.post("/owner-push-subscribe")
def owner_push_subscribe():
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "").strip()
    endpoint = str(payload.get("endpoint") or "").strip()
    p256dh = str(payload.get("p256dh") or "").strip()
    auth_key = str(payload.get("auth") or "").strip()
    if not token or not endpoint or not p256dh or not auth_key:
        return jsonify(ok=False, error="BAD_PUSH_SUBSCRIPTION"), 400

    try:
        check = requests.post(
            SIGNAL_GATEWAY_URL.rstrip("/") + "/check",
            json={"token": token}, timeout=(4, 10)
        ).json()
    except Exception:
        return jsonify(ok=False, error="AUTH_UNREACHABLE"), 502
    if not check.get("ok"):
        return jsonify(ok=False, error="ACCESS_DENIED"), 403

    try:
        upstream = requests.post(
            APPS_SCRIPT_URL,
            data={
                "action": "adminOwnerPushSubscribe",
                "adminCode": SIGNAL_ADMIN_CODE,
                "endpoint": endpoint,
                "p256dh": p256dh,
                "auth": auth_key,
            },
            timeout=(4, 15), allow_redirects=True
        )
        data = upstream.json()
    except requests.RequestException:
        return jsonify(ok=False, error="BACKEND_UNREACHABLE"), 502
    except Exception:
        return jsonify(ok=False, error="BACKEND_BAD_RESPONSE"), 502
    return jsonify(data), 200

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
        levels_upstream = requests.post(
            APPS_SCRIPT_URL,
            data={"action": "adminAlertLevels", "adminCode": SIGNAL_ADMIN_CODE},
            timeout=(4, 35),
            allow_redirects=True,
        )
        levels_data = levels_upstream.json()
        regional_upstream = requests.post(
            APPS_SCRIPT_URL,
            data={"action": "adminSignalStats", "adminCode": SIGNAL_ADMIN_CODE},
            timeout=(4, 35),
            allow_redirects=True,
        )
        regional_data = regional_upstream.json()
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
            "favoriteTeam": s.get("favoriteTeam") or "",
            "alert": s.get("publicAlert") or s.get("internalAlert") or "",
            "internalAlert": s.get("internalAlert") or "",
            "publicAlert": s.get("publicAlert") or "",
            "publicSymbol": s.get("publicSymbol") or "",
            "publicLevel": s.get("publicLevel") or 0,
            "levelScore": s.get("levelScore") or 0,
            "levelWins": s.get("levelWins") or 0,
            "levelTotal": s.get("levelTotal") or 0,
            "levelNextReview": s.get("levelNextReview") or "",
            "reviewState": s.get("reviewState") or "",
            "suggestedSymbol": s.get("suggestedSymbol") or "",
            "rating": s.get("rating") or "",
            "leagueRecord": s.get("leagueRecord") or "",
            "allStatsRecord": s.get("allStatsRecord") or "",
            "kickoff": s.get("kickoff") or "",
            "selectionId": s.get("selectionId") or "",
            "controlId": s.get("controlId") or "",
            "customerPick": s.get("customerPick") or "",
            "customerTeam": s.get("customerTeam") or "",
            "customerOdds": s.get("customerOdds") or 0,
            "publicationStatus": s.get("publicationStatus") or "waiting",
            "published": bool(s.get("published")),
            "canEdit": bool(s.get("canEdit")),
            "played": False,
        })

    symbol_stats = {"🔷": {"wins": 0, "total": 0}, "💎": {"wins": 0, "total": 0}, "👑": {"wins": 0, "total": 0},
                    "🎯": {"wins": 0, "total": 0}, "⚡": {"wins": 0, "total": 0}, "💣": {"wins": 0, "total": 0}}
    if isinstance(levels_data, dict) and levels_data.get("ok"):
        for item in levels_data.get("levels") or []:
            symbol = str(item.get("symbol") or "").strip()
            if symbol not in symbol_stats:
                continue
            symbol_stats[symbol]["wins"] += int(item.get("wins") or 0)
            symbol_stats[symbol]["total"] += int(item.get("total") or 0)

    return jsonify(
        ok=True,
        username="Signal",
        alerts=alerts,
        slips=[],
        count=len(alerts),
        symbolStats=symbol_stats,
        regionalSymbolStats=(regional_data.get("regions") if isinstance(regional_data, dict) and regional_data.get("ok") else {}),
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
