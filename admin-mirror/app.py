import os,time,threading,hmac,requests
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from datetime import datetime, timezone
from flask import Flask,request,jsonify,send_from_directory
app=Flask(__name__,static_folder="web")
ACCESS=os.getenv("MIRROR_ACCESS_CODE","")
SECRET=os.getenv("MIRROR_SESSION_SECRET","")
SOURCE=os.getenv("MIRROR_SOURCE_URL","")
SOURCE_CODE=os.getenv("MIRROR_SOURCE_ADMIN_CODE","")
TTL=600
cache={"at":0,"data":None,"last_error":None}
lock=threading.Lock()
@app.get("/")
def index(): return send_from_directory("web","index.html")
@app.get("/<path:name>")
def asset(name):
    if name not in ("style.css","app.js"): return ("Not Found",404)
    return send_from_directory("web",name)
@app.get("/health")
def health(): return jsonify(ok=True,service="admin-mirror",configured=bool(ACCESS and SECRET and SOURCE and SOURCE_CODE))
def authorized():
    if not ACCESS or not SECRET: return False
    token=request.headers.get("Authorization","").removeprefix("Bearer ").strip()
    if not token:return False
    try:return URLSafeTimedSerializer(SECRET,salt="dtt-admin-mirror").loads(token,max_age=365*86400)=="mirror"
    except (BadSignature,SignatureExpired):return False
@app.post("/api/login")
def login():
    if not ACCESS or not SECRET:return jsonify(ok=False,error="LOGIN_NOT_CONFIGURED"),503
    code=str((request.get_json(silent=True) or {}).get("code") or "")
    if not hmac.compare_digest(code,ACCESS):return jsonify(ok=False,error="ACCESS_DENIED"),403
    return jsonify(ok=True,token=URLSafeTimedSerializer(SECRET,salt="dtt-admin-mirror").dumps("mirror"))
@app.post("/api/signals")
def signals():
    if not authorized(): return jsonify(ok=False,error="ACCESS_DENIED"),401
    if not SOURCE or not SOURCE_CODE: return jsonify(ok=False,error="SOURCE_NOT_CONFIGURED"),503
    now=time.monotonic()
    with lock:
        data=cache["data"]
        if data is not None and now-cache["at"]<TTL: return jsonify(ok=True,signals=data["signals"],updatedAt=data.get("updatedAt"),cachedAt=data["cachedAt"],fromCache=True)
        try:
            result=requests.post(SOURCE,data={"action":"adminSignals","adminCode":SOURCE_CODE},timeout=(4,28),allow_redirects=True)
            if result.status_code >= 400:
                return jsonify(ok=False,error="SOURCE_HTTP_ERROR",upstreamStatus=result.status_code),502
            try:
                raw=result.json()
            except ValueError:
                return jsonify(ok=False,error="SOURCE_NON_JSON"),502
            if not isinstance(raw,dict):
                return jsonify(ok=False,error="SOURCE_BAD_FORMAT"),502
            if not raw.get("ok"):
                # Avoid relaying arbitrary backend strings, secrets, or private data.
                return jsonify(ok=False,error="SOURCE_REJECTED"),502
            if not isinstance(raw.get("signals"),list):
                return jsonify(ok=False,error="SOURCE_MISSING_SIGNALS"),502
            # Read-only projection, retains computed scores and source attributes without recalculation.
            projected=[dict(s) for s in raw["signals"] if isinstance(s,dict)]
            data={"signals":projected,"updatedAt":raw.get("updatedAt"),"cachedAt":datetime.now(timezone.utc).isoformat()}
            cache.update(data=data,at=time.monotonic(),last_error=None)
            return jsonify(ok=True,**data,fromCache=False)
        except (requests.RequestException,ValueError):
            if data is not None: return jsonify(ok=True,**data,stale=True,lastError="SOURCE_UNAVAILABLE")
            return jsonify(ok=False,error="SOURCE_UNAVAILABLE"),502
@app.after_request
def headers(r):
    r.headers["Cache-Control"]="no-store"
    r.headers["X-Content-Type-Options"]="nosniff"
    r.headers["Referrer-Policy"]="no-referrer"
    r.headers["Content-Security-Policy"]="default-src 'self';script-src 'self';style-src 'self';connect-src 'self';object-src 'none';frame-ancestors 'none'"
    return r
