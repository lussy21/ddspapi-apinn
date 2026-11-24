"""Private Italian Serie A ESPN confirmed-XI snapshot into Lineup Lens Neon.

Source: ESPN site soccer scoreboard and match summary, Italian Serie A
ita.1, 2026/27. Publicly accessible (unofficial) endpoints; research use only.
No scraping of predictions, no paid API, no SharpVision/PINNACLE operations.

ESPN occasionally labels EVERY confirmed starter's position "SUB" in a few
matches. Count the 11 explicitly marked starter=True, but store position=NULL
rather than guessing a tactical role for these games. NEVER label those pitch
positions as verified. Match archive includes all confirmed lineups and a
separately verified last dated match pitch for each team.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import re
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import time
from urllib.request import Request, urlopen

import season_db
from archive_pitch import ROLE, pitch_from_codes

SOURCE="espn"
LEAGUE="SA"
RELEASE="espn-ita1-delta-2026-11-24"
BASE="https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1"
CUTOFF="2026-11-24"
ITALIAN_TZ=ZoneInfo("Europe/Rome")
TEAM_OFFSET=1_000_000_000
PLAYER_OFFSET=1_500_000_000
MATCH_OFFSET=500_000_000
MAX_EVENTS=120
MAX_JSON=2_300_000

class ItalianArchiveProblem(ValueError):
    pass

def fetch(route):
    """Bounded fixed-host GET; never accepts a user-supplied URL."""
    if not route.startswith(("/scoreboard?dates=", "/summary?event=")):
        raise ItalianArchiveProblem("Unexpected ESPN route")
    req=Request(BASE+route,headers={"User-Agent":"LineupLens-Personal-Research/1.0"})
    with urlopen(req,timeout=24) as result:
        raw=result.read(MAX_JSON+1)
    if len(raw)>MAX_JSON:raise ItalianArchiveProblem("Oversized ESPN JSON")
    return json.loads(raw)

def _id(value,offset):
    if isinstance(value,bool) or not str(value or "").isdigit():
        raise ItalianArchiveProblem("Missing ESPN numeric ID")
    val=int(value)
    # ESPN event IDs are ~400 million; team/player IDs use smaller ranges.
    upper=500_000_000 if offset==MATCH_OFFSET else 100_000_000
    if val<=0 or val>=upper:
        raise ItalianArchiveProblem("ESPN ID exceeds reserved namespace")
    if offset+val>2_147_483_647:
        raise ItalianArchiveProblem("ESPN ID cannot fit PostgreSQL INT")
    return offset+val

def discover_games(get=fetch, pause=0.16):
    payload=get("/scoreboard?dates=20261120&limit=50")
    leagues=payload.get("leagues") or []
    if len(leagues)!=1 or leagues[0].get("slug")!="ita.1":
        raise ItalianArchiveProblem("Could not verify ESPN Italian league")
    if (leagues[0].get("season") or {}).get("year")!=2026:
        raise ItalianArchiveProblem("ESPN season mismatch")
    days=sorted({x[:10].replace("-","") for x in leagues[0].get("calendar",[])
                 if "2026-07-01"<=x[:10]<CUTOFF})
    if not 15<=len(days)<=85:
        raise ItalianArchiveProblem("Unexpected Italian calendar coverage: "+str(len(days)))
    events={}
    for day in days:
        doc=get("/scoreboard?dates="+day+"&limit=50")
        for e in doc.get("events") or []:
            if not e.get("status",{}).get("type",{}).get("completed"):
                continue
            if not "2026-07-01"<=e.get("date","")[:10]<CUTOFF:continue
            events[_id(e.get("id"),MATCH_OFFSET)]=e
        if len(events)>MAX_EVENTS:raise ItalianArchiveProblem("Too many fixtures")
        if pause:time.sleep(pause)
    if len(events)!=120:
        raise ItalianArchiveProblem("Expected 120 completed Italian games through Nov 23; got "+str(len(events)))
    appearances=Counter()
    for e in events.values():
        for c in (e.get("competitions") or [{}])[0].get("competitors") or []:
            appearances[_id(c.get("team",{}).get("id"),TEAM_OFFSET)]+=1
    if len(appearances)!=20 or set(appearances.values())!={12}:
        raise ItalianArchiveProblem("Italian team fixture coverage is not 12 matches each")
    return sorted(events.values(),key=lambda x:(x["date"],int(x["id"])))

def parse_match(event, summary):
    if not event.get("status",{}).get("type",{}).get("completed"):
        raise ItalianArchiveProblem("Not a completed official fixture")
    kickoff=datetime.fromisoformat(event["date"].replace("Z","+00:00"))
    if kickoff.tzinfo is None or kickoff>=datetime(2026,11,24,tzinfo=timezone.utc):
        raise ItalianArchiveProblem("Date outside audited season snapshot")
    competitors=(event.get("competitions") or [{}])[0].get("competitors") or []
    if len(competitors)!=2:
        raise ItalianArchiveProblem("Match requires 2 competitors")
    comp={p.get("homeAway"):p for p in competitors}
    if set(comp)!={"home","away"}:
        raise ItalianArchiveProblem("Home and away assignment missing")
    groups=summary.get("rosters") or []
    if len(groups)!=2:
        raise ItalianArchiveProblem("Both historical team rosters required")
    sides={}
    for side in ("home","away"):
        c=comp[side]
        tid=_id(c.get("team",{}).get("id"),TEAM_OFFSET)
        group=next((g for g in groups if g.get("homeAway")==side),None)
        if group is None or _id(group.get("team",{}).get("id"),TEAM_OFFSET)!=tid:
            raise ItalianArchiveProblem("ESPN roster team id mismatches fixture")
        name=(c.get("team",{}).get("displayName") or "").strip()
        if not name:raise ItalianArchiveProblem("Team without name")
        roster=group.get("roster") or []
        starters=[p for p in roster if p.get("starter") is True]
        if len(starters)!=11:
            raise ItalianArchiveProblem("Team has not exactly 11 explicit starters")
        normalized=[]
        for p in starters:
            athlete=p.get("athlete") or {}
            pid=_id(athlete.get("id"),PLAYER_OFFSET)
            pname=(athlete.get("displayName") or "").strip()
            if not pname:raise ItalianArchiveProblem("Starter without real name")
            code=(p.get("position") or {}).get("abbreviation")
            shirt=p.get("jersey")
            shirt=int(shirt) if str(shirt or "").isdigit() else None
            normalized.append({"player_id":pid,"player_name":pname,
                               "position_code":code,"shirt_number":shirt})
        if len({x["player_id"] for x in normalized})!=11:
            raise ItalianArchiveProblem("Duplicate athlete in starting XI")
        codes=[p["position_code"] for p in normalized]
        all_unknown=all(code=="SUB" for code in codes)
        if all_unknown:
            # ESPN source bug: confirmed XI has position=SUB across all starters.
            # Keep starter membership but NEVER guess the positions.
            for p in normalized:p["position_code"]=None
        elif all(code in ROLE for code in codes):
            try:
                pitch_from_codes(normalized)
            except (ValueError, KeyError):
                all_unknown=True
                for p in normalized:p["position_code"]=None
        else:
            # Starter membership is explicit; unverified tactical positions stay null.
            all_unknown=True
            for p in normalized:p["position_code"]=None
        sides[side]={"id":tid,"name":name,"players":normalized,
                     "position_unavailable":all_unknown}
    if sides["home"]["id"]==sides["away"]["id"]:
        raise ItalianArchiveProblem("Duplicate team in match")
    return {
        "match_id":_id(event["id"],MATCH_OFFSET),"season_year":2026,
        "competition_code":LEAGUE,"kickoff_utc":kickoff,
        "local_date":kickoff.astimezone(ITALIAN_TZ).date(),
        "home":sides["home"],"away":sides["away"],
        "position_unavailable":(sides["home"]["position_unavailable"] or
                                sides["away"]["position_unavailable"])
    }

def gather_snapshot(get=fetch,pause=0.16,log=print):
    events=discover_games(get=get,pause=pause)
    matches=[]
    for i,e in enumerate(events):
        doc=get("/summary?event="+str(e["id"]))
        matches.append(parse_match(e,doc))
        if (i+1)%15==0:log("Italian confirmed lineups: %d / %d audited" %(i+1,len(events)))
        if pause:time.sleep(pause)
    return matches

# Do not mix provider IDs: retain the existing 11footy team and player IDs
# when the same player can be matched in a previously archived starting XI.
ALIASES={"inter":"internazionale","inter milan":"internazionale","fc internazionale":"internazionale",
         "milan":"ac milan","roma":"as roma","ss lazio":"lazio","ssc napoli":"napoli",
         "atalanta bc":"atalanta","como 1907":"como","hellas verona":"verona",
         "ac monza":"monza","ac fiorentina":"fiorentina","genoa cfc":"genoa",
         "parma calcio":"parma","venezia fc":"venezia","frosinone calcio":"frosinone",
         "bologna fc":"bologna","us lecce":"lecce","udinese calcio":"udinese",
         "torino fc":"torino","us sassuolo":"sassuolo","cagliari calcio":"cagliari"}

def norm(value):
    raw=unicodedata.normalize("NFKD",str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+","".join(c for c in raw if not unicodedata.combining(c))))
def team_key(value):
    key=norm(value)
    if key.endswith(" fc"):key=key[:-3]
    return ALIASES.get(key,key)
def compatible(a,b):
    a,b=norm(a),norm(b)
    if not a or not b:return False
    if a==b:return True
    aa,bb=set(a.split()),set(b.split())
    return bool(aa and bb and (aa<=bb or bb<=aa) and any(len(x)>=4 for x in aa&bb))
def bind(mapping,reverse,new,old):
    if new in mapping and mapping[new]!=old:
        raise ItalianArchiveProblem(f"Ambiguous source player {new}: {mapping[new]} versus {old}")
    if old in reverse and reverse[old]!=new:
        raise ItalianArchiveProblem(f"Ambiguous historical player {old}: {reverse[old]} versus {new}")
    mapping[new]=old
    reverse[old]=new

def import_all(log=print):
    if not season_db.enabled():raise ItalianArchiveProblem("Lineup Lens Neon not connected")
    with season_db.db() as db:
        existing=db.execute("SELECT imported_matches FROM archive_import_state WHERE source=%s AND release_name=%s AND competition_code=%s",(SOURCE,RELEASE,LEAGUE)).fetchone()
        if existing:return {"status":"already_imported","matches":existing["imported_matches"]}
        previous=db.execute("SELECT m.match_id,m.kickoff_utc,m.local_date,m.home_team_id,m.away_team_id,h.team_name home_name,a.team_name away_name FROM archive_matches m JOIN archive_teams h ON h.team_id=m.home_team_id JOIN archive_teams a ON a.team_id=m.away_team_id WHERE m.competition_code=%s AND m.season_year=2026 ORDER BY m.kickoff_utc",(LEAGUE,)).fetchall()
        old_starters=db.execute("SELECT s.match_id,s.team_id,s.player_id,s.jersey_number,p.player_name FROM archive_starters s JOIN archive_matches m ON m.match_id=s.match_id JOIN archive_players p ON p.player_id=s.player_id WHERE m.competition_code=%s AND m.season_year=2026",(LEAGUE,)).fetchall()
    if len(previous)!=110 or len(old_starters)!=2420:raise ItalianArchiveProblem("Unexpected baseline size; refusing to append")
    matches=gather_snapshot(log=log)
    old_by_pair={}
    old_xi=defaultdict(list)
    old_people={}
    for m in previous:
        pair=(team_key(m["home_name"]),team_key(m["away_name"]))
        if pair in old_by_pair:raise ItalianArchiveProblem("Duplicate historical fixture")
        old_by_pair[pair]=m
    for p in old_starters:
        old_xi[(p["match_id"],p["team_id"])].append(p)
        old_people[p["player_id"]]=p["player_name"]
    cross,reverse,teams={}, {}, {}
    historical_ids=set()
    historical_unmatched=set()
    covered=set()
    delta=[]
    for m in matches:
        h,a=m["home"],m["away"]
        pair=(team_key(h["name"]),team_key(a["name"]))
        old=old_by_pair.get(pair)
        if old is None:
            if str(m["local_date"])<="2026-11-08":
                raise ItalianArchiveProblem("Old fixture not identified: "+str(pair))
            delta.append(m)
            continue
        if str(old["local_date"])!=str(m["local_date"]):
            raise ItalianArchiveProblem("Historical fixture date mismatch: "+str(pair))
        if old["match_id"] in covered:raise ItalianArchiveProblem("Duplicate source fixture")
        covered.add(old["match_id"])
        for side in ("home","away"):
            team=m[side]; tid=old[side+"_team_id"]
            if team["id"] in teams and teams[team["id"]]!=tid:raise ItalianArchiveProblem("Team identity conflict")
            teams[team["id"]]=tid
            roster=old_xi[(old["match_id"],tid)]
            for p in team["players"]:
                pid=p["player_id"];historical_ids.add(pid)
                same=[r for r in roster if norm(r["player_name"])==norm(p["player_name"])]
                if len(same)!=1:
                    same=[r for r in roster if r["jersey_number"] is not None and r["jersey_number"]==p["shirt_number"] and compatible(r["player_name"],p["player_name"])]
                if len(same)==1:
                    bind(cross,reverse,pid,same[0]["player_id"])
                else:historical_unmatched.add(pid)
    if len(covered)!=110 or len(delta)!=10 or len(teams)!=20 or len(set(teams.values()))!=20:
        raise ItalianArchiveProblem(f"Coverage mismatch: overlap={len(covered)}, new={len(delta)}, teams={len(teams)}")
    print(f"SA identity audit: {len(covered)} archived fixtures, {len(cross)} matched players; {len(historical_unmatched-cross.keys())} unmatched historical source IDs",flush=True)
    game_rows=[];starter_rows=[];new_people={};new_names={}
    for m in delta:
        h,a=m["home"],m["away"]
        if h["id"] not in teams or a["id"] not in teams:raise ItalianArchiveProblem("Unknown delta team")
        game_rows.append((m["match_id"],2026,LEAGUE,m["kickoff_utc"],m["local_date"],teams[h["id"]],teams[a["id"]],RELEASE))
        for team in (h,a):
            tid=teams[team["id"]]; seen=set()
            for p in team["players"]:
                pid=p["player_id"]
                if pid in cross:
                    final_id=cross[pid]
                elif pid in historical_ids:
                    raise ItalianArchiveProblem(f"Unresolved previously starting player: {team['name']} / {p['player_name']} / {pid}")
                else:
                    # A new source ID is admissible only if no historical name
                    # could be confused with it. Ambiguity is an explicit blocker.
                    possible=[old_id for old_id,name in old_people.items() if compatible(name,p["player_name"])]
                    if possible:raise ItalianArchiveProblem(f"Unresolved possible existing player: {team['name']} / {p['player_name']} / {possible}")
                    final_id=pid
                    key=norm(p["player_name"])
                    if key in new_names and new_names[key]!=pid:raise ItalianArchiveProblem("Ambiguous new player name")
                    new_names[key]=pid
                    new_people[pid]=p["player_name"]
                if final_id in seen:raise ItalianArchiveProblem("Duplicate player after identity mapping")
                seen.add(final_id)
                starter_rows.append((m["match_id"],tid,final_id,p["position_code"],p["shirt_number"]))
            if len(seen)!=11:raise ItalianArchiveProblem("Invalid mapped XI")
    if len(game_rows)!=10 or len(starter_rows)!=220:raise ItalianArchiveProblem("Delta count mismatch")
    with season_db.db() as db:
        with db.cursor() as c:
            # Historical data must remain exactly as it was when we started.
            baseline=db.execute("SELECT count(*) n FROM archive_matches WHERE competition_code=%s AND season_year=2026",(LEAGUE,)).fetchone()
            if baseline["n"]!=110:raise ItalianArchiveProblem("Baseline changed")
            for pid,name in new_people.items():
                row=db.execute("SELECT player_name FROM archive_players WHERE player_id=%s",(pid,)).fetchone()
                if row and norm(row["player_name"])!=norm(name):raise ItalianArchiveProblem("New source player ID collision")
            ids=[r[0] for r in game_rows]
            collision=db.execute("SELECT match_id FROM archive_matches WHERE match_id=ANY(%s) LIMIT 1",(ids,)).fetchone()
            if collision:raise ItalianArchiveProblem("New fixture ID already exists")
            c.executemany("INSERT INTO archive_players(player_id,player_name) VALUES(%s,%s) ON CONFLICT(player_id) DO NOTHING",list(new_people.items()))
            c.executemany("INSERT INTO archive_matches(match_id,season_year,competition_code,kickoff_utc,local_date,home_team_id,away_team_id,source_release) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",game_rows)
            c.executemany("INSERT INTO archive_starters(match_id,team_id,player_id,position_code,jersey_number) VALUES(%s,%s,%s,%s,%s)",starter_rows)
            check=db.execute("SELECT count(*) n FROM (SELECT s.match_id,s.team_id FROM archive_starters s JOIN archive_matches m USING(match_id) WHERE m.competition_code=%s AND m.season_year=2026 GROUP BY s.match_id,s.team_id HAVING count(*)=11 AND count(distinct player_id)=11) q",(LEAGUE,)).fetchone()
            if check["n"]!=240:raise ItalianArchiveProblem("Full-season XI validation failed")
            c.execute("INSERT INTO archive_import_state(source,release_name,competition_code,state,imported_matches,last_match_date) VALUES(%s,%s,%s,'complete',%s,%s)",(SOURCE,RELEASE,LEAGUE,len(game_rows),max(m["local_date"] for m in delta)))
    print(f"SA delta committed: 10 fixtures, 220 starters, {len(new_people)} new players; total 120 fixtures",flush=True)
    return {"status":"complete","added":10,"total":120,"starters":220,"new_players":len(new_people)}
