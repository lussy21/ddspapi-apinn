"""Lineup Lens: public ESPN match-day feed, no paid API.
Persistent schedule and XI snapshots; archive only after final whistle.
Render Free may sleep: catch up on wake, not guaranteed always-on.
"""
from datetime import datetime,date,timedelta,timezone
from collections import defaultdict
import importlib,json,time
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb
import season_db
import archive_daily as archive
from archive_pitch import ROLE,pitch_from_codes

ATHENS=ZoneInfo("Europe/Athens")
LOCK=614439841
CHECKPOINTS=(70,58,50,30)
FINAL_NAMES={"STATUS_FULL_TIME","STATUS_FINAL","STATUS_FINAL_AET","STATUS_FINAL_PEN","STATUS_END_OF_EXTRATIME"}
def now():return datetime.now(timezone.utc)
def kickoff(e):return datetime.fromisoformat(e["date"].replace("Z","+00:00"))
def mod_for(league):
    module,tz=archive.MODULES[league]
    return importlib.import_module("archive_espn_"+module),ZoneInfo(tz)
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_live_fixtures (
       match_id integer PRIMARY KEY, competition_code text NOT NULL,
       kickoff_utc timestamptz NOT NULL, event jsonb NOT NULL,
       status text NOT NULL DEFAULT 'waiting', checks integer[] NOT NULL DEFAULT '{}',
       announced jsonb, announced_at timestamptz, last_final_check timestamptz,
       archived boolean NOT NULL DEFAULT false, error text, updated_at timestamptz NOT NULL DEFAULT now())""")
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_live_discovery (
       competition_code text NOT NULL, local_date date NOT NULL,
       checked_at timestamptz NOT NULL DEFAULT now(), error text,
       PRIMARY KEY(competition_code,local_date))""")

def board(league,day):
    mod,tz=mod_for(league)
    doc=mod.fetch("/scoreboard?dates="+day.strftime("%Y%m%d")+"&limit=50")
    ls=doc.get("leagues") or []
    if len(ls)!=1 or ls[0].get("slug")!=mod.BASE.rsplit("/",1)[-1] or (ls[0].get("season") or {}).get("year")!=2026:
        raise ValueError("ESPN league/season not verified")
    es=doc.get("events")
    if not isinstance(es,list) or len(es)>=50:raise ValueError("Missing or truncated ESPN fixtures")
    return mod,tz,doc

def sides(e):
    cs=(e.get("competitions") or [{}])[0].get("competitors") or []
    d={c.get("homeAway"):c.get("team") or {} for c in cs}
    if len(cs)!=2 or set(d)!={"home","away"}:raise ValueError("Invalid fixture teams")
    for x in d.values():
        archive.source_id(x.get("id"),archive.TEAM_OFFSET)
        if not x.get("displayName"):raise ValueError("Team name missing")
    if d["home"]["id"]==d["away"]["id"]:raise ValueError("Same teams")
    return d

def discover(league,day):
    mod,tz,doc=board(league,day)
    rows=[]
    for e in doc["events"]:
        k=kickoff(e)
        if k.tzinfo is None:raise ValueError("Missing timezone")
        if k.astimezone(tz).date()!=day:continue
        # UEFA qualifying stage is not part of the archived league-phase history.
        if league in ("UCL","UEL","UECL") and day<date(2026,11,24):continue
        sides(e)
        mid=archive.source_id(e["id"],archive.MATCH_OFFSET)
        status=(e.get("status") or {}).get("type") or {}
        name=str(status.get("name","")).upper()
        if any(x in name for x in ("POSTPONED","CANCELED","CANCELLED","ABANDONED")):state="unavailable"
        elif status.get("completed"):state="finished"
        elif k<=now():state="playing"
        else:state="waiting"
        rows.append((mid,league,k,Jsonb(e),state))
    with season_db.db() as db:
        for row in rows:
            db.execute("""INSERT INTO lineup_live_fixtures(match_id,competition_code,kickoff_utc,event,status)
               VALUES(%s,%s,%s,%s,%s) ON CONFLICT(match_id) DO UPDATE SET
               kickoff_utc=excluded.kickoff_utc,event=excluded.event,
               status=CASE WHEN excluded.status IN ('finished','unavailable') THEN excluded.status
                 WHEN lineup_live_fixtures.announced IS NOT NULL THEN 'ready'
                 ELSE excluded.status END,updated_at=now()
               WHERE lineup_live_fixtures.competition_code=excluded.competition_code
               AND NOT lineup_live_fixtures.archived""",row)
        db.execute("""INSERT INTO lineup_live_discovery(competition_code,local_date,error)
            VALUES(%s,%s,NULL) ON CONFLICT(competition_code,local_date)
            DO UPDATE SET checked_at=now(),error=NULL""",(league,day))
    print(f"Live fixtures {league} {day}: {len(rows)}",flush=True)

def get_summary(mod,e):
    doc=mod.fetch("/summary?event="+str(e["id"]))
    header=doc.get("header") or {}
    if str(header.get("id"))!=str(e["id"]):raise ValueError("ESPN summary identity not verified")
    cs=header.get("competitions") or []
    if len(cs)!=1 or str(cs[0].get("id"))!=str(e["id"]):raise ValueError("ESPN competition identity not verified")
    status=cs[0].get("status",{}).get("type",{})
    return doc,status

def parse_announced(league,e,doc):
    # ESPN's soccer summary publishes explicit starter flags in its match roster.
    # Reject any explicit prediction indicators and all incomplete lineups.
    for g in doc.get("rosters") or []:
        for obj in [g]+(g.get("roster") or []):
            if obj.get("predicted") is True or obj.get("isPredicted") is True or obj.get("confirmed") is False or obj.get("isConfirmed") is False:
                raise ValueError("Roster is not confirmed")
    mod,tz=mod_for(league)
    m=archive.parse_new(e,doc,league,tz,prematch=True)
    all_ids=[p["player_id"] for side in ("home","away") for p in m[side]["players"]]
    if len(set(all_ids))!=22:raise ValueError("Duplicate source players across lineups")
    return {k:m[k] for k in ("home","away")}

def precheck(row,stage):
    mid,league,e=row["match_id"],row["competition_code"],row["event"]
    mod,tz=mod_for(league)
    # Persist the attempt first; restarts cannot repeat an already spent check.
    with season_db.db() as db:
        db.execute("""UPDATE lineup_live_fixtures SET checks=array_append(checks,%s),status='searching',updated_at=now()
           WHERE match_id=%s AND NOT (%s=ANY(checks)) AND announced IS NULL""",(stage,mid,stage))
    try:
        doc,status=get_summary(mod,e)
        if now()>=row["kickoff_utc"] or status.get("completed") or status.get("state")!="pre":
            raise ValueError("No verified pre-match status")
        xi=parse_announced(league,e,doc)
        with season_db.db() as db:
            db.execute("""UPDATE lineup_live_fixtures SET announced=%s,announced_at=now(),status='ready',error=NULL,updated_at=now()
               WHERE match_id=%s AND announced IS NULL AND kickoff_utc>now()""",(Jsonb(xi),mid))
        print(f"Live XI stored {league} {mid}, 22 explicit ESPN starters at checkpoint {stage}",flush=True)
    except Exception as exc:
        with season_db.db() as db:
            db.execute("UPDATE lineup_live_fixtures SET error=%s,updated_at=now() WHERE match_id=%s",(str(exc)[:300],mid))
        print(f"Live XI waiting {league} {mid}: {str(exc)[:200]}",flush=True)

def finalcheck(row):
    mid,league,e=row["match_id"],row["competition_code"],row["event"]
    with season_db.db() as db:
        db.execute("UPDATE lineup_live_fixtures SET last_final_check=now() WHERE match_id=%s",(mid,))
        links=archive.get_links(db,league)
        canonical=links["match"].get(mid,mid)
        if db.execute("SELECT 1 FROM archive_matches WHERE match_id=%s AND competition_code=%s",(canonical,league)).fetchone():
            db.execute("UPDATE lineup_live_fixtures SET archived=true,status='finished',error=NULL WHERE match_id=%s",(mid,))
            return
    mod,tz=mod_for(league)
    doc,status=get_summary(mod,e)
    if not status.get("completed"):return
    if str(status.get("name","")).upper() not in FINAL_NAMES:
        raise ValueError("Not a verified played final: "+str(status.get("name")))
    # Re-fetch final fixture status and use the final XI, not the pre-match snapshot.
    day=row["kickoff_utc"].astimezone(tz).date()
    mod,tz,scoreboard=board(league,day)
    events=[x for x in scoreboard["events"] if str(x.get("id"))==str(e["id"])]
    if len(events)!=1 or not events[0].get("status",{}).get("type",{}).get("completed"):return
    with season_db.db() as lockdb:
        if not lockdb.execute("SELECT pg_try_advisory_lock(%s) acquired",(archive.LOCK,)).fetchone()["acquired"]:return
        try:
            with season_db.db() as db:
                seed=db.execute("SELECT seeded FROM archive_daily_state WHERE competition_code=%s",(league,)).fetchone()
            if not seed or not seed["seeded"]:raise ValueError("Historical identities not seeded")
            archive.scan_day(league,mod,tz,day,only_event=mid,scoreboard=scoreboard,summary=doc)
            with season_db.db() as db:
                if not db.execute("SELECT 1 FROM archive_matches WHERE match_id=%s AND competition_code=%s",(mid,league)).fetchone():raise ValueError("Final archive missing")
                db.execute("UPDATE lineup_live_fixtures SET archived=true,status='finished',error=NULL WHERE match_id=%s",(mid,))
            print(f"Live final archived {league} {mid}",flush=True)
        finally:lockdb.execute("SELECT pg_advisory_unlock(%s)",(archive.LOCK,))

def tick():
    with season_db.db() as lockdb:
        if not lockdb.execute("SELECT pg_try_advisory_lock(%s) acquired",(LOCK,)).fetchone()["acquired"]:return
        try:
            with season_db.db() as db:setup(db)
            current=now()
            for league in archive.MODULES:
                mod,tz=mod_for(league)
                day=current.astimezone(tz).date()
                if day<date(2026,11,24) or day>(date(2026,12,31) if league in ("NO1","SE1") else date(2027,6,30)):continue
                with season_db.db() as db:
                    state=db.execute("SELECT checked_at,error FROM lineup_live_discovery WHERE competition_code=%s AND local_date=%s",(league,day)).fetchone()
                if not state or (current-state["checked_at"]).total_seconds()> (600 if state["error"] else 3600):
                    try:discover(league,day)
                    except Exception as exc:
                        print(f"Live discovery held {league}: {str(exc)[:200]}",flush=True)
                        with season_db.db() as db:
                            db.execute("""INSERT INTO lineup_live_discovery(competition_code,local_date,error) VALUES(%s,%s,%s)
                              ON CONFLICT(competition_code,local_date) DO UPDATE SET checked_at=now(),error=excluded.error""",(league,day,str(exc)[:300]))
            with season_db.db() as db:
                rows=db.execute("""SELECT * FROM lineup_live_fixtures WHERE NOT archived
                  AND status<>'unavailable' AND kickoff_utc BETWEEN now()-interval '30 hours' AND now()+interval '70 minutes'
                  ORDER BY kickoff_utc""").fetchall()
            for row in rows:
                try:
                    mins=(row["kickoff_utc"]-now()).total_seconds()/60
                    if mins>0 and row["announced"] is None:
                        eligible=[x for x in CHECKPOINTS if mins<=x and x not in row["checks"]]
                        if eligible:
                            # After wake, use the most recent due stage, not a burst of missed calls.
                            stage=min(eligible)
                            with season_db.db() as db:
                                db.execute("UPDATE lineup_live_fixtures SET checks=ARRAY(SELECT DISTINCT unnest(checks || %s::integer[])) WHERE match_id=%s",([x for x in CHECKPOINTS if x>stage],row["match_id"]))
                            precheck(row,stage)
                    elif mins<=-105 and (not row["last_final_check"] or (now()-row["last_final_check"]).total_seconds()>=900):
                        finalcheck(row)
                except Exception as exc:
                    print(f"Live check held {row['match_id']}: {str(exc)[:200]}",flush=True)
                    with season_db.db() as db:
                        db.execute("UPDATE lineup_live_fixtures SET error=%s WHERE match_id=%s",(str(exc)[:300],row["match_id"]))
        finally:lockdb.execute("SELECT pg_advisory_unlock(%s)",(LOCK,))

def loop():
    while True:
        try:tick()
        except Exception as exc:print("Live loop held: "+str(exc)[:200],flush=True)
        time.sleep(45)

def fixtures(day):
    start=datetime.combine(day,datetime.min.time(),ATHENS)
    end=start+timedelta(days=1)
    with season_db.db() as db:
        setup(db)
        rows=db.execute("SELECT * FROM lineup_live_fixtures WHERE kickoff_utc>=%s AND kickoff_utc<%s ORDER BY kickoff_utc",(start,end)).fetchall()
        discovered=db.execute("SELECT competition_code,error FROM lineup_live_discovery WHERE local_date=%s",(day,)).fetchall()
    result=[]
    for r in rows:
        s=sides(r["event"])
        result.append({"id":str(r["match_id"]),"utc_date":r["kickoff_utc"].isoformat(),"competition":r["competition_code"],
           "home_team":{"name":s["home"]["displayName"]},"away_team":{"name":s["away"]["displayName"]},
           "status":r["status"],"ready":r["announced"] is not None,"archived":r["archived"]})
    return {"data":result,"checked":sum(1 for r in discovered if not r["error"]),"errors":[r["competition_code"] for r in discovered if r["error"]],"total_competitions":len(archive.MODULES)}

def lineup(mid):
    with season_db.db() as db:
        setup(db)
        row=db.execute("SELECT * FROM lineup_live_fixtures WHERE match_id=%s",(mid,)).fetchone()
        if not row:raise ValueError("Αγώνας δεν βρέθηκε")
        league=row["competition_code"]
        mod,tz=mod_for(league)
        links=archive.get_links(db,league)
        canonical=links["match"].get(mid,mid)
        final=db.execute("SELECT * FROM archive_matches WHERE match_id=%s AND competition_code=%s",(canonical,league)).fetchone()
        snapshot=row["announced"]
        if final:
            # Final starters supersede any last-minute pre-match change.
            snapshot={}
            for side in ("home","away"):
                tid=final[side+"_team_id"]
                team=db.execute("SELECT team_name FROM archive_teams WHERE team_id=%s",(tid,)).fetchone()
                ps=db.execute("""SELECT s.player_id,p.player_name,s.position_code,s.jersey_number AS shirt_number FROM archive_starters s JOIN archive_players p USING(player_id) WHERE s.match_id=%s AND s.team_id=%s""",(canonical,tid)).fetchall()
                snapshot[side]={"id":tid,"name":team["team_name"],"players":ps}
        out={"ready":bool(snapshot),"confirmed":bool(snapshot),"kickoff":row["kickoff_utc"].isoformat(),"competition":league,"status":row["status"],"archived":bool(final),"source":"ESPN","message":"Αναμονή επίσημων ενδεκάδων από ESPN."}
        if not snapshot:return out
        for side in ("home","away"):
            t=snapshot[side]
            tid=t["id"] if final or league not in archive.MIXED else links["team"].get(t["id"])
            counts=db.execute("""SELECT s.player_id,p.player_name,count(*)::int starts FROM archive_starters s JOIN archive_matches m USING(match_id) JOIN archive_players p USING(player_id)
               WHERE m.competition_code=%s AND m.season_year=2026 AND s.team_id=%s AND m.kickoff_utc<%s
               GROUP BY s.player_id,p.player_name""",(league,tid,row["kickoff_utc"])).fetchall()
            played=db.execute("""SELECT count(*)::int n FROM archive_matches WHERE competition_code=%s AND season_year=2026 AND (home_team_id=%s OR away_team_id=%s) AND kickoff_utc<%s""",(league,tid,tid,row["kickoff_utc"])).fetchone()["n"]
            hist={x["player_id"]:x for x in counts}
            verified=bool(tid and played)
            try:
                formation,ordered=pitch_from_codes(t["players"])
                # A source-backed explicit formation and order may override the
                # derived order only after the full XI and role rows agree.
                explicit=t.get("formation")
                order=t.get("position_order")
                by_id={p["player_id"]:p for p in ordered}
                if t.get("position_source") and explicit==formation and isinstance(order,list) and len(order)==11 and set(order)==set(by_id):
                    candidate=[by_id[pid] for pid in order]
                    if [ROLE[p["position_code"]] for p in candidate]==[ROLE[p["position_code"]] for p in ordered]:
                        ordered=candidate
            except (ValueError,KeyError,TypeError):formation,ordered="",t["players"]
            players=[]
            for p in ordered:
                pid=p["player_id"];name=p["player_name"]
                if not final and league=="SE1" and "ohlsson" in archive.norm(name) and "degerfors" in archive.norm(t["name"]):
                    pid={7:1800000007,16:1800000016}.get(p["shirt_number"],pid)
                blocked=not final and pid in links["blocked_player"]
                cid=pid if final or league not in archive.MIXED else links["player"].get(pid,pid)
                starts=None
                if verified and not blocked:
                    if cid in hist and mod.compatible(hist[cid]["player_name"],name) if league in archive.MIXED and cid in hist else cid in hist and archive.compatible(hist[cid]["player_name"],name):
                        starts=hist[cid]["starts"]
                    elif cid not in hist and not any(archive.compatible(x["player_name"],name) for x in counts):
                        starts=0
                players.append({"id":pid,"name":name,"number":p["shirt_number"],"position":ROLE.get(p["position_code"]),"starts":starts})
            out[side]={"id":tid,"name":t["name"],"formation":formation,"played":played if verified else None,"verified":verified,"starting_xi":players,"positions_known":bool(formation),"position_source":t.get("position_source") if formation else None}
        return out
