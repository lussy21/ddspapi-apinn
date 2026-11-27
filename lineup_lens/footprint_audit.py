"""Read-only chronological audit of actual archived lineups.
Uses the same production assessment function, no future data or final result
as inputs. Coverage audit only, NOT an accuracy/forecast backtest.
European rows use own-competition history here (not domestic fallback).
"""
from collections import Counter,defaultdict
import season_db
import lineup_footprint as fp
import archive_daily

VERSION="2026-11-27-v2"

def evaluate(fixtures,starter_rows,stats_rows,rating_rows,role_rows=()):
    bymatch=defaultdict(list);sm=defaultdict(list);rm=defaultdict(list);mm=defaultdict(list)
    for r in starter_rows:bymatch[(r["match_id"],r["team_id"])].append({"id":r["player_id"],"name":r["player_name"],"code":r["position_code"]})
    for r in stats_rows:sm[(r["match_id"],r["team_id"])].append(r)
    for r in rating_rows:rm[(r["match_id"],r["team_id"])].append(r)
    for r in role_rows:mm[(r["match_id"],r["team_id"])].append(r)
    role_metrics=defaultdict(lambda:defaultdict(list))
    histories=defaultdict(list);stats=defaultdict(lambda:defaultdict(list));ratings=defaultdict(lambda:defaultdict(list));starts=defaultdict(Counter)
    statuses=Counter();lines=defaultdict(Counter)
    # A fixture cannot contribute to its own profile, even if an old archive
    # already includes its final stats. Group equal kickoff timestamps.
    from itertools import groupby
    for _,batch_iter in groupby(sorted(fixtures,key=lambda x:x["kickoff_utc"]),key=lambda x:x["kickoff_utc"]):
        batch=list(batch_iter)
        for f in batch:
            for tid in (f["home_team_id"],f["away_team_id"]):
                mid=f["match_id"];xi=bymatch[(mid,tid)]
                result=fp.assess(xi,histories[tid],stats[tid],ratings[tid],starts[tid],role_metrics[tid])
                for line in result:
                    statuses[line["status"]]+=1;lines[line["line"]][line["status"]]+=1
        for f in batch:
            for tid in (f["home_team_id"],f["away_team_id"]):
                mid=f["match_id"];xi=bymatch[(mid,tid)]
                if len(xi)==11 and len({p["id"] for p in xi})==11:
                    histories[tid].append({"kickoff_utc":f["kickoff_utc"],"players":xi})
                    histories[tid]=histories[tid][-7:]
                    starts[tid].update(p["id"] for p in xi)
                for r in sm[(mid,tid)]:stats[tid][r["player_id"]].append(r)
                for r in rm[(mid,tid)]:ratings[tid][r["player_id"]].append(r)
                for r in mm[(mid,tid)]:role_metrics[tid][r["player_id"]].append(r)
    return {"matches":len(fixtures),"lines":dict(statuses),"by_line":{k:dict(v) for k,v in lines.items()},
            "individual_quality_lines":sum(statuses[x] for x in ("positive","negative","similar"))}

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_footprint_audit (
      version text NOT NULL,competition_code text NOT NULL,result jsonb NOT NULL,
      completed_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(version,competition_code))""")

def run():
    from psycopg.types.json import Jsonb
    for code in archive_daily.MODULES:
        try:
            with season_db.db() as db:
                setup(db)
                if db.execute("SELECT 1 FROM lineup_footprint_audit WHERE version=%s AND competition_code=%s",(VERSION,code)).fetchone():continue
                fixtures=db.execute("""SELECT match_id,kickoff_utc,home_team_id,away_team_id FROM archive_matches WHERE season_year=2026 AND competition_code=%s""",(code,)).fetchall()
                starters=db.execute("""SELECT s.match_id,s.team_id,s.player_id,s.position_code,p.player_name FROM archive_starters s JOIN archive_matches a USING(match_id) JOIN archive_players p USING(player_id) WHERE a.season_year=2026 AND a.competition_code=%s""",(code,)).fetchall()
                st=db.execute("""SELECT p.match_id,p.team_id,p.player_id,p.metrics FROM lineup_private_match_stats p JOIN archive_matches a USING(match_id) WHERE a.season_year=2026 AND a.competition_code=%s AND p.source='11footy' AND p.release_name='11footy-2026-11-10'
                UNION ALL SELECT p.match_id,p.team_id,p.player_id,p.metrics FROM lineup_private_sub_stats p JOIN archive_matches a USING(match_id) WHERE a.season_year=2026 AND a.competition_code=%s AND p.release_name='11footy-2026-11-10' AND p.player_id IS NOT NULL""",(code,code)).fetchall()
                rt=db.execute("""SELECT p.match_id,p.team_id,p.canonical_player_id player_id,p.minutes,p.stats->>'position' position,(p.stats->>'rating')::numeric rating FROM soccer_stats_player p JOIN soccer_stats_fixture f USING(match_id) JOIN archive_matches a USING(match_id)
                 WHERE a.season_year=2026 AND a.competition_code=%s AND f.fetched_at IS NOT NULL AND f.matched_starters=22 AND p.played AND p.canonical_player_id IS NOT NULL AND jsonb_typeof(p.stats->'rating')='number'""",(code,)).fetchall()
                role_rows=[]
                if code=="PL":
                    role_rows=db.execute("""SELECT v.match_id,v.team_id,v.canonical_player_id player_id,v.minutes,v.xg,v.xa,
                        v.shots_on_target,v.chances_created,v.duels_won,v.raw_metrics->>'duels_lost' duels_lost,
                        v.interceptions,v.recoveries,s.position_code
                        FROM lineup_research_verified_player_stats v JOIN archive_starters s
                        ON s.match_id=v.match_id AND s.team_id=v.team_id AND s.player_id=v.canonical_player_id
                        WHERE v.source='fpl_elo' AND v.season_year=2026 AND v.competition_code=%s""",(code,)).fetchall()
                    role_rows=[dict(r,role=fp.role(r["position_code"])) for r in role_rows]
                result=evaluate(fixtures,starters,st,rt,role_rows)
                if sum(result["lines"].values())!=len(fixtures)*8:raise ValueError("audit line count mismatch")
                db.execute("INSERT INTO lineup_footprint_audit(version,competition_code,result) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(VERSION,code,Jsonb(result)))
            print("Footprint historical audit",code,result["matches"],result["lines"],flush=True)
        except Exception as exc:
            print("Footprint historical audit held",code,type(exc).__name__,flush=True)
