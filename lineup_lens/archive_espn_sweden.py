"""Private Swedish Allsvenskan ESPN confirmed-XI snapshot into Lineup Lens Neon.

Source: ESPN site soccer scoreboard and match summary, Swedish Allsvenskan
swe.1, 2026. Publicly accessible (unofficial) endpoints; research use only.
No scraping of predictions, no paid API, no SharpVision/PINNACLE operations.

ESPN occasionally labels EVERY confirmed starter's position "SUB" in a few
matches. Count the 11 explicitly marked starter=True, but store position=NULL
rather than guessing a tactical role for these games. NEVER label those pitch
positions as verified. Match archive includes all confirmed lineups and a
separately verified last dated match pitch for each team.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import time
from urllib.request import Request, urlopen

import season_db
from archive_pitch import ROLE, pitch_from_codes

SOURCE="espn"
LEAGUE="SE1"
RELEASE="espn-swe1-2026-11-24"
BASE="https://site.api.espn.com/apis/site/v2/sports/soccer/swe.1"
CUTOFF="2026-11-24"
SWEDISH_TZ=ZoneInfo("Europe/Stockholm")
TEAM_OFFSET=1_000_000_000
PLAYER_OFFSET=1_500_000_000
MATCH_OFFSET=500_000_000
MAX_EVENTS=232
MAX_JSON=2_300_000

class SwedishArchiveProblem(ValueError):
    pass

def fetch(route):
    """Bounded fixed-host GET; never accepts a user-supplied URL."""
    if not route.startswith(("/scoreboard?dates=", "/summary?event=")):
        raise SwedishArchiveProblem("Unexpected ESPN route")
    req=Request(BASE+route,headers={"User-Agent":"LineupLens-Personal-Research/1.0"})
    with urlopen(req,timeout=24) as result:
        raw=result.read(MAX_JSON+1)
    if len(raw)>MAX_JSON:raise SwedishArchiveProblem("Oversized ESPN JSON")
    return json.loads(raw)

def _id(value,offset):
    if isinstance(value,bool) or not str(value or "").isdigit():
        raise SwedishArchiveProblem("Missing ESPN numeric ID")
    val=int(value)
    # ESPN event IDs are ~400 million; team/player IDs use smaller ranges.
    upper=500_000_000 if offset==MATCH_OFFSET else 100_000_000
    if val<=0 or val>=upper:
        raise SwedishArchiveProblem("ESPN ID exceeds reserved namespace")
    if offset+val>2_147_483_647:
        raise SwedishArchiveProblem("ESPN ID cannot fit PostgreSQL INT")
    return offset+val

def discover_games(get=fetch, pause=0.16):
    payload=get("/scoreboard?dates=20261123&limit=50")
    leagues=payload.get("leagues") or []
    if len(leagues)!=1 or leagues[0].get("slug")!="swe.1":
        raise SwedishArchiveProblem("Could not verify ESPN Swedish league")
    if (leagues[0].get("season") or {}).get("year")!=2026:
        raise SwedishArchiveProblem("ESPN season mismatch")
    days=sorted({x[:10].replace("-","") for x in leagues[0].get("calendar",[])
                 if "2026-01-01"<=x[:10]<CUTOFF})
    if not 25<=len(days)<=180:
        raise SwedishArchiveProblem("Unexpected Swedish calendar coverage: "+str(len(days)))
    events={}
    for day in days:
        doc=get("/scoreboard?dates="+day+"&limit=50")
        for e in doc.get("events") or []:
            if not e.get("status",{}).get("type",{}).get("completed"):
                continue
            if not "2026-01-01"<=e.get("date","")[:10]<CUTOFF:continue
            events[_id(e.get("id"),MATCH_OFFSET)]=e
        if len(events)>MAX_EVENTS:raise SwedishArchiveProblem("Too many fixtures")
        if pause:time.sleep(pause)
    if len(events)!=232:
        raise SwedishArchiveProblem("Expected 232 completed Swedish games through Nov 23; got "+str(len(events)))
    appearances=Counter()
    for e in events.values():
        for c in (e.get("competitions") or [{}])[0].get("competitors") or []:
            appearances[_id(c.get("team",{}).get("id"),TEAM_OFFSET)]+=1
    if len(appearances)!=16 or set(appearances.values())!={29}:
        raise SwedishArchiveProblem("Swedish team fixture coverage is not 29 matches each")
    return sorted(events.values(),key=lambda x:(x["date"],int(x["id"])))

# Two distinct real players share the same name. Local archive IDs are
# explicitly reserved outside the ESPN ID namespace; not fake ESPN IDs.
# Club confirmation: https://degerforsif.se/nyheter/
# Independently verified starting shirt numbers in the seven affected fixtures.
VERIFIED_DEGERFORS_XI = {
    # Eurosport: https://www.eurosport.fr/football/allsvenskan/2026/live-degerfors-if-malmoe-ff_mtc1657722/live-lineup.shtml
    401842743: {4,6,7,8,14,16,17,18,20,22,38},
    # https://www.csports.se/allsvenskan/matcher/vasteras-sk-fk-mot-degerfors-if-2026-07-12
    401842746: {4,6,7,8,14,16,17,18,20,22,38},
    # https://www.csports.se/allsvenskan/matcher/hammarby-ff-mot-degerfors-if-2026-07-19
    401842760: {3,4,8,11,13,16,17,18,20,23,38},
    # https://www.csports.se/allsvenskan/matcher/degerfors-if-mot-ifk-goteborg-2026-08-16
    401842787: {2,3,4,8,11,16,17,18,20,23,38},
    # https://www.ballwhizz.net/en/matches/8404
    401842795: {2,3,8,11,16,17,18,20,22,23,38},
    # https://betsgo-global.com/en/matches/degerfors-vs-hammarby-20260920-4meby5/
    401842827: {2,3,6,8,9,10,11,13,16,22,38},
    # https://www.fotboll-idag.com/matcher/17370-degerfors-vs-kalmar
    401842846: {2,3,6,8,10,11,13,16,17,22,38},
}
OHLS_IDS={7:1800000007,16:1800000016}
def _is_ohlsson(p):
    name=((p.get("athlete") or {}).get("displayName") or "").lower()
    return "sebastian" in name and ("ohlsson" in name or "olsson" in name)

def _shirt(p):
    s=p.get("jersey")
    return int(s) if str(s or "").isdigit() else None

def _ohlsson(number):
    return {"player_id":OHLS_IDS[number],
            "player_name":f"Sebastian Ohlsson (#{number})",
            "position_code":None,"shirt_number":number}

def _verified_degerfors_starters(event, roster):
    expected=VERIFIED_DEGERFORS_XI.get(int(event["id"]))
    if expected is None:return None
    # Match the ten/nine other starters with independently checked shirt numbers.
    others=[p for p in roster if p.get("starter") is True and not _is_ohlsson(p)]
    shirts=[_shirt(p) for p in others]
    if len(shirts)!=len(set(shirts)) or set(shirts)!=expected-{7,16}:
        raise SwedishArchiveProblem("Independent XI disagrees with ESPN non-Ohlsson starters")
    return others, sorted(expected & {7,16})

def parse_match(event, summary, cutoff=None):
    if not event.get("status",{}).get("type",{}).get("completed"):
        raise SwedishArchiveProblem("Not a completed official fixture")
    kickoff=datetime.fromisoformat(event["date"].replace("Z","+00:00"))
    if kickoff.tzinfo is None or kickoff>=(cutoff or datetime(2026,11,24,tzinfo=timezone.utc)):
        raise SwedishArchiveProblem("Date outside audited season snapshot")
    competitors=(event.get("competitions") or [{}])[0].get("competitors") or []
    if len(competitors)!=2:
        raise SwedishArchiveProblem("Match requires 2 competitors")
    comp={p.get("homeAway"):p for p in competitors}
    if set(comp)!={"home","away"}:
        raise SwedishArchiveProblem("Home and away assignment missing")
    groups=summary.get("rosters") or []
    if len(groups)!=2:
        raise SwedishArchiveProblem("Both historical team rosters required")
    sides={}
    for side in ("home","away"):
        c=comp[side]
        tid=_id(c.get("team",{}).get("id"),TEAM_OFFSET)
        group=next((g for g in groups if g.get("homeAway")==side),None)
        if group is None or _id(group.get("team",{}).get("id"),TEAM_OFFSET)!=tid:
            raise SwedishArchiveProblem("ESPN roster team id mismatches fixture")
        name=(c.get("team",{}).get("displayName") or "").strip()
        if not name:raise SwedishArchiveProblem("Team without name")
        roster=group.get("roster") or []
        starters=[p for p in roster if p.get("starter") is True]
        is_degerfors="degerfors" in name.lower()
        correction=_verified_degerfors_starters(event,roster) if is_degerfors else None
        if correction is not None:
            starters, known_ohlssons=correction
        else:
            known_ohlssons=[]
            if len(starters)!=11:
                raise SwedishArchiveProblem(f"{name}: {len(starters)} explicit starters (roster {len(roster)})")
        normalized=[_ohlsson(n) for n in known_ohlssons]
        for p in starters:
            athlete=p.get("athlete") or {}
            pid=_id(athlete.get("id"),PLAYER_OFFSET)
            pname=(athlete.get("displayName") or "").strip()
            if not pname:raise SwedishArchiveProblem("Starter without real name")
            code=(p.get("position") or {}).get("abbreviation")
            shirt=p.get("jersey")
            shirt=int(shirt) if str(shirt or "").isdigit() else None
            if is_degerfors and _is_ohlsson(p):
                if shirt not in OHLS_IDS:
                    raise SwedishArchiveProblem("Ambiguous Ohlsson shirt number")
                pid=OHLS_IDS[shirt]
                pname=f"Sebastian Ohlsson (#{shirt})"
            normalized.append({"player_id":pid,"player_name":pname,
                               "position_code":code,"shirt_number":shirt})
        if len(normalized)!=11 or len({x["player_id"] for x in normalized})!=11:
            raise SwedishArchiveProblem("Duplicate athlete in starting XI")
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
        raise SwedishArchiveProblem("Duplicate team in match")
    return {
        "match_id":_id(event["id"],MATCH_OFFSET),"season_year":2026,
        "competition_code":LEAGUE,"kickoff_utc":kickoff,
        "local_date":kickoff.astimezone(SWEDISH_TZ).date(),
        "home":sides["home"],"away":sides["away"],
        "position_unavailable":(sides["home"]["position_unavailable"] or
                                sides["away"]["position_unavailable"])
    }

def gather_snapshot(get=fetch,pause=0.16,log=print):
    events=discover_games(get=get,pause=pause)
    matches=[]
    failures=[]
    for i,e in enumerate(events):
        try:
            doc=get("/summary?event="+str(e["id"]))
            matches.append(parse_match(e,doc))
        except (SwedishArchiveProblem, ValueError, KeyError) as err:
            detail=f"Swedish XI audit failed: ESPN event {e.get('id')} | {e.get('date')} | {e.get('name')} | {err}"
            failures.append(detail)
            print(detail,flush=True)
        if (i+1)%30==0:print(f"Swedish XI audit: {i+1}/{len(events)}, valid={len(matches)}, failures={len(failures)}",flush=True)
        if pause:time.sleep(pause)
    if failures:
        raise SwedishArchiveProblem(f"Swedish audit incomplete: {len(matches)}/{len(events)} verified; {len(failures)} failed. No archive writes.")
    return matches

def import_all(log=print):
    """Whole season snapshot or no write, with transactional Neon commit."""
    if not season_db.enabled():raise SwedishArchiveProblem("Lineup Lens Neon not connected")
    with season_db.db() as db:
        for number,pid in OHLS_IDS.items():
            existing=db.execute("SELECT player_name FROM archive_players WHERE player_id=%s",(pid,)).fetchone()
            if existing and existing["player_name"]!=_ohlsson(number)["player_name"]:
                raise SwedishArchiveProblem("Reserved local player ID collision")
        row=db.execute(
            "SELECT imported_matches FROM archive_import_state "
            "WHERE source=%s AND release_name=%s AND competition_code=%s",
            (SOURCE,RELEASE,LEAGUE)).fetchone()
        if row:
            log("Swedish Allsvenskan already imported (%d games)"%row["imported_matches"])
            return {"status":"already_imported","matches":row["imported_matches"]}
    matches=gather_snapshot(log=log)
    if not all(len(m["home"]["players"])==11 and len(m["away"]["players"])==11 for m in matches):
        raise SwedishArchiveProblem("Aborting inconsistent Swedish archive")
    teams={};players={};game_rows=[];starter_rows=[]
    unknown=0
    for m in matches:
        game_rows.append((m["match_id"],2026,LEAGUE,m["kickoff_utc"],m["local_date"],
                          m["home"]["id"],m["away"]["id"],RELEASE))
        unknown+=int(m["position_unavailable"])
        for side in ("home","away"):
            team=m[side]
            teams[team["id"]]=(team["id"],team["name"],"Sweden")
            for p in team["players"]:
                players[p["player_id"]]=(p["player_id"],p["player_name"])
                starter_rows.append((m["match_id"],team["id"],p["player_id"],
                                     p["position_code"],p["shirt_number"]))
    if len(starter_rows)!=len(matches)*22 or len(teams)!=16:
        raise SwedishArchiveProblem("Aborting Swedish import due to bad counts")
    with season_db.db() as db:
        with db.cursor() as c:
            c.executemany("INSERT INTO archive_players(player_id,player_name) "
                          "VALUES(%s,%s) ON CONFLICT(player_id) "
                          "DO UPDATE SET player_name=EXCLUDED.player_name",list(players.values()))
            c.executemany("INSERT INTO archive_teams(team_id,team_name,country) "
                          "VALUES(%s,%s,%s) ON CONFLICT(team_id) DO UPDATE "
                          "SET team_name=EXCLUDED.team_name,country=EXCLUDED.country",
                          list(teams.values()))
            c.executemany("INSERT INTO archive_matches(match_id,season_year,"
                          "competition_code,kickoff_utc,local_date,home_team_id,"
                          "away_team_id,source_release) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                          "ON CONFLICT(match_id) DO NOTHING",game_rows)
            c.executemany("INSERT INTO archive_starters(match_id,team_id,player_id,"
                          "position_code,jersey_number) VALUES(%s,%s,%s,%s,%s) "
                          "ON CONFLICT(match_id,team_id,player_id) DO NOTHING",starter_rows)
            c.execute("INSERT INTO archive_import_state(source,release_name,"
                      "competition_code,state,imported_matches,last_match_date) "
                      "VALUES(%s,%s,%s,'complete',%s,%s) ON CONFLICT DO NOTHING",
                      (SOURCE,RELEASE,LEAGUE,len(matches),
                       max(m["local_date"] for m in matches)))
    result={"source":SOURCE,"release":RELEASE,"matches":len(matches),
            "clubs":len(teams),"starter_rows":len(starter_rows),
            "games_with_unknown_positions":unknown,
            "latest_date":str(max(m["local_date"] for m in matches))}
    log("Swedish Allsvenskan actual Neon import: "+str(result))
    return result
