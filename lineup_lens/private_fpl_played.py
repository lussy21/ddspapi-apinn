"""Private FPL-Elo played-player import, including substitutions.
Source: https://github.com/randomcrit2020/FPL-Elo-Insights (README permits use).
Only exact previously verified CSV blobs and exact 22-starter anchors.
No new Soccer Data requests. Never guesses a canonical substitute identity.
"""
import csv,hashlib,io,json,time
from collections import defaultdict,Counter
from math import isfinite
from urllib.parse import quote
import requests
import season_db

BASE="https://raw.githubusercontent.com/randomcrit2020/FPL-Elo-Insights/main/"
FIELDS=("goals","assists","xg","xa","shots_on_target","chances_created","duels_won","duels_lost","interceptions","recoveries","saves","goals_conceded","xgot_faced","goals_prevented")
POSITIONS={"Goalkeeper":"G","Defender":"D","Midfielder":"M","Forward":"F"}
def parse(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"),newline="")))
def blob_sha(data):
    return hashlib.sha1(("blob "+str(len(data))+"\0").encode()+data).hexdigest()
def get(gw,name):
    path=f"data/2026-2027/By Gameweek/GW{gw}/{name}.csv"
    with requests.get(BASE+quote(path),timeout=(10,25),stream=True) as resp:
        resp.raise_for_status()
        out=bytearray()
        for chunk in resp.iter_content(65536):
            out.extend(chunk)
            if len(out)>3000000:raise ValueError("CSV size limit")
        return bytes(out)
def number(v,signed=False):
    if v is None or str(v).strip()=="":return None
    try:
        n=float(v)
        return n if isfinite(n) and (signed or n>=0) else None
    except (ValueError,TypeError,OverflowError):return None
def reconcile(m,stats,players,identities):
    rows=[p for p in stats if p["match_id"]==m["source_match"] and (number(p["minutes_played"]) or 0)>0]
    starts=[p for p in rows if number(p["start_min"])==0]
    anchors={p["sid"]:p for p in m["anchors"]}
    if len(anchors)!=22 or len(starts)!=22 or {p["player_id"] for p in starts}!=set(anchors):return None
    if len({p["player_id"] for p in rows})!=len(rows):return None
    people={p["player_id"]:p for p in players}
    if len(people)!=len(players):return None
    codes={}
    for sid,p in anchors.items():
        person=people.get(sid)
        if not person:return None
        code=person["team_code"]
        if not code or (code in codes and codes[code]!=p["tid"]):return None
        codes[code]=p["tid"]
    if len(codes)!=2 or len(set(codes.values()))!=2 or set(Counter(p["tid"] for p in anchors.values()).values())!={11}:return None
    out=[];seen=set()
    for p in rows:
        sid=p["player_id"];person=people.get(sid)
        if not person:return None
        tid=codes.get(person["team_code"]);pos=POSITIONS.get(person["position"])
        mins=number(p["minutes_played"]);start=number(p["start_min"])
        if tid is None or pos is None or mins is None or not 0<mins<=150 or start is None:return None
        started=start==0
        if started and sid not in anchors:return None
        candidates=identities.get((tid,sid),set())
        pid=anchors[sid]["pid"] if started else next(iter(candidates)) if len(candidates)==1 else None
        if pid is not None:
            if pid in seen or (not started and pid in {x["pid"] for x in anchors.values()}):return None
            seen.add(pid)
        metrics={k:number(p.get(k),signed=k=="goals_prevented") for k in FIELDS}
        out.append((m["match_id"],tid,sid,pid,started,mins,pos,json.dumps(metrics,allow_nan=False),m["sha"],m["gw"]))
    return out

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_fpl_played_metrics (
        match_id integer NOT NULL REFERENCES archive_matches(match_id),
        team_id integer NOT NULL REFERENCES archive_teams(team_id),
        source_player_id text NOT NULL,player_id integer REFERENCES archive_players(player_id),
        started boolean NOT NULL,minutes numeric NOT NULL CHECK(minutes>0 AND minutes<=150),
        position text NOT NULL,metrics jsonb NOT NULL,source_sha text NOT NULL,gw integer NOT NULL,
        imported_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(match_id,team_id,source_player_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_fpl_played_state (
        gw integer PRIMARY KEY, source_sha text NOT NULL, matches integer NOT NULL,
        rows integer NOT NULL, linked_subs integer NOT NULL,completed_at timestamptz NOT NULL DEFAULT now())""")

def run():
    with season_db.db() as db:
        setup(db)
        anchors=db.execute("""SELECT v.match_id,v.probe_id,(p.result->>'gameweek')::int gw,p.result->>'source_file_sha' sha,
            (SELECT x->>'match' FROM jsonb_array_elements(p.result->'results') x WHERE x->>'id'=v.match_id::text AND x->>'verified'='true' LIMIT 1) source_match,
            count(*) n,jsonb_agg(jsonb_build_object('pid',v.canonical_player_id,'tid',v.team_id,'sid',x->>'source_player_id')) anchors
            FROM lineup_research_verified_player_stats v JOIN lineup_source_probe p ON p.probe_id=v.probe_id
            CROSS JOIN LATERAL jsonb_array_elements(p.result->'verified_rows') x
            WHERE v.source='fpl_elo' AND x->>'match_id'=v.match_id::text AND (x->>'canonical_player_id')::int=v.canonical_player_id
              AND (x->>'team_id')::int=v.team_id GROUP BY 1,2,3,4,5 ORDER BY gw,v.match_id""").fetchall()
        done={r["gw"]:r["source_sha"] for r in db.execute("SELECT gw,source_sha FROM lineup_fpl_played_state").fetchall()}
    identities=defaultdict(set)
    for m in anchors:
        if m["n"]!=22 or not m["source_match"]:continue
        for p in m["anchors"]:identities[(p["tid"],p["sid"])].add(p["pid"])
    weeks=defaultdict(list)
    for m in anchors:
        if m["n"]==22 and m["source_match"]:weeks[m["gw"]].append(m)
    for gw,mm in sorted(weeks.items()):
        try:
            shas={m["sha"] for m in mm}
            if len(shas)!=1:continue
            expected=next(iter(shas))
            if done.get(gw)==expected:continue
            raw=get(gw,"playermatchstats")
            if blob_sha(raw)!=expected:raise ValueError("source blob differs from verified snapshot")
            stats=parse(raw);people=parse(get(gw,"players"))
            rows=[];count=0
            for m in mm:
                match=reconcile(m,stats,people,identities)
                if match is not None:rows.extend(match);count+=1
            if count!=len(mm):raise ValueError("one or more anchored fixtures not fully reconciled")
            with season_db.db() as db:
                setup(db)
                if not db.execute("SELECT pg_try_advisory_xact_lock(614439858) ok").fetchone()["ok"]:continue
                with db.cursor() as cur:
                    cur.executemany("""INSERT INTO lineup_fpl_played_metrics
                    (match_id,team_id,source_player_id,player_id,started,minutes,position,metrics,source_sha,gw)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT DO NOTHING""",rows)
                actual=db.execute("SELECT count(*) n FROM lineup_fpl_played_metrics WHERE gw=%s AND source_sha=%s",(gw,expected)).fetchone()["n"]
                if actual!=len(rows):raise ValueError("persisted row count mismatch")
                linked=sum(not r[4] and r[3] is not None for r in rows)
                db.execute("""INSERT INTO lineup_fpl_played_state(gw,source_sha,matches,rows,linked_subs)
                    VALUES(%s,%s,%s,%s,%s) ON CONFLICT(gw) DO NOTHING""",(gw,expected,count,len(rows),linked))
            print("FPL played import",gw,count,len(rows),linked,flush=True)
        except Exception as exc:
            print("FPL played import held",gw,type(exc).__name__,str(exc)[:120],flush=True)
        time.sleep(1)
