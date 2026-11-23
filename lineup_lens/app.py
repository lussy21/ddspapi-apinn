"""Lineup Lens — private football lineups and seasonal starts. Independent from SharpVision."""
import json, os, re, secrets, sqlite3, threading, time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from flask import Flask, jsonify, render_template, request, Response

app=Flask(__name__)
BASE="https://api.soccer-data.co/v1"
KEY=os.getenv("SOCCER_DATA_KEY","").strip()
PASS=os.getenv("APP_ACCESS_PASS","")
DB=os.getenv("LINEUP_DB_PATH","/tmp/lineup_lens.sqlite3")
LIMIT=int(os.getenv("MAX_DAY_CALLS","46"))
ID=re.compile(r"^(match|team|player|season|competition)_[A-Za-z0-9]{5,32}$")
lock=threading.Lock()
last_call=0.0
session=requests.Session()

@app.before_request
def authentication():
    if PASS:
        received=request.authorization.password if request.authorization else ""
        if not secrets.compare_digest(received or "",PASS):
            return Response("Login required",401,{"WWW-Authenticate":'Basic realm="Lineup Lens"'})

class Problem(Exception):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status

@app.errorhandler(Problem)
def problem_handler(e):
    return jsonify(error=str(e)),e.status

@contextmanager
def database():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB,timeout=20)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY,value TEXT NOT NULL,expires REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY,calls INTEGER,remaining INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS watch (match_id TEXT PRIMARY KEY,kickoff TEXT,label TEXT,last_check REAL DEFAULT 0,status TEXT DEFAULT 'watching')")
    conn.commit()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def valid(s,kind):
    if not isinstance(s,str) or not ID.fullmatch(s) or not s.startswith(kind+"_"):
        raise Problem("Μη έγκυρο ID.")
    return s

def today():
    return datetime.now(timezone.utc).date().isoformat()

def cache_get(k):
    with database() as c:
        r=c.execute("SELECT value FROM cache WHERE key=? AND expires>?",(k,time.time())).fetchone()
        return json.loads(r["value"]) if r else None

def cache_put(k,v,ttl):
    with database() as c:
        c.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",(k,json.dumps(v,ensure_ascii=False),time.time()+ttl))

def usage():
    with database() as c:
        r=c.execute("SELECT calls,remaining FROM usage WHERE day=?",(today(),)).fetchone()
    return {"calls":r["calls"] if r else 0,"remote_remaining":r["remaining"] if r else None,"local_limit":LIMIT}

def api(path,params=None,ttl=900,allow404=False):
    global last_call
    k="api:"+json.dumps([path,sorted((params or {}).items())],ensure_ascii=False)
    found=cache_get(k)
    if found is not None:
        return found["data"]
    if not KEY:
        raise Problem("Δεν έχει ρυθμιστεί το Soccer Data API key.",503)
    with lock:
        found=cache_get(k)
        if found is not None: return found["data"]
        u=usage()
        if u["calls"]>=LIMIT or u["remote_remaining"]==0:
            raise Problem("Το ημερήσιο όριο κλήσεων εξαντλήθηκε.",429)
        wait=max(0,6.2-(time.monotonic()-last_call))
        if wait: time.sleep(wait)
        try:
            r=session.get(BASE+path,params=params,headers={"X-Api-Key":KEY},timeout=16)
        except requests.RequestException:
            raise Problem("Αδυναμία σύνδεσης με Soccer Data.",502)
        last_call=time.monotonic()
        remaining=r.headers.get("X-Daily-Quota-Remaining")
        with database() as c:
            c.execute("INSERT INTO usage (day,calls,remaining) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET calls=calls+1,remaining=excluded.remaining",(today(),1,int(remaining) if remaining and remaining.isdigit() else None))
        if r.status_code==429: raise Problem("Ο πάροχος επέστρεψε όριο κλήσεων.",429)
        if r.status_code==404 and allow404:
            cache_put(k,{"data":None},240)
            return None
        if not r.ok: raise Problem("Soccer Data HTTP "+str(r.status_code),502)
        try: data=r.json()["data"]
        except (ValueError,TypeError,KeyError): raise Problem("Μη αναγνωρίσιμη απάντηση από Soccer Data.",502)
        cache_put(k,{"data":data},ttl)
        return data

def match(mid):
    return api("/matches/"+valid(mid,"match"),ttl=18000)

def lineup_raw(mid):
    valid(mid,"match")
    return api("/matches/"+mid+"/lineups",ttl=240,allow404=True)

def before_kickoff(m):
    try: return datetime.now(timezone.utc)<datetime.fromisoformat(m["utc_date"].replace("Z","+00:00"))
    except (ValueError,KeyError,TypeError): return False

def team_snap(mid,m,tid):
    valid(tid,"team")
    k="team-snapshot:"+mid+":"+tid
    saved=cache_get(k)
    if saved is not None: return saved.get("played")
    if not before_kickoff(m): return None
    sid=valid(m.get("season_id"),"season")
    d=api("/teams/"+tid+"/stats",{"season_id":sid},ttl=900,allow404=True)
    n=d.get("matches_played") if isinstance(d,dict) else None
    value=n if isinstance(n,int) and n>=0 else None
    cache_put(k,{"played":value},365*86400)
    return value

def player_snap(mid,m,pid):
    valid(pid,"player")
    k="player-snapshot:"+mid+":"+pid
    saved=cache_get(k)
    if saved is not None: return saved
    if not before_kickoff(m): raise Problem("Ο αγώνας έχει ξεκινήσει, δεν δημιουργούμε αναδρομικό snapshot.",409)
    sid=valid(m.get("season_id"),"season")
    cid=valid(m.get("competition_id"),"competition")
    d=api("/players/"+pid+"/stats",{"season_id":sid,"competition_id":cid},ttl=900,allow404=True)
    n=d.get("starts") if isinstance(d,dict) else None
    value=n if isinstance(n,int) and n>=0 else None
    snapshot={"player_id":pid,"starts":value,"source":"Soccer Data"}
    cache_put(k,snapshot,365*86400)
    return snapshot

def sheet(mid):
    m=match(mid)
    s=lineup_raw(mid)
    if not s or not isinstance(s,dict):
        return {"ready":False,"confirmed":False,"kickoff":m.get("utc_date"),"message":"Δεν έχει ανακοινωθεί ενδεκάδα."}
    out=[]
    for side in ("home","away"):
        part=s.get(side) or {}
        mpart=m.get(side+"_team") or {}
        tid=part.get("id") or mpart.get("id")
        ts=cache_get("team-snapshot:"+mid+":"+str(tid))
        players=[]
        for p in part.get("starting_xi") or []:
            ps=cache_get("player-snapshot:"+mid+":"+str(p.get("id")))
            players.append({"id":p.get("id"),"name":p.get("name"),"number":p.get("jersey_number"),"position":p.get("position"),"starts":ps.get("starts") if isinstance(ps,dict) else None})
        out.append({"id":tid,"name":part.get("name") or mpart.get("name") or "Ομάδα","formation":part.get("formation") or "","played":ts.get("played") if isinstance(ts,dict) else None,"starting_xi":players})
    return {"ready":True,"confirmed":bool(s.get("confirmed")) and s.get("type") in ("team_sheet","played"),"type":s.get("type"),"kickoff":m.get("utc_date"),"home":out[0],"away":out[1]}

@app.get("/")
def index(): return render_template("index.html")

@app.get("/health")
def health(): return jsonify(ok=True)

@app.get("/api/status")
def status(): return jsonify(configured=bool(KEY),usage=usage(),scheduler_enabled=os.getenv("ENABLE_SCHEDULER")=="1")

@app.get("/api/matches")
def matches():
    d=request.args.get("date","")
    try:
        day=datetime.strptime(d,"%Y-%m-%d")
        off=day.replace(tzinfo=ZoneInfo("Europe/Athens")).utcoffset()
        hours=int(off.total_seconds()//3600)
        tz=("{:+03d}:00".format(hours))
    except (TypeError,ValueError):
        raise Problem("Μη έγκυρη ημερομηνία.")
    data=api("/matches",{"date_from":d,"date_to":d,"utc_offset":tz,"sort":"utc_date","per_page":100},ttl=900)
    return jsonify(data=data or [],note="Πρώτη σελίδα, έως 100 αγώνες.")

@app.get("/api/lineup")
def lineup():
    return jsonify(sheet(valid(request.args.get("match_id"),"match")))

@app.get("/api/team")
def team():
    mid=valid(request.args.get("match_id"),"match")
    tid=valid(request.args.get("team_id"),"team")
    return jsonify(played=team_snap(mid,match(mid),tid))

@app.get("/api/player")
def player():
    mid=valid(request.args.get("match_id"),"match")
    pid=valid(request.args.get("player_id"),"player")
    return jsonify(player_snap(mid,match(mid),pid))

@app.post("/api/watch")
def watch():
    payload=request.get_json(silent=True) or {}
    mid=valid(payload.get("match_id"),"match")
    m=match(mid)
    if not before_kickoff(m): raise Problem("Αυτός ο αγώνας έχει ξεκινήσει.",409)
    ko=m.get("utc_date")
    if not ko: raise Problem("Δεν υπάρχει ώρα έναρξης.")
    label=(m.get("home_team") or {}).get("name","")+" – "+(m.get("away_team") or {}).get("name","")
    with database() as c:
        c.execute("INSERT INTO watch(match_id,kickoff,label,status) VALUES(?,?,?,'watching') ON CONFLICT(match_id) DO UPDATE SET kickoff=excluded.kickoff,label=excluded.label,status='watching'",(mid,ko,label))
    enabled=os.getenv("ENABLE_SCHEDULER")=="1"
    return jsonify(ok=True,enabled=enabled,message="Ο αγώνας μπήκε στη λίστα.")

@app.get("/api/watches")
def watches():
    with database() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM watch ORDER BY kickoff DESC LIMIT 30").fetchall()]
    return jsonify(data=rows,enabled=os.getenv("ENABLE_SCHEDULER")=="1")

def monitor_tick():
    if not KEY: return
    now=datetime.now(timezone.utc)
    with database() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM watch WHERE status IN ('watching','fetching')").fetchall()]
    for r in rows:
        mid=r["match_id"]
        try:
            kick=datetime.fromisoformat(r["kickoff"].replace("Z","+00:00"))
            minutes=(kick-now).total_seconds()/60
            if minutes<=0:
                with database() as c: c.execute("UPDATE watch SET status='expired' WHERE match_id=?",(mid,))
                continue
            if minutes>65 or time.time()-r["last_check"]<900: continue
            with database() as c: c.execute("UPDATE watch SET last_check=? WHERE match_id=?",(time.time(),mid))
            s=lineup_raw(mid)
            if not s or s.get("type")!="team_sheet" or not s.get("confirmed"): continue
            if len((s.get("home") or {}).get("starting_xi") or [])!=11 or len((s.get("away") or {}).get("starting_xi") or [])!=11: continue
            with database() as c: c.execute("UPDATE watch SET status='fetching' WHERE match_id=?",(mid,))
            m=match(mid)
            if not before_kickoff(m): continue
            for side in ("home","away"):
                part=s[side]
                tid=valid(part.get("id"),"team")
                team_snap(mid,m,tid)
                for p in part["starting_xi"]:
                    player_snap(mid,m,valid(p.get("id"),"player"))
            with database() as c: c.execute("UPDATE watch SET status='ready' WHERE match_id=?",(mid,))
        except Problem as e:
            app.logger.warning("Monitor %s: %s",mid,e)
            if e.status==429: break
        except Exception:
            app.logger.exception("Monitor failed for %s",mid)

def monitor():
    while True:
        try: monitor_tick()
        except Exception: app.logger.exception("Monitor loop failed")
        time.sleep(60)

if os.getenv("ENABLE_SCHEDULER")=="1":
    threading.Thread(target=monitor,daemon=True,name="lineup-monitor").start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","8000")),debug=False,use_reloader=False)
