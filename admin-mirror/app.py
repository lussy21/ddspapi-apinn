import os,time,threading,hmac,requests,re
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from datetime import datetime, timezone
from flask import Flask,request,jsonify,send_from_directory
app=Flask(__name__,static_folder="web")
ACCESS=os.getenv("MIRROR_ACCESS_CODE","")
SECRET=os.getenv("MIRROR_SESSION_SECRET","")
SOURCE=os.getenv("MIRROR_SOURCE_URL","")
SOURCE_CODE=os.getenv("MIRROR_SOURCE_ADMIN_CODE","")
# Only this independent service polls the original read-only Admin endpoint.
# Clients read a precomputed snapshot; they never trigger upstream work.
TTL=600
cache={"at":0,"data":None,"last_error":"WAITING_FOR_FIRST_SYNC","last_attempt":None}
lock=threading.Lock()
def refresh_snapshot():
    with lock:
        cache["last_attempt"]=datetime.now(timezone.utc).isoformat()
    if not SOURCE or not SOURCE_CODE:
        with lock: cache["last_error"]="SOURCE_NOT_CONFIGURED"
        return
    try:
        response=requests.post(SOURCE,data={"action":"adminSignals","adminCode":SOURCE_CODE},timeout=(4,80),allow_redirects=True)
        if response.status_code>=400: raise ValueError("SOURCE_HTTP_ERROR")
        try: raw=response.json()
        except ValueError: raise ValueError("SOURCE_NON_JSON")
        if not isinstance(raw,dict): raise ValueError("SOURCE_BAD_FORMAT")
        if not raw.get("ok"):
            # Only expose safe backend error categories; never any credentials or payload.
            reason=raw.get("error")
            # Relay only machine-readable error identifiers. Never forward free text or values.
            if isinstance(reason,str) and re.fullmatch(r"[A-Z][A-Z_]{2,48}",reason):
                raise ValueError("UPSTREAM_"+reason)
            raise ValueError("SOURCE_REJECTED")
        if not isinstance(raw.get("signals"),list): raise ValueError("SOURCE_MISSING_SIGNALS")
        projected=[dict(item) for item in raw["signals"] if isinstance(item,dict)]
        snapshot={"signals":projected,"updatedAt":raw.get("updatedAt"),"cachedAt":datetime.now(timezone.utc).isoformat()}
        with lock: cache.update(data=snapshot,at=time.monotonic(),last_error=None)
    except (requests.RequestException,ValueError) as exc:
        with lock: cache["last_error"]=str(exc) if isinstance(exc,ValueError) else "SOURCE_UNAVAILABLE"

def poll_loop():
    # A single gunicorn worker is configured for this small free service.
    while True:
        refresh_snapshot()
        time.sleep(TTL)

@app.before_request
def initialize_poller():
    global poller_started
    if not poller_started:
        with poller_start_lock:
            if not poller_started:
                threading.Thread(target=poll_loop,daemon=True,name="mirror-snapshot-poller").start()
                poller_started=True
poller_started=False
poller_start_lock=threading.Lock()
@app.get("/")
def index(): return send_from_directory("web","index.html")
@app.get("/<path:name>")
def asset(name):
    if name not in ("style.css","app.js"): return ("Not Found",404)
    return send_from_directory("web",name)
@app.get("/health")
def health():
    with lock: ready=cache["data"] is not None
    return jsonify(ok=True,service="admin-mirror",configured=bool(ACCESS and SECRET and SOURCE and SOURCE_CODE),snapshotReady=ready)
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
    with lock:
        data=cache["data"]
        error=cache["last_error"]
        attempted=cache["last_attempt"]
        age=max(0,int(time.monotonic()-cache["at"])) if data else None
    if data is None:
        return jsonify(ok=False,error=error or "SYNC_PENDING",lastAttempt=attempted),503
    return jsonify(ok=True,**data,fromCache=True,stale=bool(error),lastError=error,snapshotAgeSeconds=age,lastAttempt=attempted)
@app.after_request
def headers(r):
    r.headers["Cache-Control"]="no-store"
    r.headers["X-Content-Type-Options"]="nosniff"
    r.headers["Referrer-Policy"]="no-referrer"
    r.headers["Content-Security-Policy"]="default-src 'self';script-src 'self';style-src 'self';connect-src 'self';object-src 'none';frame-ancestors 'none'"
    return r
