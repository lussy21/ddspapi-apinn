"""Lineup Lens — private football lineups and seasonal starts. Independent from SharpVision."""
import json, os, re, secrets, sqlite3, threading, time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from flask import Flask, jsonify, render_template, request, Response
import season_db
import archive_11footy
import archive_espn_greece
import archive_espn_belgium
import archive_espn_denmark
import archive_espn_germany2
import archive_espn_norway
import archive_espn_netherlands
import archive_espn_turkey
import archive_espn_scotland
import archive_espn_sweden

app=Flask(__name__)
BASE="https://api.soccer-data.co/v1"
KEY=os.getenv("SOCCER_DATA_KEY","").strip()
PASS=os.getenv("APP_ACCESS_PASS","")
DB=os.getenv("LINEUP_DB_PATH","/tmp/lineup_lens.sqlite3")
LIMIT=int(os.getenv("MAX_DAY_CALLS","46"))
VERIFY_WINDOW=5  # Small sample on the 50/day free plan
VERIFY_RESERVE=10  # Preserve quota for fixtures and lineups
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
        if u["calls"]>=LIMIT:
            raise Problem("Έφτασες στο εσωτερικό όριο ασφαλείας ("+str(u["calls"])+"/"+str(LIMIT)+" κλήσεις σήμερα).",429)
        if u["remote_remaining"]==0:
            raise Problem("Εξαντλήθηκε το ημερήσιο όριο κλήσεων του Soccer Data API.",429)
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


def verified_team_snap(mid,m,tid):
    """Count starts from prior FINISHED matches' official lineups, not player season totals.
    One fixture-list request plus up to one cached lineup request per prior match.
    """
    valid(mid,"match")
    valid(tid,"team")
    k="verified-v2:"+mid+":"+tid
    cached=cache_get(k)
    if cached is not None:
        return cached
    if not before_kickoff(m):
        raise Problem("Η επαλήθευση αφορά αγώνες πριν τη σέντρα.",409)
    sid=valid(m.get("season_id"),"season")
    cid=valid(m.get("competition_id"),"competition")
    kickoff=datetime.fromisoformat(m["utc_date"].replace("Z","+00:00"))
    listing=api("/matches",{
        "team_id":tid,"competition_id":cid,"season_id":sid,
        "status":"finished","sort":"-utc_date","per_page":100
    },ttl=900)
    if not isinstance(listing,list):
        raise Problem("Μη αναγνωρίσιμη λίστα προηγούμενων αγώνων.",502)
    prior=[]
    for item in listing:
        if not isinstance(item,dict) or not isinstance(item.get("id"),str):
            continue
        try:
            game_time=datetime.fromisoformat(item["utc_date"].replace("Z","+00:00"))
            if item["id"]!=mid and game_time<kickoff and item.get("season_id")==sid and item.get("competition_id")==cid:
                prior.append(item)
        except (KeyError,TypeError,ValueError):
            continue
    prior.sort(key=lambda x:x["utc_date"],reverse=True)
    prior=prior[:VERIFY_WINDOW]
    if not prior:
        raise Problem("Δεν βρέθηκαν ολοκληρωμένοι αγώνες στην ίδια διοργάνωση και σεζόν.",404)
    # Protect the daily call allowance: no partial run when the required uncached
    # official lineups exceed the remaining local or provider quota.
    missing=0
    for item in prior:
        path="/matches/"+valid(item["id"],"match")+"/lineups"
        api_key="api:"+json.dumps([path,[]],ensure_ascii=False)
        if cache_get(api_key) is None:
            missing+=1
    allowance=usage()
    remaining=LIMIT-allowance["calls"]
    if allowance["remote_remaining"] is not None:
        remaining=min(remaining,allowance["remote_remaining"])
    if missing>max(0,remaining-VERIFY_RESERVE):
        raise Problem("Δεν υπάρχουν αρκετές διαθέσιμες κλήσεις για έλεγχο. Χρειάζονται "+str(missing)+" και απομένουν "+str(remaining)+". Κρατάμε "+str(VERIFY_RESERVE)+" για τους σημερινούς αγώνες.",429)
    counts={}
    official=0
    for item in prior:
        historical=api("/matches/"+item["id"]+"/lineups",ttl=30*86400,allow404=True)
        if not isinstance(historical,dict) or historical.get("type") not in ("played","team_sheet") or not historical.get("confirmed"):
            continue
        team=next((historical.get(side) for side in ("home","away")
                  if isinstance(historical.get(side),dict) and historical[side].get("id")==tid),None)
        xi=team.get("starting_xi") if team else None
        if not isinstance(xi,list) or len(xi)!=11:
            continue
        ids=[p.get("id") for p in xi if isinstance(p,dict)]
        if len(ids)!=11 or any(not isinstance(pid,str) or not ID.fullmatch(pid) or not pid.startswith("player_") for pid in ids) or len(set(ids))!=11:
            continue
        official+=1
        for pid in ids:
            counts[pid]=counts.get(pid,0)+1
    if official==0:
        raise Problem("Οι προηγούμενοι αγώνες δεν έχουν διαθέσιμες επίσημες ενδεκάδες.",404)
    report={"starts":counts,"played":official,"eligible":len(prior),"window":"last_5",
            "verified":official==len(prior),"source":"past_official_lineups",
            "unavailable":len(prior)-official}
    cache_put(k,report,3600)
    app.logger.info("Verified lineup sample match=%s team=%s official=%d prior=%d",mid,tid,official,len(prior))
    return report

def sheet(mid):
    m=match(mid)
    s=lineup_raw(mid)
    # Capture newly announced official XI for future seasonal history.
    # A DB outage must never prevent displaying today's lineup.
    if isinstance(s,dict) and s.get("confirmed") and s.get("type") in ("played","team_sheet") and season_db.enabled():
        try: season_db.record_confirmed(m,s,"soccer-data:"+mid)
        except Exception: app.logger.exception("Could not persist official XI for %s",mid)
    if not s or not isinstance(s,dict):
        return {"ready":False,"confirmed":False,"kickoff":m.get("utc_date"),"message":"Δεν έχει ανακοινωθεί ενδεκάδα."}
    out=[]
    for side in ("home","away"):
        part=s.get(side) or {}
        mpart=m.get(side+"_team") or {}
        tid=part.get("id") or mpart.get("id")
        ts=cache_get("team-snapshot:"+mid+":"+str(tid))
        verified=None  # Never mix old five-match cache into whole-season figures
        # Prefer persistent whole-season history over the temporary last-5 sample.
        if season_db.enabled() and tid:
            try:
                season_report=season_db.summary(m,tid)
                if season_report.get("ready"):
                    verified={"starts":season_report["starts"],"played":season_report["played"],
                              "verified":season_report["verified"],"eligible":season_report["official"],
                              "window":"season","official":season_report["official"]}
            except Exception: app.logger.exception("Could not load Neon season summary for %s",tid)
        starts=verified.get("starts",{}) if isinstance(verified,dict) else {}
        players=[]
        for p in part.get("starting_xi") or []:
            players.append({"id":p.get("id"),"name":p.get("name"),"number":p.get("jersey_number"),"position":p.get("position"),"starts":starts.get(p.get("id")) if verified else None})
        out.append({"id":tid,"name":part.get("name") or mpart.get("name") or "Ομάδα","formation":part.get("formation") or "","played":verified.get("played") if verified else (ts.get("played") if isinstance(ts,dict) else None),"verified":verified.get("verified") if verified else None,"eligible":verified.get("eligible") if verified else None,"window":verified.get("window") if verified else None,"starting_xi":players})
    return {"ready":True,"confirmed":bool(s.get("confirmed")) and s.get("type") in ("team_sheet","played"),"type":s.get("type"),"kickoff":m.get("utc_date"),"home":out[0],"away":out[1]}

@app.get("/")
def index(): return render_template("index.html")

@app.get("/health")
def health(): return jsonify(ok=True)

@app.get("/api/status")
def status(): return jsonify(configured=bool(KEY),usage=usage(),verification_window=VERIFY_WINDOW,verification_reserve=VERIFY_RESERVE,scheduler_enabled=os.getenv("ENABLE_SCHEDULER")=="1",season_db_connected=season_db.enabled())

@app.get("/api/archive-status")
def archive_status():
    """Read-only history import progress. Does not call Soccer Data."""
    if not season_db.enabled():
        raise Problem("Το Neon δεν είναι συνδεδεμένο.",503)
    try: return jsonify(archive_11footy.archive_status())
    except Exception:
        app.logger.exception("Could not read historical archive status")
        raise Problem("Το ιστορικό δεν είναι διαθέσιμο.",503)


@app.get("/api/archive-teams")
def archive_teams():
    if not season_db.enabled(): raise Problem("Το Neon δεν είναι συνδεδεμένο.",503)
    league=request.args.get("league","PL")
    try: return jsonify(data=archive_11footy.archive_teams(league))
    except archive_11footy.ArchiveProblem as e: raise Problem(str(e),400)
    except Exception:
        app.logger.exception("Archive team lookup failed")
        raise Problem("Το ιστορικό δεν είναι διαθέσιμο.",503)


@app.get("/api/archive-team")
def archive_team():
    if not season_db.enabled(): raise Problem("Το Neon δεν είναι συνδεδεμένο.",503)
    league=request.args.get("league","PL")
    try:
        tid=int(request.args.get("team_id",""))
        return jsonify(archive_11footy.team_history(league,tid))
    except (ValueError, archive_11footy.ArchiveProblem) as e: raise Problem(str(e),400)
    except Exception:
        app.logger.exception("Archive player history failed")
        raise Problem("Το ιστορικό δεν είναι διαθέσιμο.",503)


@app.get("/api/open-fixtures")
def open_fixtures():
    """Research-only fixture discovery, NO Soccer Data quota used.

    Schedules are not team sheets. Keep them out of the lineup selector until
    a separately validated lineup source exists.
    """
    from open_matchday import fetch_day, FixtureSourceProblem
    day=request.args.get("date","")
    selected=tuple(s.strip() for s in request.args.get("leagues","england,italy").split(",") if s.strip())
    try:
        return jsonify(fetch_day(day,selected))
    except FixtureSourceProblem as e:
        raise Problem(str(e),400)


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

@app.get("/api/season-team")
def season_team():
    if not season_db.enabled(): raise Problem("Η μόνιμη βάση Lineup Lens δεν έχει συνδεθεί.",503)
    mid=valid(request.args.get("match_id"),"match")
    tid=valid(request.args.get("team_id"),"team")
    m=match(mid)
    if tid not in ((m.get("home_team") or {}).get("id"),(m.get("away_team") or {}).get("id")):
        raise Problem("Η ομάδα δεν ανήκει στον αγώνα.",400)
    try: return jsonify(season_db.summary(m,tid))
    except Exception:
        app.logger.exception("Neon season read failed")
        raise Problem("Η βάση ιστορικού δεν είναι διαθέσιμη.",503)


@app.post("/api/season-team")
def collect_season_team():
    """Explicit, conservative on-demand full-season backfill.

    Each click handles at most five historical XIs and preserves a minimum
    reserve of ten provider calls. On Render Free there is no guaranteed
    continuously running worker, so collection resumes on the next click.
    """
    if not season_db.enabled(): raise Problem("Η μόνιμη βάση Lineup Lens δεν έχει συνδεθεί.",503)
    payload=request.get_json(silent=True) or {}
    mid=valid(payload.get("match_id"),"match")
    tid=valid(payload.get("team_id"),"team")
    m=match(mid)
    if tid not in ((m.get("home_team") or {}).get("id"),(m.get("away_team") or {}).get("id")):
        raise Problem("Η ομάδα δεν ανήκει στον αγώνα.",400)
    try:
        scan=season_db.last_scan(m,tid)
        need_scan=scan is None or (datetime.now(timezone.utc)-scan["fixture_list_at"]).total_seconds()>6*3600
        if need_scan:
            sid=valid(m.get("season_id"),"season")
            cid=valid(m.get("competition_id"),"competition")
            listing=api("/matches",{"team_id":tid,"competition_id":cid,"season_id":sid,
                                   "status":"finished","sort":"-utc_date","per_page":100},ttl=6*3600)
            season_db.record_fixture_list(m,tid,listing)
        allowance=usage()
        remaining=max(0,LIMIT-allowance["calls"])
        if allowance["remote_remaining"] is not None:
            remaining=min(remaining,allowance["remote_remaining"])
        batch=min(5,max(0,remaining-VERIFY_RESERVE))
        candidates=season_db.pending_matches(m,tid,batch) if batch else []
        fetched=0
        unavailable=0
        stopped=None
        for item in candidates:
            hid=item["match_id"]
            try:
                raw=api("/matches/"+valid(hid,"match")+"/lineups",ttl=30*86400,allow404=True)
                if not isinstance(raw,dict):
                    season_db.record_missing(hid)
                    unavailable+=1
                    continue
                previous={"id":hid,"season_id":item["season_id"],
                          "competition_id":item["competition_id"],"utc_date":item["kickoff_utc"].isoformat(),
                          "home_team":{"id":item["home_team_id"]},
                          "away_team":{"id":item["away_team_id"]},"status":"finished"}
                try:
                    season_db.record_confirmed(previous,raw,"soccer-data:"+hid)
                    fetched+=1
                except season_db.InvalidXI:
                    season_db.record_missing(hid)
                    unavailable+=1
            except Problem as e:
                stopped=str(e)
                break
        report=season_db.summary(m,tid)
        report.update(imported=fetched,unavailable=unavailable,api_remaining=remaining,
                      stopped=stopped,batch_size=batch)
        return jsonify(report)
    except Problem: raise
    except (ValueError,KeyError,TypeError) as e:
        raise Problem("Αδυναμία συλλογής ιστορικού: "+str(e),422)
    except Exception:
        app.logger.exception("Neon season collection failed")
        raise Problem("Η συλλογή ιστορικού απέτυχε. Τα ήδη αποθηκευμένα στοιχεία παραμένουν.",503)


@app.get("/api/team")
def team():
    mid=valid(request.args.get("match_id"),"match")
    tid=valid(request.args.get("team_id"),"team")
    return jsonify(played=team_snap(mid,match(mid),tid))

@app.get("/api/verified-team")
def verified_team():
    mid=valid(request.args.get("match_id"),"match")
    tid=valid(request.args.get("team_id"),"team")
    return jsonify(verified_team_snap(mid,match(mid),tid))

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
            # Do not spend 22 per-player stat calls when the official XI arrives.
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

def _first_private_archive_import():
    """One-time archive recovery after deploy; never blocks /health or requests."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439817) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Archive backfill is already running in another worker")
                return
            try:
                archive_11footy.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439817)")
    except Exception:
        app.logger.exception("Private 11footy import failed — existing application unaffected")

if os.getenv("LINEUP_ARCHIVE_BACKFILL")=="1" and season_db.enabled():
    threading.Thread(target=_first_private_archive_import,
                     name="private-lineup-history-import",daemon=True).start()

def _one_time_greek_backfill():
    """Read-only ESPN fetch + isolated Neon transaction. Never affects paid provider."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439818) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Greek league history import already running")
                return
            try:
                archive_espn_greece.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439818)")
    except Exception:
        app.logger.exception("Private Greek Super League history import failed")

if os.getenv("LINEUP_GREEK_BACKFILL")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_greek_backfill,
                     name="private-greek-superleague-import",daemon=True).start()


def _one_time_belgium_backfill():
    """Confirmed Belgian starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439819) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Belgian league history import already running")
                return
            try:
                archive_espn_belgium.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439819)")
    except Exception:
        app.logger.exception("Private Belgian Pro League history import failed")

if os.getenv("LINEUP_BELGIUM_BACKFILL")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_belgium_backfill,
                     name="private-belgian-proleague-import",daemon=True).start()


def _one_time_denmark_backfill():
    """Confirmed Danish starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439820) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Danish league history import already running")
                return
            try:
                archive_espn_denmark.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439820)")
    except Exception:
        app.logger.exception("Private Danish Superliga history import failed")

if os.getenv("LINEUP_DENMARK_BACKFILL","1")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_denmark_backfill,
                     name="private-danish-superliga-import",daemon=True).start()


def _one_time_germany2_backfill():
    """Confirmed German starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439821) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("German league history import already running")
                return
            try:
                archive_espn_germany2.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439821)")
    except Exception:
        app.logger.exception("Private German 2. Bundesliga history import failed")

if os.getenv("LINEUP_GERMANY2_BACKFILL","1")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_germany2_backfill,
                     name="private-german-bundesliga2-import",daemon=True).start()


def _one_time_norway_backfill():
    """Confirmed Norwegian starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439822) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Norwegian league history import already running")
                return
            try:
                archive_espn_norway.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439822)")
    except Exception:
        app.logger.exception("Private Norwegian Eliteserien history import failed")

if os.getenv("LINEUP_NORWAY_BACKFILL","1")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_norway_backfill,
                     name="private-norwegian-eliteserien-import",daemon=True).start()


def _one_time_netherlands_backfill():
    """Confirmed Dutch starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439823) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Dutch league history import already running")
                return
            try:
                archive_espn_netherlands.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439823)")
    except Exception:
        app.logger.exception("Private Dutch Eredivisie history import failed")

if os.getenv("LINEUP_NETHERLANDS_BACKFILL","1")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_netherlands_backfill,
                     name="private-dutch-eredivisie-import",daemon=True).start()


def _one_time_turkey_backfill():
    """Confirmed Turkish starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439824) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Turkish league history import already running")
                return
            try:
                archive_espn_turkey.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439824)")
    except Exception:
        app.logger.exception("Private Turkish Super Lig history import failed")

if os.getenv("LINEUP_TURKEY_BACKFILL","1")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_turkey_backfill,
                     name="private-turkish-superlig-import",daemon=True).start()


def _one_time_scotland_backfill():
    """Confirmed Scottish starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439825) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Scottish league history import already running")
                return
            try:
                archive_espn_scotland.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439825)")
    except Exception:
        app.logger.exception("Private Scottish Premiership history import failed")

if os.getenv("LINEUP_SCOTLAND_BACKFILL","1")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_scotland_backfill,
                     name="private-scottish-premiership-import",daemon=True).start()


def _one_time_sweden_backfill():
    """Confirmed Swedish starters, ESPN read-only fetch, isolated Neon write."""
    try:
        with season_db.db() as conn:
            granted=conn.execute("SELECT pg_try_advisory_lock(614439826) AS acquired").fetchone()
            if not granted or not granted["acquired"]:
                app.logger.info("Swedish league history import already running")
                return
            try:
                archive_espn_sweden.import_all(log=app.logger.info)
            finally:
                conn.execute("SELECT pg_advisory_unlock(614439826)")
    except Exception:
        app.logger.exception("Private Swedish Allsvenskan history import failed")

if os.getenv("LINEUP_SWEDEN_BACKFILL","1")=="1" and season_db.enabled():
    threading.Thread(target=_one_time_sweden_backfill,
                     name="private-swedish-allsvenskan-import",daemon=True).start()


if __name__=="__main__":
    from waitress import serve
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","8000")),threads=4)
