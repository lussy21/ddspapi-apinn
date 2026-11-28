"""Verified ESPN historical player stats for eight direct-ID domestic leagues.

Separate data source; never writes SharpVision or the official lineup archive.
Minutes are reconstructed on the 0--90 regulation clock from explicit substitutions
and dismissals (45+ stoppage maps to 45, 90+ maps to 90). Unknown events/metrics
remain unknown. Validate team IDs, both full starting XIs, score, substitution
balance and team minutes before committing a match. No xG/xA/xGOT is inferred.
"""
from collections import Counter
import json
import re
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

LEAGUES = {"BE1":"bel.1","DK1":"den.1","GR1":"gre.1","NL1":"ned.1",
           "NO1":"nor.1","SC1":"sco.1","SE1":"swe.1","TR1":"tur.1"}
LOCK = 614439873
MATCH_OFFSET=500_000_000
TEAM_OFFSET=1_000_000_000
PLAYER_OFFSET=1_500_000_000
SOURCE="ESPN (λεπτά από αλλαγές)"

class InvalidStats(ValueError):
    pass

def sid(v, offset):
    if isinstance(v,bool) or not str(v or "").isdigit():
        raise InvalidStats("Invalid ESPN identity")
    n=int(v)
    if not 0<n<(500_000_000 if offset==MATCH_OFFSET else 100_000_000):
        raise InvalidStats("ESPN identity outside namespace")
    return n+offset

def fetch(code,mid):
    slug=LEAGUES[code]
    event_id=mid-MATCH_OFFSET
    if sid(event_id,MATCH_OFFSET)!=mid:raise InvalidStats("Wrong match namespace")
    req=Request(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}",
                headers={"User-Agent":"LineupLens-Personal-Research/1.0"})
    with urlopen(req,timeout=22) as r:
        raw=r.read(4_000_001)
    if len(raw)>4_000_000:raise InvalidStats("Oversized ESPN response")
    return json.loads(raw)

def metric(v):
    if isinstance(v,bool):return None
    if isinstance(v,int) and 0<=v<=1000:return v
    if isinstance(v,float) and v.is_integer() and 0<=v<=1000:return int(v)
    if isinstance(v,str) and v.isdigit() and int(v)<=1000:return int(v)
    return None

def required(stats,key):
    v=metric(stats.get(key))
    if v is None:raise InvalidStats("Missing explicit statistic: "+key)
    return v

def flag(v):
    if isinstance(v,bool):return v
    if isinstance(v,dict) and isinstance(v.get("didSub"),bool):return v["didSub"]
    raise InvalidStats("Unverified substitution flag")

def minute(clock):
    if not isinstance(clock,dict):raise InvalidStats("Missing event clock")
    s=str(clock.get("displayValue","")).strip().replace("’","'")
    m=re.fullmatch(r"(\d{1,3})\s*'?(?:\s*\+\s*(\d{1,2})\s*'?)?",s)
    if not m:raise InvalidStats("Unknown clock format")
    base=int(m.group(1))
    if m.group(2) is not None and base not in (45,90):
        raise InvalidStats("Unexpected stoppage-time clock")
    if not 0<=base<=110:raise InvalidStats("Non-regulation match clock")
    return min(base,90)

def sub_times(player,ins,outs):
    events=[minute(p.get("clock")) for p in (player.get("plays") or [])
            if isinstance(p,dict) and p.get("substitution") is True]
    needed=int(ins)+int(outs)
    if len(events)==needed:return sorted(events)
    # Older ESPN schema has explicit clock inside the two substitution objects.
    direct=[]
    for field,wanted in (("subbedIn",ins),("subbedOut",outs)):
        if wanted:
            obj=player.get(field)
            if not isinstance(obj,dict):raise InvalidStats("Incomplete substitution events")
            direct.append(minute(obj.get("clock")))
    if len(direct)!=needed:raise InvalidStats("Incomplete substitution events")
    return sorted(direct)

def player_row(p,tid):
    if not isinstance(p,dict) or not isinstance(p.get("starter"),bool):
        raise InvalidStats("Unverified roster membership")
    athlete=p.get("athlete") or {}
    pid=sid(athlete.get("id"),PLAYER_OFFSET)
    name=(athlete.get("displayName") or "").strip()
    if not name:raise InvalidStats("Missing player name")
    raw={}
    for s in (p.get("stats") or []):
        if not isinstance(s,dict) or not s.get("name"):continue
        k=s["name"]
        if k in raw and raw[k]!=s.get("value"):raise InvalidStats("Conflicting player stats")
        raw[k]=s.get("value")
    started=p["starter"]
    ins=flag(p.get("subbedIn",False));outs=flag(p.get("subbedOut",False))
    app=metric(raw.get("appearances"))
    if not started and not ins:
        if app not in (0,None) or outs or any((metric(raw.get(k)) or 0)>0 for k in ("totalGoals","goalAssists","ownGoals")):
            raise InvalidStats("Unexplained appearance")
        return pid,None,None,None,0
    if app!=1 or (started and ins):raise InvalidStats("Unverified played appearance")
    # Explicit substitution flags and event times are required for all played players.
    if "subbedIn" not in p or "subbedOut" not in p:raise InvalidStats("Missing played-player flags")
    clocks=sub_times(p,ins,outs)
    entry=0 if started else clocks[0]
    exit_=clocks[-1] if outs else 90
    if not 0<=entry<=exit_<=90:raise InvalidStats("Inconsistent playing interval")
    red_count=required(raw,"redCards")
    red_clocks=[minute(x.get("clock")) for x in (p.get("plays") or [])
                if isinstance(x,dict) and x.get("redCard") is True]
    if red_count and not red_clocks:raise InvalidStats("Missing dismissal clock")
    if len(red_clocks)>1:raise InvalidStats("Ambiguous dismissal")
    loss=0
    if red_clocks:
        red=red_clocks[0]
        if red<entry:raise InvalidStats("Dismissed before entry")
        if red<exit_ or (not outs and red==exit_):
            if outs:raise InvalidStats("Dismissal conflicts with replacement")
            exit_=red
            loss=90-red
    data={"goals":required(raw,"totalGoals"),"assists":required(raw,"goalAssists"),
          "own_goals":required(raw,"ownGoals")}
    for src,dst in (("totalShots","shots"),("shotsOnTarget","shots_on_target")):
        v=metric(raw.get(src))
        if v is not None:data[dst]=v
    # ESPN's saves field is keeper-only in the audited rosters.
    saves=metric(raw.get("saves"))
    gc=metric(raw.get("goalsConceded"))
    if saves is not None and gc is not None:
        data.update(saves=saves,goals_conceded=gc)
    row={"player_id":pid,"team_id":tid,"player_name":name,"started":started,
         "minutes":exit_-entry,"metrics":data}
    return pid,row,(entry if ins else None),(clocks[-1] if outs else None),loss

def parse(doc,match,expected):
    mid=match["match_id"]
    header=doc.get("header") or {}
    if sid(header.get("id"),MATCH_OFFSET)!=mid:raise InvalidStats("Wrong event")
    comps=header.get("competitions") or []
    if len(comps)!=1:raise InvalidStats("Unverified competition")
    comp=comps[0]
    if (comp.get("status") or {}).get("type",{}).get("completed") is not True:
        raise InvalidStats("Fixture not completed")
    competitors=comp.get("competitors") or []
    if len(competitors)!=2:raise InvalidStats("Expected two final scores")
    actual={}
    for c in competitors:
        team=sid((c.get("team") or {}).get("id") or c.get("id"),TEAM_OFFSET)
        score=metric(c.get("score"))
        if score is None or team in actual:raise InvalidStats("Invalid final score")
        actual[team]=score
    home,away=match["home_team_id"],match["away_team_id"]
    if actual!={home:match["home_goals"],away:match["away_goals"]}:
        raise InvalidStats("Final score/team mismatch")
    groups=doc.get("rosters") or []
    if len(groups)!=2:raise InvalidStats("Missing full team rosters")
    seen=set();team_rows={};all_ids=set()
    for g in groups:
        tid=sid((g.get("team") or {}).get("id"),TEAM_OFFSET)
        if tid not in actual or tid in seen:raise InvalidStats("Roster team mismatch")
        seen.add(tid)
        roster=g.get("roster") or []
        if not 11<=len(roster)<=40:raise InvalidStats("Invalid roster size")
        rows=[];incoming=Counter();outgoing=Counter();dismissals=0;starters=set()
        for p in roster:
            pid,row,entry,exit_,loss=player_row(p,tid)
            if pid in all_ids:raise InvalidStats("Duplicate player")
            all_ids.add(pid)
            if row is None:continue
            if row["started"]:starters.add(pid)
            if entry is not None:incoming[entry]+=1
            if exit_ is not None:outgoing[exit_]+=1
            dismissals+=loss
            rows.append(row)
        if len(starters)!=11 or starters!=set(expected.get(tid,[])):
            raise InvalidStats("Starting XI disagrees with archive")
        if incoming!=outgoing:raise InvalidStats("Unbalanced substitutions")
        if sum(r["minutes"] for r in rows)!=990-dismissals:
            raise InvalidStats("Team playing minutes do not reconcile")
        team_rows[tid]=rows
    if set(team_rows)!=set(actual):raise InvalidStats("Missing team")
    for tid,opp in ((home,away),(away,home)):
        rows=team_rows[tid]
        goals=sum(r["metrics"]["goals"] for r in rows)
        own=sum(r["metrics"]["own_goals"] for r in team_rows[opp])
        if goals+own!=actual[tid]:raise InvalidStats("Player goals do not reconcile with final score")
        if sum(r["metrics"]["assists"] for r in rows)>goals:
            raise InvalidStats("Player assists exceed recorded goals")
        keepers=[r for r in rows if "saves" in r["metrics"]]
        # Never use an outfield zero or a partial goalkeeper record as keeper data.
        if (not keepers or sum(r["minutes"] for r in keepers)!=90 or
            sum(r["metrics"]["goals_conceded"] for r in keepers)!=actual[opp]):
            for r in rows:
                r["metrics"].pop("saves",None);r["metrics"].pop("goals_conceded",None)
    return team_rows[home]+team_rows[away]

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_espn_stats_state (
      match_id integer PRIMARY KEY REFERENCES archive_matches(match_id),
      status text NOT NULL CHECK(status IN('complete','retry')),
      player_rows integer NOT NULL DEFAULT 0, last_attempt_at timestamptz NOT NULL DEFAULT now(),
      retry_at timestamptz, last_error text)""")
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_espn_player_metrics (
      match_id integer NOT NULL REFERENCES archive_matches(match_id),
      team_id integer NOT NULL, player_id integer NOT NULL, player_name text NOT NULL,
      started boolean NOT NULL, minutes integer NOT NULL CHECK(minutes BETWEEN 0 AND 90),
      metrics jsonb NOT NULL, PRIMARY KEY(match_id,player_id))""")
    db.execute("""CREATE INDEX IF NOT EXISTS lineup_espn_metrics_team_idx
        ON lineup_espn_player_metrics(team_id,match_id)""")

def tick():
    import season_db
    from psycopg.types.json import Jsonb
    with season_db.db() as db:
        setup(db)
        if not db.execute("SELECT pg_try_advisory_xact_lock(%s) ok",(LOCK,)).fetchone()["ok"]:
            return 15
        # Round-robin across leagues by most recent attempt, newest matches first.
        m=db.execute("""WITH recent AS (
            SELECT a.competition_code,max(s.last_attempt_at) last_attempt
            FROM lineup_espn_stats_state s JOIN archive_matches a USING(match_id)
            GROUP BY a.competition_code)
            SELECT a.match_id,a.competition_code,a.home_team_id,a.away_team_id,r.home_goals,r.away_goals
            FROM archive_matches a JOIN archive_match_results r USING(match_id)
            LEFT JOIN lineup_espn_stats_state s USING(match_id)
            LEFT JOIN recent z ON z.competition_code=a.competition_code
            WHERE a.season_year=2026 AND a.competition_code=ANY(%s)
            AND r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL
            AND a.kickoff_utc<now() AND a.match_id BETWEEN 500000001 AND 999999999
            AND (s.match_id IS NULL OR (s.status='retry' AND s.retry_at<=now()))
            ORDER BY z.last_attempt NULLS FIRST,a.kickoff_utc DESC,a.match_id LIMIT 1""",(list(LEAGUES),)).fetchone()
        if not m:return 300
        mid=m["match_id"]
        expected={}
        for p in db.execute("SELECT team_id,player_id FROM archive_starters WHERE match_id=%s",(mid,)).fetchall():
            expected.setdefault(p["team_id"],set()).add(p["player_id"])
        try:
            if len(expected)!=2 or any(len(v)!=11 for v in expected.values()):
                raise InvalidStats("Archive XI incomplete")
            rows=parse(fetch(m["competition_code"],mid),m,expected)
        except Exception as exc:
            limited=isinstance(exc,HTTPError) and exc.code==429
            delay=86400 if isinstance(exc,InvalidStats) else 3600
            db.execute("""INSERT INTO lineup_espn_stats_state(match_id,status,last_error,retry_at)
              VALUES(%s,'retry',%s,now()+make_interval(secs=>%s))
              ON CONFLICT(match_id) DO UPDATE SET status='retry',last_error=excluded.last_error,
              retry_at=excluded.retry_at,last_attempt_at=now()""",(mid,str(exc)[:180],delay))
            print("ESPN stats held",m["competition_code"],mid,type(exc).__name__,str(exc)[:100],flush=True)
            return 900 if limited else (20 if not isinstance(exc,InvalidStats) else 3)
        with db.cursor() as c:
            c.executemany("""INSERT INTO lineup_espn_player_metrics(match_id,team_id,player_id,player_name,started,minutes,metrics)
                 VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(match_id,player_id) DO NOTHING""",
                [(mid,r["team_id"],r["player_id"],r["player_name"],r["started"],r["minutes"],Jsonb(r["metrics"])) for r in rows])
            c.execute("""INSERT INTO lineup_espn_stats_state(match_id,status,player_rows)
              VALUES(%s,'complete',%s) ON CONFLICT(match_id) DO UPDATE SET
              status='complete',player_rows=excluded.player_rows,last_attempt_at=now(),retry_at=NULL,last_error=NULL""",(mid,len(rows)))
        print("ESPN stats verified",m["competition_code"],mid,len(rows),"played players",flush=True)
        return 2

def loop():
    time.sleep(10)
    while True:
        try:delay=tick()
        except Exception as exc:
            print("ESPN stats paused",type(exc).__name__,flush=True)
            delay=300
        time.sleep(delay)
