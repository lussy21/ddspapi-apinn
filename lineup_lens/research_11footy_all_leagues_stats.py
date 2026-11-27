"""Research only: actual 11footy player match statistics coverage for 9 leagues.
Fetches documented CC BY-NC 4.0 public snapshot, prints aggregates only.
No Neon, credentials or application deployment."""
import concurrent.futures,json,lzma,sqlite3,tempfile
from pathlib import Path
from urllib.request import Request,urlopen
BASE="https://github.com/fm-devlab/11footy-dataset/releases/download/11footy-2026-11-10/"
LEAGUES={"PL":"england.premier-league","SA":"italy.serie-a","LL":"spain.la-liga","BL":"germany.bundesliga","L1":"france.ligue-1","DE2":"germany.2-bundesliga","UCL":"european-cups.champions-league","UEL":"european-cups.europa-league","UECL":"european-cups.conference-league"}
METRICS=("minutes_played","goals","assists","shots","shots_on_target","key_passes","fouls_committed","fouls_suffered","yellow_cards","red_cards","saves","goals_conceded")
def audit(item):
    code,slug=item
    try:
        with tempfile.TemporaryDirectory() as td:
            compressed=Path(td)/"source.xz"; path=Path(td)/"source.db"
            with urlopen(Request(BASE+slug+".db.xz",headers={"User-Agent":"LineupLens-Personal-Research/1.0"}),timeout=90) as r,compressed.open("wb") as w:
                n=0
                while (chunk:=r.read(1024*1024)):
                    n+=len(chunk)
                    if n>60_000_000:raise ValueError("compressed size limit")
                    w.write(chunk)
            with lzma.open(compressed,"rb") as r,path.open("wb") as w:
                n=0
                while (chunk:=r.read(1024*1024)):
                    n+=len(chunk)
                    if n>400_000_000:raise ValueError("uncompressed size limit")
                    w.write(chunk)
            db=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
            try:
                cols={r[1] for r in db.execute("pragma table_info(player_match_statistics)")}
                if not {"match_id","team_id","player_id",*METRICS}<=cols:raise ValueError("missing stats columns")
                db.execute("""CREATE TEMP VIEW this_season AS
                SELECT m.match_id,m.local_date,m.home_team_id,m.away_team_id
                FROM matches m JOIN seasons s ON m.season_id=s.season_id
                WHERE s.season=2026 AND m.status='played'""")
                total=db.execute("select count(*) from this_season").fetchone()[0]
                sql="""WITH base AS (
                  SELECT p.match_id,p.team_id,p.player_id,t.local_date,s.minutes_played,
                  """+",".join("s."+m for m in METRICS[1:])+"""
                  FROM this_season t JOIN match_players p USING(match_id)
                  LEFT JOIN player_match_statistics s ON s.match_id=p.match_id AND s.team_id=p.team_id AND s.player_id=p.player_id
                  WHERE p.started=1 AND p.team_id IN(t.home_team_id,t.away_team_id)
                ), sides AS (SELECT match_id,team_id,count(*) n,count(distinct player_id) np,
                  sum(case when minutes_played is not null and minutes_played>0 then 1 else 0 end) nm
                  FROM base GROUP BY 1,2),
                good AS (SELECT match_id FROM sides GROUP BY 1 HAVING count(*)=2 AND min(n)=11 AND max(n)=11 AND min(np)=11 AND min(nm)=11),
                verified AS (SELECT b.* FROM base b JOIN good USING(match_id))
                SELECT count(distinct match_id),count(*),min(local_date),max(local_date),"""+",".join("count("+m+")" for m in METRICS)+" FROM verified"
                row=db.execute(sql).fetchone()
                return {"code":code,"source_matches":total,"verified_source_matches":row[0],"starter_rows":row[1],"first":row[2],"last":row[3],"metric_counts":dict(zip(METRICS,row[4:]))}
            finally:db.close()
    except Exception as exc:return {"code":code,"error":str(exc)}
if __name__=="__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for report in pool.map(audit,LEAGUES.items()):print("AUDIT "+json.dumps(report,ensure_ascii=False),flush=True)
