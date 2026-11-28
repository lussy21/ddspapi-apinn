"""One-time historical check of old vs new estimates, not predictive validation."""
from psycopg.types.json import Jsonb
import season_db
import lineup_goal_context as goal
import lineup_shrinkage as shrink
from simple_replacements import load_history,load_sources

VERSION="shrinkage-v1-450m"
MATCHES=(901884720,901878930)

def run():
    with season_db.db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS lineup_shrinkage_audit(
            version text NOT NULL, match_id integer NOT NULL, team_id integer NOT NULL,
            result jsonb NOT NULL, checked_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(version,match_id,team_id))""")
    for mid in MATCHES:
        with season_db.db() as db:
            m=db.execute("""SELECT match_id,competition_code,kickoff_utc,home_team_id,away_team_id
                FROM archive_matches WHERE match_id=%s""",(mid,)).fetchone()
            if not m:continue
            if db.execute("""SELECT count(*) n FROM lineup_shrinkage_audit WHERE version=%s AND match_id=%s""",(VERSION,mid)).fetchone()["n"]==2:continue
            code=m["competition_code"];cutoff=m["kickoff_utc"]
            priors=shrink.load_priors(db,code,cutoff)
            for tid in (m["home_team_id"],m["away_team_id"]):
                cur=db.execute("""SELECT s.player_id id,p.player_name name,s.position_code code
                    FROM archive_starters s JOIN archive_players p USING(player_id)
                    WHERE s.match_id=%s AND s.team_id=%s""",(mid,tid)).fetchall()
                history=load_history(db,code,tid,cutoff);sources=load_sources(db,code,tid,cutoff)
                scores=goal.load_scores(db,code,tid,cutoff)
                before=goal.evaluate(cur,history,sources,scores)
                after=goal.evaluate(cur,history,sources,scores,priors=priors)
                result={"league":code,"before":before,"after":after,
                        "team":db.execute("SELECT team_name FROM archive_teams WHERE team_id=%s",(tid,)).fetchone()["team_name"],
                        "cutoff":cutoff.isoformat()}
                db.execute("""INSERT INTO lineup_shrinkage_audit(version,match_id,team_id,result)
                    VALUES(%s,%s,%s,%s) ON CONFLICT(version,match_id,team_id) DO UPDATE
                    SET result=excluded.result,checked_at=now()""",(VERSION,mid,tid,Jsonb(result)))
                print("Shrinkage real historical audit",mid,tid,
                      [(r["line"],r["status"],r.get("value")) for r in after],flush=True)
