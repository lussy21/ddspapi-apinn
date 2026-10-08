import os,time,threading,hmac,requests
from datetime import datetime, timezone
from flask import Flask,request,jsonify,send_from_directory
app=Flask(__name__,static_folder="web")
ACCESS=os.getenv("MIRROR_ACCESS_CODE","")
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
def health(): return jsonify(ok=True,service="admin-mirror",configured=bool(ACCESS and SOURCE and SOURCE_CODE))
@app.post("/api/signals")
def signals():
    code=str((request.get_json(silent=True) or {}).get("code") or "")
    if not ACCESS: return jsonify(ok=False,error="MIRROR_LOGIN_NOT_CONFIGURED"),503
    if not hmac.compare_digest(code,ACCESS): return jsonify(ok=False,error="ACCESS_DENIED"),403
    if not SOURCE or not SOURCE_CODE: return jsonify(ok=False,error="SOURCE_NOT_CONFIGURED"),503
    now=time.monotonic()
    with lock:
        data=cache["data"]
        if data is not None and now-cache["at"]<TTL: return jsonify(ok=True,signals=data["signals"],updatedAt=data.get("updatedAt"),cachedAt=data["cachedAt"],fromCache=True)
        try:
            result=requests.post(SOURCE,data={"action":"adminSignals","adminCode":SOURCE_CODE},timeout=(4,28),allow_redirects=True)
            result.raise_for_status()
            raw=result.json()
            if not isinstance(raw,dict) or not raw.get("ok") or not isinstance(raw.get("signals"),list): raise ValueError("BAD_SOURCE_RESPONSE")
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
