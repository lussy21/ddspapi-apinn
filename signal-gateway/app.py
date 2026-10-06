import os, hmac, hashlib, base64, time
from flask import Flask, request, jsonify

app = Flask(__name__)
ACCESS_CODES={x.strip() for x in os.environ.get("SIGNAL_ACCESS_CODES","").split(",") if x.strip()}
AUTH_SECRET=os.environ.get("SIGNAL_AUTH_SECRET","").strip()
ALLOWED={x.strip() for x in os.environ.get("SIGNAL_ALLOWED_ORIGINS","").split(",") if x.strip()}

def cors(resp):
    origin=request.headers.get("Origin","")
    if origin in ALLOWED:
        resp.headers["Access-Control-Allow-Origin"]=origin
    resp.headers["Vary"]="Origin"
    resp.headers["Access-Control-Allow-Headers"]="Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"]="GET, POST, OPTIONS"
    resp.headers["Cache-Control"]="no-store"
    return resp

@app.after_request
def headers(resp): return cors(resp)

@app.route("/<path:path>",methods=["OPTIONS"])
@app.route("/",methods=["OPTIONS"])
def options(path=""): return ("",204)

def make_token(code):
    exp=int(time.time())+30*24*60*60
    body=f"{code}:{exp}"
    sig=hmac.new(AUTH_SECRET.encode(),body.encode(),hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}:{sig}".encode()).decode().rstrip("=")

def valid_token(token):
    try:
        raw=base64.urlsafe_b64decode(token+"="*(-len(token)%4)).decode()
        code,exp,sig=raw.rsplit(":",2)
        body=f"{code}:{exp}"
        good=hmac.new(AUTH_SECRET.encode(),body.encode(),hashlib.sha256).hexdigest()
        return code in ACCESS_CODES and int(exp)>=int(time.time()) and hmac.compare_digest(sig,good)
    except Exception:
        return False

@app.get("/health")
def health(): return jsonify(ok=True,service="signal-gateway")

@app.post("/login")
def login():
    data=request.get_json(silent=True) or {}
    code=str(data.get("code") or "").strip()
    if not AUTH_SECRET:
        return jsonify(ok=False,error="NOT_CONFIGURED"),500
    if code not in ACCESS_CODES:
        return jsonify(ok=False,error="INVALID_CODE"),401
    return jsonify(ok=True,token=make_token(code))

@app.post("/check")
def check():
    data=request.get_json(silent=True) or {}
    ok=valid_token(str(data.get("token") or ""))
    return jsonify(ok=ok),(200 if ok else 401)
