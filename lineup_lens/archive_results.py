"""Verified final scores for existing Lineup Lens archive fixtures only."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import importlib
import time
import season_db
import archive_daily as archive

LOCK=614439842
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS archive_match_results (
        match_id integer PRIMARY KEY REFERENCES archive_matches(match_id),
        home_goals integer NOT NULL CHECK(home_goals>=0),
        away_goals integer NOT NULL CHECK(away_goals>=0),
        source text NOT NULL DEFAULT 'ESPN', verified_at timestamptz NOT NULL DEFAULT now())""")
    db.execute("""CREATE TABLE IF NOT EXISTS archive_result_attempts (
        competition_code text NOT NULL, local_date date NOT NULL,
        attempted_at timestamptz NOT NULL DEFAULT now(), error text,
        PRIMARY KEY(competition_code,local_date))""")

def final_score(event):
    status=event.get("status",{}).get("type",{})
    if status.get("completed") is not True or status.get("name") not in ("STATUS_FULL_TIME","STATUS_FINAL"):
        return None
    cs=event.get("competitions") or []
    if len(cs)!=1:return None
    teams=cs[0].get("competitors") or []
    if len(teams)!=2 or {t.get("homeAway") for t in teams}!={"home","away"}:return None
    out={}
    for t in teams:
        raw=t.get("score")
        if isinstance(raw,bool) or not str(raw).isdigit():return None
        score=int(raw)
        if score>99:return None
        tid=archive.source_id((t.get("team") or {}).get("id"),archive.TEAM_OFFSET)
        out[t["homeAway"]]=(tid,score)
    return out

def scan(league,day):
    module,tzname=archive.MODULES[league]
    mod=importlib.import_module("archive_espn_"+module)
    doc=mod.fetch("/scoreboard?dates="+day.strftime("%Y%m%d")+"&limit=50")
    ls=doc.get("leagues") or []
    if len(ls)!=1 or ls[0].get("slug")!=mod.BASE.rsplit("/",1)[-1] or (ls[0].get("season") or {}).get("year")!=2026:
        raise ValueError("Scoreboard competition/season not verified")
    events=doc.get("events")
    if not isinstance(events,list) or len(events)>=50:raise ValueError("Incomplete scoreboard")
    with season_db.db() as db:
        links=archive.get_links(db,league)
        targets={r["match_id"]:r for r in db.execute("""SELECT m.* FROM archive_matches m
            LEFT JOIN archive_match_results r USING(match_id)
            WHERE m.competition_code=%s AND m.local_date=%s AND m.season_year=2026 AND r.match_id IS NULL""",(league,day)).fetchall()}
        added=0
        for e in events:
            mid=archive.source_id(e.get("id"),archive.MATCH_OFFSET)
            canonical=links["match"].get(mid,mid)
            m=targets.get(canonical)
            if not m:continue
            k=datetime.fromisoformat(e["date"].replace("Z","+00:00"))
            if k.tzinfo is None or k.astimezone(ZoneInfo(tzname)).date()!=day:continue
            score=final_score(e)
            if not score:continue
            if any(links["team"].get(score[s][0],score[s][0])!=m[s+"_team_id"] for s in ("home","away")):continue
            db.execute("""INSERT INTO archive_match_results(match_id,home_goals,away_goals)
                VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",(canonical,score["home"][1],score["away"][1]))
            added+=1
        if added:print(f"Results {league} {day}: {added}/{len(targets)} verified",flush=True)
        return len(targets)-added

def tick():
    with season_db.db() as lockdb:
        if not lockdb.execute("SELECT pg_try_advisory_lock(%s) acquired",(LOCK,)).fetchone()["acquired"]:return
        try:
            with season_db.db() as db:
                setup(db)
                days=db.execute("""SELECT DISTINCT m.competition_code,m.local_date,
                    CASE WHEN m.competition_code IN ('UCL','UEL','UECL') THEN 0 ELSE 1 END priority
                    FROM archive_matches m LEFT JOIN archive_match_results r USING(match_id)
                    LEFT JOIN archive_result_attempts a ON a.competition_code=m.competition_code AND a.local_date=m.local_date
                    WHERE m.season_year=2026 AND r.match_id IS NULL
                    AND (a.attempted_at IS NULL OR a.error IS NULL OR a.attempted_at<now()-interval '15 minutes')
                    ORDER BY priority,local_date DESC,competition_code LIMIT 35""").fetchall()
            for item in days:
                league,day=item["competition_code"],item["local_date"]
                error=None
                try:
                    missing=scan(league,day)
                    if missing:error=f"{missing} scores not verified"
                except Exception as exc:
                    error=str(exc)[:250]
                    print(f"Results held {league} {day}: {error}",flush=True)
                with season_db.db() as db:
                    db.execute("""INSERT INTO archive_result_attempts(competition_code,local_date,error)
                        VALUES(%s,%s,%s) ON CONFLICT(competition_code,local_date)
                        DO UPDATE SET attempted_at=now(),error=excluded.error""",(league,day,error))
                time.sleep(.35)
        finally:lockdb.execute("SELECT pg_advisory_unlock(%s)",(LOCK,))

def loop():
    while True:
        try:tick()
        except Exception as exc:print("Results loop held: "+str(exc)[:200],flush=True)
        time.sleep(20)

def history(db,league,tid,kickoff,include_match=False):
    if tid is None:return {}
    if not db.execute("SELECT to_regclass('archive_match_results') present").fetchone()["present"]:return {}
    operator='<=' if include_match else '<'
    return {r["player_id"]:r for r in db.execute(f"""SELECT s.player_id,
        count(r.match_id)::int scored,
        coalesce(sum(CASE WHEN m.home_team_id=s.team_id THEN r.home_goals ELSE r.away_goals END),0)::int gf,
        coalesce(sum(CASE WHEN m.home_team_id=s.team_id THEN r.away_goals ELSE r.home_goals END),0)::int ga,
        count(*) FILTER(WHERE (m.home_team_id=s.team_id AND r.home_goals>r.away_goals)
                           OR (m.away_team_id=s.team_id AND r.away_goals>r.home_goals))::int wins
        FROM archive_starters s JOIN archive_matches m USING(match_id)
        LEFT JOIN archive_match_results r USING(match_id)
        WHERE m.competition_code=%s AND m.season_year=2026 AND s.team_id=%s AND m.kickoff_utc{operator}%s
        GROUP BY s.player_id""",(league,tid,kickoff)).fetchall()}

def player_stat(hist,cid,starts):
    if not isinstance(starts,int) or starts<=0:return None
    row=hist.get(cid)
    if not row or not row["scored"] or not 0<=row["wins"]<=row["scored"]<=starts:return None
    return {"wins":row["wins"],"scored":row["scored"],"starts":starts,"gf":row["gf"],"ga":row["ga"]}

def team_totals(db,league,tid,kickoff,include_match=False):
    """One result per team fixture, independent of lineup; same time cutoff."""
    if tid is None:return None
    if not db.execute("SELECT to_regclass('archive_match_results') present").fetchone()["present"]:return None
    op='<=' if include_match else '<'
    row=db.execute(f"""SELECT count(*)::int played,count(r.match_id)::int scored,
        coalesce(sum(CASE WHEN m.home_team_id=%s THEN r.home_goals ELSE r.away_goals END),0)::int gf,
        coalesce(sum(CASE WHEN m.home_team_id=%s THEN r.away_goals ELSE r.home_goals END),0)::int ga,
        count(*) FILTER(WHERE (m.home_team_id=%s AND r.home_goals>r.away_goals)
                         OR (m.away_team_id=%s AND r.away_goals>r.home_goals))::int wins
        FROM archive_matches m LEFT JOIN archive_match_results r USING(match_id)
        WHERE m.competition_code=%s AND m.season_year=2026 AND %s IN (m.home_team_id,m.away_team_id)
        AND m.kickoff_utc{op}%s""",(tid,tid,tid,tid,league,tid,kickoff)).fetchone()
    return dict(row) if row and row["played"] else None
