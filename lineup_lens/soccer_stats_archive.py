"""Quota-limited, independent Soccer Data match statistics archive, 17 competitions."""
from datetime import datetime, timedelta, timezone
import json
import re
import time
import unicodedata
import season_db
import soccer_stats_coverage as coverage

COMP="competition_705uv6jm8myn"
SEASON="season_hr1ie7yrsdmt"
LOCK=614439855
CAP=40
COVERAGE_CAP=44  # Up to four additional coverage-only calls; still below free 50 and app limit 46.
# Allocate uncovered leagues first (the current PL pilot already has match ratings).
PRIORITY=('TR1','GR1','BE1','DK1','NL1','NO1','SC1','SE1')

ALIASES={"mancity":"manchestercity","manutd":"manchesterunited","spurs":"tottenhamhotspur",
         "nottmforest":"nottinghamforest","nottmfor":"nottinghamforest",
         "newcastle":"newcastleunited","brighton":"brightonhovealbion",
         "bournemouth":"afcbournemouth","wolves":"wolverhamptonwanderers",
         "leeds":"leedsunited","ipswich":"ipswichtown","coventry":"coventrycity",
         "hull":"hullcity","westham":"westhamunited"}

TRANS=str.maketrans({"ß":"ss","ð":"d","đ":"d","ı":"i","ł":"l","ø":"o"})
def norm(v):
    return "".join(c for c in unicodedata.normalize("NFKD",str(v or "")).casefold().translate(TRANS) if c.isascii() and c.isalnum())

def team(v):
    n=norm(v)
    if n.endswith("fc"):n=n[:-2]
    return ALIASES.get(n,n)

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_fixture (
        match_id integer PRIMARY KEY REFERENCES archive_matches(match_id),
        provider_id text UNIQUE NOT NULL, home_source_id text NOT NULL,
        away_source_id text NOT NULL, mapped_at timestamptz NOT NULL DEFAULT now(),
        fetched_at timestamptz, matched_starters integer, player_rows integer,
        last_error text, last_attempt_at timestamptz)""")
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_player (
        match_id integer NOT NULL REFERENCES soccer_stats_fixture(match_id),
        provider_player_id text NOT NULL, team_id integer NOT NULL,
        canonical_player_id integer REFERENCES archive_players(player_id),
        player_name text NOT NULL, started boolean NOT NULL, played boolean NOT NULL,
        minutes integer NOT NULL CHECK(minutes>=0 AND minutes<=150),
        stats jsonb NOT NULL, PRIMARY KEY(match_id,provider_player_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_day (
        day date PRIMARY KEY, calls integer NOT NULL DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_listing (
        start_day date PRIMARY KEY, attempted_at timestamptz NOT NULL DEFAULT now(),
        matched integer, error text)""")
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_status (
        id integer PRIMARY KEY CHECK(id=1), updated_at timestamptz NOT NULL DEFAULT now(),
        message text NOT NULL)""")
    coverage.setup(db)

def status(db,message):
    db.execute("""INSERT INTO soccer_stats_status(id,message) VALUES(1,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=now(),message=excluded.message""",(message,))

def reserve(usage,cap=CAP):
    u=usage()
    if u.get("remote_remaining") is not None and u["remote_remaining"]<=5:return False
    if u.get("calls",0)>=min(cap,u.get("local_limit",46)):return False
    with season_db.db() as db:
        return bool(db.execute("""INSERT INTO soccer_stats_day(day,calls)
            VALUES((now() at time zone 'UTC')::date,1)
            ON CONFLICT(day) DO UPDATE SET calls=soccer_stats_day.calls+1
            WHERE soccer_stats_day.calls<%s RETURNING calls""",(cap,)).fetchone())

def request(api,usage,path,params=None,cap=CAP):
    if not reserve(usage,cap):raise RuntimeError("daily quota reserve reached")
    return api(path,params=params,ttl=86400)

def candidates(db):
    return db.execute("""SELECT m.match_id,m.kickoff_utc,m.local_date,m.home_team_id,m.away_team_id,
        h.team_name home_name,a.team_name away_name,r.home_goals,r.away_goals,m.competition_code,c.provider_id comp,c.season_id
        FROM archive_matches m JOIN archive_match_results r ON r.match_id=m.match_id
        JOIN archive_teams h ON h.team_id=m.home_team_id
        JOIN archive_teams a ON a.team_id=m.away_team_id
        LEFT JOIN soccer_stats_fixture f ON f.match_id=m.match_id
        JOIN soccer_stats_coverage c ON c.code=m.competition_code AND c.coverage_status='ready'
        WHERE m.season_year=2026 AND f.match_id IS NULL
        ORDER BY m.kickoff_utc DESC""").fetchall()

def week(d):return d-timedelta(days=d.weekday())

def find_fixture(rows,m):
    out=[]
    for r in rows:
        if not isinstance(r,dict) or r.get("competition_id")!=m["comp"] or r.get("season_id")!=m["season_id"] or r.get("status")!="finished":continue
        h=r.get("home_team") or {}; a=r.get("away_team") or {}
        if not isinstance(h,dict) or not isinstance(a,dict):continue
        try:k=datetime.fromisoformat(r["utc_date"].replace("Z","+00:00"))
        except (ValueError,TypeError,KeyError,AttributeError):continue
        if k!=m["kickoff_utc"] or team(h.get("name"))!=team(m["home_name"]) or team(a.get("name"))!=team(m["away_name"]):continue
        # Compare final goals whenever the documented payload exposes a recognized score shape.
        score=r.get("score") or {}
        hs=r.get("home_score");as_=r.get("away_score")
        if isinstance(score,dict):
            if hs is None:hs=score.get("home")
            if as_ is None:as_=score.get("away")
        if isinstance(hs,int) and isinstance(as_,int) and (hs,as_)!=(m["home_goals"],m["away_goals"]):continue
        mid=r.get("id");hid=h.get("id");aid=a.get("id")
        if all(isinstance(v,str) and re.fullmatch(p+r"_[A-Za-z0-9]{5,32}",v) for p,v in (("match",mid),("team",hid),("team",aid))) and hid!=aid:out.append((mid,hid,aid))
    return out[0] if len(out)==1 else None

def collection_context(db):
    recent=db.execute("""SELECT a.competition_code code,count(*) total,
        count(*) FILTER(WHERE f.fetched_at IS NOT NULL AND f.matched_starters=22) ready
        FROM archive_matches a LEFT JOIN soccer_stats_fixture f USING(match_id)
        WHERE a.season_year=2026 AND a.kickoff_utc>=now()-interval '60 days'
        GROUP BY a.competition_code""").fetchall()
    ratios={r["code"]:r["ready"]/r["total"] for r in recent if r["total"]}
    upcoming=set()
    if db.execute("SELECT to_regclass('lineup_live_fixtures') AS t").fetchone()["t"]:
        rows=db.execute("""WITH live AS (
          SELECT f.competition_code code,
            CASE WHEN c->'team'->>'id' ~ '^[0-9]{1,8}$'
              THEN 1000000000+(c->'team'->>'id')::int END source_id
          FROM lineup_live_fixtures f
          CROSS JOIN LATERAL jsonb_array_elements(f.event->'competitions'->0->'competitors') c
          WHERE f.kickoff_utc BETWEEN now() AND now()+interval '72 hours'
          AND f.status<>'unavailable')
          SELECT DISTINCT live.code,coalesce(l.canonical_id,live.source_id) tid FROM live
          LEFT JOIN archive_source_links l ON l.competition_code=live.code AND l.kind='team'
          AND l.source_id=live.source_id WHERE live.source_id IS NOT NULL""").fetchall()
        upcoming={(r["code"],r["tid"]) for r in rows}
    return ratios,upcoming

def collection_key(m,ratios,upcoming,now):
    code=m["competition_code"]
    age=(now-m["kickoff_utc"]).total_seconds()/86400
    relevant=any((code,m[k]) in upcoming for k in ("home_team_id","away_team_id"))
    tier=0 if relevant and age<=60 else (1 if age<=60 else 2)
    order=PRIORITY+tuple(c for c in coverage.ORDER if c not in PRIORITY)
    return (tier,ratios.get(code,0.0),-m["kickoff_utc"].timestamp(),order.index(code),m["match_id"])

def discover(api,usage,db,missing,context=None,preferred=None):
    eligible={(r["code"],r["start_day"]) for r in db.execute("""SELECT code,start_day FROM soccer_stats_listing_v2
        WHERE attempted_at>now()-(CASE WHEN start_day>=current_date-14 THEN interval '1 day' ELSE interval '7 days' END)""").fetchall()}
    ratios,upcoming=context if context is not None else collection_context(db)
    now=datetime.now(timezone.utc)
    missing.sort(key=lambda m:collection_key(m,ratios,upcoming,now))
    choices=missing if preferred is None else [m for m in missing if m["match_id"] in preferred]
    m0=next((m for m in choices if (m["competition_code"],week(m["local_date"])) not in eligible),None)
    if m0 is None:return False
    code=m0["competition_code"]; anchor=week(m0["local_date"])
    try:
        rows=request(api,usage,"/matches",{"competition_id":m0["comp"],"season_id":m0["season_id"],"status":"finished",
            "date_from":anchor.isoformat(),"date_to":(anchor+timedelta(days=6)).isoformat(),
            "utc_offset":"+00:00","sort":"utc_date","per_page":100})
        if not isinstance(rows,list) or len(rows)>=100:raise ValueError("fixture list missing or truncated")
    except Exception as e:
        if str(e)=="daily quota reserve reached" or getattr(e,"status",None)==429:raise
        db.execute("""INSERT INTO soccer_stats_listing_v2(code,start_day,error) VALUES(%s,%s,%s)
            ON CONFLICT(code,start_day) DO UPDATE SET attempted_at=now(),error=excluded.error""",(code,anchor,str(e)[:160]))
        return True
    n=0
    for m in missing:
        if m["competition_code"]!=code or week(m["local_date"])!=anchor:continue
        hit=find_fixture(rows,m)
        if hit:
            db.execute("""INSERT INTO soccer_stats_fixture(match_id,provider_id,home_source_id,away_source_id)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(m["match_id"],*hit))
            n+=1
    db.execute("""INSERT INTO soccer_stats_listing_v2(code,start_day,matched) VALUES(%s,%s,%s)
        ON CONFLICT(code,start_day) DO UPDATE SET attempted_at=now(),matched=excluded.matched,error=NULL""",(code,anchor,n))
    status(db,f"{code} fixtures {anchor}: {n} matched")
    return True

def store(db,f,rows):
    if not isinstance(rows,list) or not rows or len(rows)>100:raise ValueError("invalid stats roster")
    old=db.execute("""SELECT s.team_id,s.player_id,p.player_name FROM archive_starters s
        JOIN archive_players p ON p.player_id=s.player_id WHERE s.match_id=%s""",(f["match_id"],)).fetchall()
    if len(old)!=22:raise ValueError("archive XI not complete")
    sides={f["home_source_id"]:f["home_team_id"],f["away_source_id"]:f["away_team_id"]}
    counts={tid:0 for tid in sides.values()};seen=set();linked=set();out=[]
    for p in rows:
        if not isinstance(p,dict):raise ValueError("invalid player record")
        pid=p.get("player_id");name=p.get("player_name");tid=sides.get(p.get("team_id"));mins=p.get("minutes_played")
        started=p.get("started");played=p.get("played")
        if not isinstance(pid,str) or not re.fullmatch(r"player_[A-Za-z0-9]{5,32}",pid) or pid in seen or not isinstance(name,str) or not name.strip() or tid is None or type(mins) is not int or not 0<=mins<=150 or type(started) is not bool or type(played) is not bool:raise ValueError("unverified player identity or minutes")
        seen.add(pid)
        if started:counts[tid]+=1
        matches=[q["player_id"] for q in old if started and q["team_id"]==tid and norm(q["player_name"])==norm(name)]
        # Reuse only an already verified provider identity, within the same team.
        known=db.execute("""SELECT DISTINCT canonical_player_id FROM soccer_stats_player
            WHERE provider_player_id=%s AND team_id=%s AND started
            AND canonical_player_id IS NOT NULL""",(pid,tid)).fetchall()
        ids={r["canonical_player_id"] for r in known}
        if len(ids)==1:
            previous=next(iter(ids))
            if started and previous in {q["player_id"] for q in old if q["team_id"]==tid}:
                if not matches or matches==[previous]:matches=[previous]
                else:matches=[]
            elif not started and played and previous not in {q["player_id"] for q in old}:
                matches=[previous]
        canonical=matches[0] if len(matches)==1 and matches[0] not in linked else None
        if canonical is not None:linked.add(canonical)
        clean={k:p[k] for k in ("position","rating","passing","shooting","duels","defending","goalkeeping","general") if k in p}
        out.append((f["match_id"],pid,tid,canonical,name,started,played,mins,json.dumps(clean,ensure_ascii=False,allow_nan=False)))
    if any(v!=11 for v in counts.values()):raise ValueError("provider XI not complete")
    verified_starters=sum(1 for r in out if r[5] and r[3] is not None)
    # Preserve validated roster and raw stats; never infer unmatched canonical IDs.
    for row in out:
        db.execute("""INSERT INTO soccer_stats_player(match_id,provider_player_id,team_id,canonical_player_id,
            player_name,started,played,minutes,stats) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT(match_id,provider_player_id) DO NOTHING""",row)
    db.execute("""UPDATE soccer_stats_fixture SET fetched_at=now(),matched_starters=%s,player_rows=%s,last_error=NULL
        WHERE match_id=%s""",(verified_starters,len(out),f["match_id"]))
    status(db,f"{f['competition_code']} match {f['match_id']}: {verified_starters}/22 verified starters, {len(out)} player rows")

def tick(api,usage):
    with season_db.db() as db:
        if not db.execute("SELECT pg_try_advisory_xact_lock(%s) AS ok",(LOCK,)).fetchone()["ok"]:return False
        try:
            if coverage.step(db,lambda path,params:request(api,usage,path,params,cap=COVERAGE_CAP)):return True
        except RuntimeError as e:
            if str(e)=="daily quota reserve reached":return False
            raise
        context=collection_context(db)
        ratios,upcoming=context
        now=datetime.now(timezone.utc)
        missing=candidates(db)
        pending=db.execute("""SELECT f.*,m.home_team_id,m.away_team_id,m.competition_code,m.kickoff_utc
            FROM soccer_stats_fixture f JOIN archive_matches m ON m.match_id=f.match_id
            WHERE f.fetched_at IS NULL AND (f.last_attempt_at IS NULL OR f.last_attempt_at<now()-interval '1 day')""").fetchall()
        f=min(pending,key=lambda m:collection_key(m,ratios,upcoming,now)) if pending else None
        # Reserve a portion of the daily budget for discovering new leagues
        # even while another competition has a pending match backlog.
        attempts=db.execute("SELECT count(*) n FROM soccer_stats_listing_v2 WHERE attempted_at>=date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'").fetchone()["n"]
        better=[m for m in missing if f is None or collection_key(m,ratios,upcoming,now)<collection_key(f,ratios,upcoming,now)]
        if better and attempts<10:
            try:
                if discover(api,usage,db,missing,context,preferred={m["match_id"] for m in better}):return True
            except RuntimeError as e:
                if str(e)=="daily quota reserve reached":return False
                raise
        if f:
            try:rows=request(api,usage,"/matches/"+f["provider_id"]+"/player-stats")
            except RuntimeError as e:
                if str(e)=="daily quota reserve reached":return False
                raise
            except Exception as e:
                if getattr(e,"status",None)==429:return False
                db.execute("UPDATE soccer_stats_fixture SET last_attempt_at=now(),last_error=%s WHERE match_id=%s",(str(e)[:160],f["match_id"]))
                return True
            try:
                # Validation and inserts are atomic, including rejection of a partial roster.
                with db.transaction():store(db,f,rows)
            except ValueError as e:
                db.execute("UPDATE soccer_stats_fixture SET last_attempt_at=now(),last_error=%s WHERE match_id=%s",(str(e)[:160],f["match_id"]))
            return True
        try:return discover(api,usage,db,missing,context)
        except RuntimeError as e:
            if str(e)=="daily quota reserve reached":return False
            raise

def loop(api,usage):
    while True:
        try:
            with season_db.db() as db:setup(db)
            more=tick(api,usage)
            time.sleep(2 if more else 600)
        except Exception as e:
            try:
                with season_db.db() as db:
                    setup(db);status(db,"Pilot paused: "+type(e).__name__)
            except Exception:pass
            print("Soccer Data PL pilot paused:",type(e).__name__,flush=True)
            time.sleep(900)
