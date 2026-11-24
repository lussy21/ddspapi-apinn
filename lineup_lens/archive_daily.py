"""Private daily incremental XI archive. No Soccer Data requests.
The existing historical snapshot is never replaced. Mixed-source identities are
seeded from verified overlapping fixtures, then persisted in Neon.
Calendar-year leagues stop at year end; the remaining leagues stop 30 June 2027.
A free Render instance can sleep; on wake the stored cursor catches up.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import importlib
import time
from zoneinfo import ZoneInfo
import season_db
from archive_pitch import ROLE, pitch_from_codes
from archive_espn_pl_delta import norm, compatible, bind
from archive_espn_sweden import parse_match as parse_sweden

ATHENS=ZoneInfo("Europe/Athens")
START=date(2026,11,23)
LOCK=614439840
TEAM_OFFSET=1_000_000_000
PLAYER_OFFSET=1_500_000_000
MATCH_OFFSET=500_000_000
MODULES={
    "PL":("pl_delta","Europe/London"),"SA":("sa_delta","Europe/Rome"),
    "LL":("ll_delta","Europe/Madrid"),"BL":("bl_delta","Europe/Berlin"),
    "L1":("l1_delta","Europe/Paris"),"GR1":("greece","Europe/Athens"),
    "BE1":("belgium","Europe/Brussels"),"DK1":("denmark","Europe/Copenhagen"),
    "DE2":("germany2","Europe/Berlin"),"NO1":("norway","Europe/Oslo"),
    "NL1":("netherlands","Europe/Amsterdam"),"TR1":("turkey","Europe/Istanbul"),
    "SC1":("scotland","Europe/London"),"SE1":("sweden","Europe/Stockholm"),
    "UCL":("ucl","Europe/Zurich"),"UEL":("uel","Europe/Zurich"),
    "UECL":("uecl","Europe/Zurich"),
}
MIXED={"PL","SA","LL","BL","L1"}

class DailyProblem(ValueError):
    pass

def source_id(value,offset):
    if isinstance(value,bool) or not str(value or "").isdigit():raise DailyProblem("Invalid ESPN ID")
    n=int(value)
    if not 0<n<(500_000_000 if offset==MATCH_OFFSET else 100_000_000):raise DailyProblem("ESPN ID outside namespace")
    return offset+n

def parse_new(event, summary, league, tz):
    if not event.get("status",{}).get("type",{}).get("completed"):
        raise DailyProblem("Not a completed official fixture")
    kickoff=datetime.fromisoformat(event["date"].replace("Z","+00:00"))
    if kickoff.tzinfo is None or kickoff>datetime.now(timezone.utc):
        raise DailyProblem("Date outside audited season snapshot")
    competitors=(event.get("competitions") or [{}])[0].get("competitors") or []
    if len(competitors)!=2:
        raise DailyProblem("Match requires 2 competitors")
    comp={p.get("homeAway"):p for p in competitors}
    if set(comp)!={"home","away"}:
        raise DailyProblem("Home and away assignment missing")
    groups=summary.get("rosters") or []
    if len(groups)!=2:
        raise DailyProblem("Both historical team rosters required")
    sides={}
    for side in ("home","away"):
        c=comp[side]
        tid=source_id(c.get("team",{}).get("id"),TEAM_OFFSET)
        group=next((g for g in groups if g.get("homeAway")==side),None)
        if group is None or source_id(group.get("team",{}).get("id"),TEAM_OFFSET)!=tid:
            raise DailyProblem("ESPN roster team id mismatches fixture")
        name=(c.get("team",{}).get("displayName") or "").strip()
        if not name:raise DailyProblem("Team without name")
        roster=group.get("roster") or []
        starters=[p for p in roster if p.get("starter") is True]
        if len(starters)!=11:
            raise DailyProblem("Team has not exactly 11 explicit starters")
        normalized=[]
        for p in starters:
            athlete=p.get("athlete") or {}
            pid=source_id(athlete.get("id"),PLAYER_OFFSET)
            pname=(athlete.get("displayName") or "").strip()
            if not pname:raise DailyProblem("Starter without real name")
            code=(p.get("position") or {}).get("abbreviation")
            shirt=p.get("jersey")
            shirt=int(shirt) if str(shirt or "").isdigit() else None
            normalized.append({"player_id":pid,"player_name":pname,
                               "position_code":code,"shirt_number":shirt})
        if len({x["player_id"] for x in normalized})!=11:
            raise DailyProblem("Duplicate athlete in starting XI")
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
        raise DailyProblem("Duplicate team in match")
    return {
        "match_id":source_id(event["id"],MATCH_OFFSET),"season_year":2026,
        "competition_code":league,"kickoff_utc":kickoff,
        "local_date":kickoff.astimezone(tz).date(),
        "home":sides["home"],"away":sides["away"],
        "position_unavailable":(sides["home"]["position_unavailable"] or
                                sides["away"]["position_unavailable"])
    }


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS archive_daily_state (
        competition_code text PRIMARY KEY, checked_through date NOT NULL,
        last_attempt_at timestamptz, last_success_at timestamptz,
        last_error text, seeded boolean NOT NULL DEFAULT false)""")
    db.execute("""CREATE TABLE IF NOT EXISTS archive_source_links (
        competition_code text NOT NULL, kind text NOT NULL,
        source_id integer NOT NULL, canonical_id integer NOT NULL,
        PRIMARY KEY(competition_code,kind,source_id))""")
    for league in MODULES:
        db.execute("INSERT INTO archive_daily_state(competition_code,checked_through,seeded) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                   (league,START-timedelta(days=1),league not in MIXED))

def baseline(db,league):
    games=db.execute("""SELECT m.match_id,m.local_date,m.home_team_id,m.away_team_id,
             h.team_name home_name,a.team_name away_name FROM archive_matches m
             JOIN archive_teams h ON h.team_id=m.home_team_id
             JOIN archive_teams a ON a.team_id=m.away_team_id
             WHERE m.competition_code=%s AND m.season_year=2026""",(league,)).fetchall()
    players=db.execute("""SELECT s.match_id,s.team_id,s.player_id,s.jersey_number,p.player_name
             FROM archive_starters s JOIN archive_matches m USING(match_id)
             JOIN archive_players p USING(player_id)
             WHERE m.competition_code=%s AND m.season_year=2026""",(league,)).fetchall()
    return games,players

def seed_mixed(league,mod):
    """Rebuild the one-time cross-provider links from the already audited snapshot."""
    with season_db.db() as db:
        games,players=baseline(db,league)
    if not games or len(players)!=22*len(games):raise DailyProblem("Historical baseline incomplete")
    pairs={}
    for g in games:
        k=(str(g["local_date"]),mod.team_key(g["home_name"]),mod.team_key(g["away_name"]))
        if k in pairs:raise DailyProblem("Ambiguous historical fixture")
        pairs[k]=g
    xis=defaultdict(list)
    for p in players:xis[(p["match_id"],p["team_id"])].append(p)
    teammap={};teamrev={};playmap={};playrev={};eventmap={};seen=set();unknown=set()
    snapshot=mod.gather_snapshot(log=lambda _:None)
    for m in snapshot:
        h,a=m["home"],m["away"]
        k=(str(m["local_date"]),mod.team_key(h["name"]),mod.team_key(a["name"]))
        g=pairs.get(k)
        if not g or g["match_id"] in seen:raise DailyProblem("Cannot match historical fixture "+str(k))
        seen.add(g["match_id"]);eventmap[m["match_id"]]=g["match_id"]
        for side in ("home","away"):
            team=m[side];tid=g[side+"_team_id"]
            bind(teammap,teamrev,team["id"],tid)
            old=xis[(g["match_id"],tid)]
            for p in team["players"]:
                pid=p["player_id"]
                same=[r for r in old if mod.norm(r["player_name"])==mod.norm(p["player_name"])]
                if len(same)!=1:
                    same=[r for r in old if r["jersey_number"] is not None and r["jersey_number"]==p["shirt_number"] and mod.compatible(r["player_name"],p["player_name"])]
                if len(same)==1:bind(playmap,playrev,pid,same[0]["player_id"])
                else:unknown.add(pid)
    expected={g["match_id"] for g in games if g["local_date"]<date(2026,11,24)}
    if seen!=expected:raise DailyProblem("Seed coverage mismatch")
    unknown-=playmap.keys()
    with season_db.db() as db:
        for kind,links in (("team",teammap),("player",playmap),("match",eventmap),("blocked_player",{x:x for x in unknown})):
            for source,canonical in links.items():
                db.execute("INSERT INTO archive_source_links(competition_code,kind,source_id,canonical_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",(league,kind,source,canonical))
        db.execute("UPDATE archive_daily_state SET seeded=true WHERE competition_code=%s",(league,))
    print(f"Daily archive seed {league}: {len(eventmap)} fixtures, {len(playmap)} player links, {len(unknown)} held identities",flush=True)

def get_links(db,league):
    out=defaultdict(dict)
    for r in db.execute("SELECT kind,source_id,canonical_id FROM archive_source_links WHERE competition_code=%s",(league,)).fetchall():
        out[r["kind"]][r["source_id"]]=r["canonical_id"]
    return out

def scan_day(league,mod,tz,day):
    doc=mod.fetch("/scoreboard?dates="+day.strftime("%Y%m%d")+"&limit=50")
    leagues=doc.get("leagues") or []
    if len(leagues)!=1 or leagues[0].get("slug")!=mod.BASE.rsplit("/",1)[-1]:
        raise DailyProblem("Scoreboard competition mismatch")
    if (leagues[0].get("season") or {}).get("year")!=2026:
        raise DailyProblem("Scoreboard season mismatch")
    events=doc.get("events")
    if not isinstance(events,list) or len(events)>=50:raise DailyProblem("Missing or truncated scoreboard")
    with season_db.db() as db:
        links=get_links(db,league)
        games,players=baseline(db,league)
        known_teams={g[k] for g in games for k in ("home_team_id","away_team_id")}
        known_games={g["match_id"]:g for g in games}
        previous={(g["home_team_id"],g["away_team_id"],g["local_date"]):g["match_id"] for g in games}
        people={p["player_id"]:p["player_name"] for p in players}
        if not games:raise DailyProblem("Missing baseline")
    mixed=league in MIXED
    prepared=[];new_ids={};seen_events=set();seen_pairs=set()
    for e in events:
        eid=source_id(e.get("id"),MATCH_OFFSET)
        if eid in seen_events:raise DailyProblem("Duplicate scoreboard fixture")
        seen_events.add(eid)
        status=e.get("status",{}).get("type",{})
        kickoff=datetime.fromisoformat(e["date"].replace("Z","+00:00"))
        if kickoff.tzinfo is None:raise DailyProblem("No fixture timezone")
        local=kickoff.astimezone(tz).date()
        if local!=day:continue
        if any(x in str(status.get("name","")).upper() for x in ("POSTPONED","CANCELED","CANCELLED")):continue
        if not status.get("completed"):
            raise DailyProblem(f"Fixture not final yet: {eid}")
        if eid in links["match"]:
            if links["match"][eid] not in known_games:raise DailyProblem("Broken fixture link")
            continue
        if eid in known_games:continue
        doc=mod.fetch("/summary?event="+str(e["id"]))
        if league=="SE1":
            m=parse_sweden(e,doc,cutoff=datetime.now(timezone.utc))
        else:m=parse_new(e,doc,league,tz)
        if m["local_date"]!=day:raise DailyProblem("Match day mismatch")
        for side in ("home","away"):
            team=m[side]
            if mixed:
                tid=links["team"].get(team["id"])
            else:tid=team["id"]
            if tid not in known_teams:raise DailyProblem("Unknown team in "+league+": "+team["name"])
            team["id"]=tid
            ids=set()
            for p in team["players"]:
                pid=p["player_id"];name=p["player_name"]
                if mixed and pid in links["blocked_player"]:raise DailyProblem("Unresolved historical source identity: "+name)
                canonical=links["player"].get(pid,pid) if mixed else pid
                namematch=mod.compatible if mixed else compatible
                if canonical in people:
                    if not namematch(people[canonical],name):raise DailyProblem("Player identity conflict: "+name)
                else:
                    # A new identity must not shadow an existing historical name.
                    candidates=[old for old,oldname in people.items() if namematch(oldname,name)]
                    if candidates:raise DailyProblem("New ID may duplicate historical player: "+name)
                    if canonical in new_ids and norm(new_ids[canonical])!=norm(name):
                        raise DailyProblem("New source ID conflict")
                    new_ids[canonical]=name
                    people[canonical]=name
                if canonical in ids:raise DailyProblem("Duplicate canonical XI player")
                ids.add(canonical)
                p["player_id"]=canonical
            if len(ids)!=11:raise DailyProblem("Expected 11 unique starters")
        pair=(m["home"]["id"],m["away"]["id"],day)
        if pair in previous or pair in seen_pairs:raise DailyProblem("Possible duplicate fixture: "+str(pair))
        seen_pairs.add(pair)
        prepared.append(m)
        time.sleep(.16)
    release="espn-daily-"+day.isoformat()
    with season_db.db() as db:
        for pid,name in new_ids.items():
            row=db.execute("SELECT player_name FROM archive_players WHERE player_id=%s",(pid,)).fetchone()
            if row and norm(row["player_name"])!=norm(name):raise DailyProblem("Shared player ID conflict")
            db.execute("INSERT INTO archive_players(player_id,player_name) VALUES(%s,%s) ON CONFLICT DO NOTHING",(pid,name))
        for m in prepared:
            mid=m["match_id"];h=m["home"];a=m["away"]
            db.execute("INSERT INTO archive_matches(match_id,season_year,competition_code,kickoff_utc,local_date,home_team_id,away_team_id,source_release) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",(mid,2026,league,m["kickoff_utc"],day,h["id"],a["id"],release))
            for team in (h,a):
                for p in team["players"]:
                    db.execute("INSERT INTO archive_starters(match_id,team_id,player_id,position_code,jersey_number) VALUES(%s,%s,%s,%s,%s)",(mid,team["id"],p["player_id"],p["position_code"],p["shirt_number"]))
            rows=db.execute("SELECT team_id,count(*) n,count(distinct player_id) unique_players FROM archive_starters WHERE match_id=%s GROUP BY team_id",(mid,)).fetchall()
            if {r["team_id"] for r in rows}!={h["id"],a["id"]} or any(r["n"]!=11 or r["unique_players"]!=11 for r in rows):
                raise DailyProblem("Transactional XI validation failed")
        if prepared:
            db.execute("INSERT INTO archive_import_state(source,release_name,competition_code,state,imported_matches,last_match_date) VALUES('espn',%s,%s,'complete',%s,%s)",(release,league,len(prepared),day))
        db.execute("UPDATE archive_daily_state SET checked_through=%s,last_success_at=now(),last_error=NULL WHERE competition_code=%s",(day,league))
    print(f"Daily archive {league} {day}: {len(prepared)} added, {len(events)} scoreboard fixtures",flush=True)
    return len(prepared)

def tick(force=False):
    now=datetime.now(ATHENS)
    if now.hour<11 and not force:return
    yesterday=now.date()-timedelta(days=1)
    with season_db.db() as lockdb:
        if not lockdb.execute("SELECT pg_try_advisory_lock(%s) acquired",(LOCK,)).fetchone()["acquired"]:return
        try:
            with season_db.db() as db:setup(db)
            for league,(module,tzname) in MODULES.items():
                # Never mix the 2026 calendar season with 2027, or 2026/27 with 2027/28.
                end=date(2026,12,31) if league in ("NO1","SE1") else date(2027,6,30)
                target=min(yesterday,end)
                with season_db.db() as db:
                    row=db.execute("SELECT * FROM archive_daily_state WHERE competition_code=%s",(league,)).fetchone()
                    if row["seeded"] and row["checked_through"]>=target:continue
                    if not force and row["last_attempt_at"] and (datetime.now(timezone.utc)-row["last_attempt_at"]).total_seconds()<3600:continue
                    db.execute("UPDATE archive_daily_state SET last_attempt_at=now() WHERE competition_code=%s",(league,))
                try:
                    mod=importlib.import_module("archive_espn_"+module)
                    if not row["seeded"]:seed_mixed(league,mod)
                    day=row["checked_through"]+timedelta(days=1)
                    for _ in range(7):
                        if day>target:break
                        scan_day(league,mod,ZoneInfo(tzname),day)
                        day+=timedelta(days=1)
                except Exception as exc:
                    msg=f"{type(exc).__name__}: {exc}"[:350]
                    print(f"Daily archive {league} held: {msg}",flush=True)
                    with season_db.db() as db:
                        db.execute("UPDATE archive_daily_state SET last_error=%s WHERE competition_code=%s",(msg,league))
        finally:
            lockdb.execute("SELECT pg_advisory_unlock(%s)",(LOCK,))

def status():
    with season_db.db() as db:
        if not db.execute("SELECT to_regclass('archive_daily_state') present").fetchone()["present"]:return []
        return db.execute("SELECT competition_code,checked_through,seeded,last_attempt_at,last_success_at,last_error FROM archive_daily_state ORDER BY competition_code").fetchall()

def loop():
    while True:
        try:tick()
        except Exception as exc:print("Daily archive loop held: "+str(exc)[:300],flush=True)
        time.sleep(300)
