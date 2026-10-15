"""SharpVision personal read-only bridge for a private Google Sheet."""
import os
import hmac
import time
import secrets
import threading
import gzip
from datetime import datetime, timezone
from urllib.parse import urlparse
from flask import Flask, jsonify, request, session, send_from_directory, make_response
import requests

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.getenv("SV_SESSION_SECRET") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60*60*24*30,
    MAX_CONTENT_LENGTH=8192,
)
VIEW_PASSWORD = os.getenv("SV_VIEW_PASSWORD", "").strip()
FEED_URL = os.getenv("SV_FEED_URL", "").strip()
FEED_KEY = os.getenv("SV_FEED_KEY", "").strip()
CACHE_TTL = 540
# A slow Google Sheets read must never block a browser request.
# The cache holds last good data and a background worker refreshes it.
cache = {"time": 0.0, "payload": None, "refreshing": False, "last_attempt": 0.0, "last_error": None}
lock = threading.Lock()
failures = {}

def _private():
    return bool(VIEW_PASSWORD) and session.get("authenticated") is True

def _response(payload, status=200):
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store, private"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # The full Excel response is large; gzip helps mobile connections.
    if len(resp.get_data()) > 4096 and "gzip" in request.headers.get("Accept-Encoding", "").lower():
        resp.set_data(gzip.compress(resp.get_data(), compresslevel=4))
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Vary"] = "Accept-Encoding"
    return resp

@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    return resp

@app.get("/")
def index():
    resp = make_response(send_from_directory(os.path.dirname(__file__), "index.html"))
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.get("/app.js")
def app_script():
    resp = make_response(send_from_directory(os.path.dirname(__file__), "app.js", conditional=False))
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(os.path.dirname(__file__), "manifest.webmanifest")

@app.get("/icon.svg")
def icon():
    return send_from_directory(os.path.dirname(__file__), "icon.svg")

@app.get("/health")
def health():
    return _response({"ok": True, "configured": bool(VIEW_PASSWORD), "feedConfigured": bool(FEED_URL and FEED_KEY)})

@app.get("/api/session")
def current_session():
    return _response({"ok": True, "authenticated": _private(), "configured": bool(VIEW_PASSWORD)})

@app.post("/api/login")
def login():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    now = time.monotonic()
    record = failures.get(ip, [])
    record = [x for x in record if now - x < 600]
    failures[ip] = record
    if len(record) >= 8:
        return _response({"ok": False, "error": "too_many_attempts"}, 429)
    if not VIEW_PASSWORD:
        return _response({"ok": False, "error": "not_configured"}, 503)
    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    if not hmac.compare_digest(password.encode(), VIEW_PASSWORD.encode()):
        failures[ip].append(now)
        return _response({"ok": False, "error": "wrong_password"}, 401)
    failures.pop(ip, None)
    session.clear()
    session["authenticated"] = True
    session.permanent = True
    return _response({"ok": True})

@app.post("/api/logout")
def logout():
    session.clear()
    return _response({"ok": True})

def get_sheet_data():
    if not FEED_URL or not FEED_KEY:
        return {"ok": False, "state": "not_connected", "rows": []}
    url = urlparse(FEED_URL)
    if url.scheme != "https" or url.hostname not in {"script.google.com", "script.googleusercontent.com"}:
        raise ValueError("FEED_URL must be a Google Apps Script HTTPS URL")
    app.logger.warning("Sheet feed fetch started")
    resp = requests.get(FEED_URL, params={"key": FEED_KEY}, timeout=(5, 18), allow_redirects=True)
    app.logger.warning("Sheet feed HTTP response received status=%s length=%s", resp.status_code, len(resp.content))
    destination = urlparse(resp.url).hostname or "unknown"
    media = resp.headers.get("Content-Type", "").split(";")[0].lower()
    app.logger.info("Feed response status=%s host=%s mime=%s redirects=%s bytes=%s",
        resp.status_code, destination, media, len(resp.history), len(resp.content))
    resp.raise_for_status()
    if len(resp.content) > 4_500_000:
        raise ValueError("FEED_TOO_LARGE")
    try:
        val = resp.json()
    except ValueError:
        # Only log safe metadata; never log response body, token or query string.
        if destination in {"accounts.google.com", "accounts.googleusercontent.com"}:
            reason = "GOOGLE_AUTH_REQUIRED"
        elif destination == "script.google.com" and "html" in media:
            reason = "GOOGLE_SCRIPT_HTML"
        elif "html" in media:
            reason = "GOOGLE_HTML_RESPONSE"
        else:
            reason = "FEED_NOT_JSON"
        app.logger.warning("Feed format error: %s", reason)
        raise ValueError(reason)
    if not isinstance(val, dict):
        raise ValueError("FEED_INVALID_OBJECT")
    if val.get("ok") is not True:
        code = "".join(ch for ch in str(val.get("error") or "UNKNOWN") if ch.isascii() and (ch.isupper() or ch == "_"))[:45]
        try:
            status = int(val.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        app.logger.warning("Feed returned upstream error=%s http_status=%s", code, status)
        raise ValueError("FEED_" + code)
    if not isinstance(val.get("rows"), list):
        raise ValueError("FEED_MISSING_ROWS")
    out=[]
    out_formats=[]
    source_formats=val.get("formats")
    # Accept only source-cell color pairs, not arbitrary CSS or HTML.
    color_columns={"10","11","12","13","14","15","20","21","22","23","24"}
    for i, row in enumerate(val["rows"][:4500]):
        if not isinstance(row, list) or len(row) < 25:
            continue
        if not str(row[1]).strip() or not str(row[2]).strip() or str(row[3]).strip() not in ("H","A"):
            continue
        out.append(row[:82])
        src=source_formats[i] if isinstance(source_formats,list) and i<len(source_formats) else None
        clean={}
        if isinstance(src,dict):
            for k,v in src.items():
                if k not in color_columns or not isinstance(v,list):
                    continue
                if len(v)>=2 and all(isinstance(c,str) and (not c or (len(c)==7 and c[0]=="#" and all(x in "0123456789abcdefABCDEF" for x in c[1:]))) for c in v[:2]):
                    clean[k]=v[:2]
        out_formats.append(clean)
    return {
        "ok": True, "state":"live", "rows":out,
        "formats":out_formats,
        "formatError": val.get("formatError") if isinstance(val.get("formatError"),str) else None,
        "sourceUpdatedAt":val.get("updatedAt"),
        "serverFetchedAt":datetime.now(timezone.utc).isoformat(),
        "count":len(out)
    }

def _refresh_sheet_in_background():
    """Refresh only in a worker. Never hold the mutex while making a network call."""
    started = time.monotonic()
    try:
        payload = get_sheet_data()
        with lock:
            if payload.get("ok"):
                cache["payload"] = payload
                cache["time"] = time.monotonic()
                cache["last_error"] = None
            else:
                cache["last_error"] = "FEED_NOT_CONFIGURED"
        app.logger.warning("Feed refresh completed: ok=%s rows=%s duration_s=%.1f",
            payload.get("ok"), payload.get("count", 0), time.monotonic() - started)
    except Exception as exc:
        error_code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        if error_code not in {"GOOGLE_AUTH_REQUIRED", "GOOGLE_SCRIPT_HTML",
                "GOOGLE_HTML_RESPONSE", "FEED_NOT_JSON", "FEED_TOO_LARGE",
                "FEED_INVALID_OBJECT", "FEED_UNAUTHORIZED", "FEED_SHEET_NOT_FOUND",
                "FEED_SHEETS_API_ERROR", "FEED_SHEET_READ_FAILED",
                "FEED_MISSING_ROWS", "ReadTimeout", "ConnectTimeout"}:
            error_code = type(exc).__name__
        with lock:
            cache["last_error"] = error_code
        app.logger.warning("Background feed refresh failed after %.1fs: %s",
            time.monotonic() - started, error_code)
    finally:
        with lock:
            cache["refreshing"] = False

def _ensure_refresh():
    if not FEED_URL or not FEED_KEY:
        return False
    now = time.monotonic()
    with lock:
        if cache["refreshing"]:
            return True
        # Throttle retries if Apps Script / Sheets is slow or inaccessible.
        if now - cache["last_attempt"] < 15:
            return False
        cache["last_attempt"] = now
        cache["refreshing"] = True
    app.logger.warning("Sheet feed refresh worker launched")
    worker = threading.Thread(target=_refresh_sheet_in_background, daemon=True)
    worker.start()
    return True

# Do not start background threads at module import: Gunicorn may import this
# module in its master before forking workers. Forking while refreshing=True
# strands child workers permanently in a "loading" state.
# Let the first /api/matches request start the refresh inside the web worker.
@app.get("/api/matches")
def matches():
    if not _private():
        return _response({"ok": False, "error": "login_required"}, 401)
    with lock:
        payload = cache["payload"]
        age = time.monotonic() - cache["time"]
        refreshing = cache["refreshing"]
        error = cache["last_error"]
    if payload and payload.get("ok"):
        if age >= CACHE_TTL and not refreshing:
            _ensure_refresh()
        out = dict(payload)
        out["cached"] = True
        if age >= CACHE_TTL:
            out["stale"] = True
            out["state"] = "stale"
        return _response(out)
    if not FEED_URL or not FEED_KEY:
        return _response({"ok": False, "state": "not_connected", "rows": []})
    if not refreshing and not error:
        _ensure_refresh()
    if error and not refreshing:
        # Explicit error, never a fake "zero matches" or a hanging request.
        _ensure_refresh()
        return _response({"ok": False, "state": "feed_error",
            "diagnostic": error, "rows": [],
            "message": "Δεν ολοκληρώθηκε η ενημέρωση του Excel."}, 502)
    return _response({"ok": False, "state": "loading", "rows": [],
        "retryAfterSeconds": 3, "message": "Γίνεται ασφαλής ανάκτηση του Excel."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")))
