"""Research only: actual 2026/27 and calendar-2026 Opta player coverage.
No Neon credentials, no writes, no raw player records in logs."""
import json, tempfile
from pathlib import Path
from urllib.request import Request,urlopen
import duckdb
URL="https://github.com/peteowen1/pannadata/releases/download/opta-latest/opta_player_stats.parquet"
LEAGUES={"PL":["EPL","Premier_League"],"SA":["Serie_A"],"LL":["La_Liga"],"BL":["Bundesliga"],"L1":["Ligue_1"],"GR1":["Greek_Super_League","Super_League_Greece","Greek_Super_League_1","Greece_Super_League"],"BE1":["Belgian_First_Division","Belgian_Pro_League"],"DK1":["Danish_Superliga","Denmark_Superliga"],"DE2":["2_Bundesliga","Bundesliga_2","German_2_Bundesliga"],"NO1":["Eliteserien","Norwegian_Eliteserien"],"NL1":["Eredivisie"],"TR1":["Super_Lig"],"SC1":["Scottish_Premiership"],"SE1":["Allsvenskan"],"UCL":["UCL","Champions_League"],"UEL":["UEL","Europa_League"],"UECL":["Conference_League","UECL"]}
def main():
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/"stats.parquet"
        with urlopen(Request(URL,headers={"User-Agent":"LineupLens-Personal-Research/1.0"}),timeout=90) as r,path.open("wb") as w:
            n=0
            while True:
                chunk=r.read(1024*1024)
                if not chunk:break
                n+=len(chunk)
                if n>500_000_000:raise RuntimeError("size safety limit")
                w.write(chunk)
        db=duckdb.connect()
        db.execute("CREATE VIEW stats AS SELECT * FROM read_parquet('"+str(path)+"')")
        cols={r[0] for r in db.execute("DESCRIBE stats").fetchall()}
        print("SCHEMA "+json.dumps(sorted(cols)),flush=True)
        league=next((x for x in ("league","competition","competition_code","league_code") if x in cols),None)
        date=next((x for x in ("match_date","date") if x in cols),None)
        if not league or not date:raise RuntimeError("unknown source date/league column")
        core=["match_id","player_id","team_id","position","minsPlayed","gameStarted"]
        if not set(core)<=cols:raise RuntimeError("missing core fields")
        measures=[k for k in ("goals","goalAssist","totalScoringAtt","ontargetScoringAtt","totalAttAssist","totalPass","accuratePass","totalTackle","interception","totalClearance","ballRecovery","duelWon","aerialWon","saves","bigChanceCreated","minsPlayed") if k in cols]
        filters=f"try_cast({date} as date) between DATE '2026-01-01' and DATE '2026-11-27'"
        # Count by actual source league and period. No assertion from release update alone.
        db.execute(f"""CREATE TEMP VIEW this_year AS SELECT * FROM stats WHERE {filters}""")
        present=db.execute(f"SELECT {league}, min(try_cast({date} as date)),max(try_cast({date} as date)),count(distinct match_id) FROM this_year GROUP BY 1 ORDER BY 1").fetchall()
        print("LEAGUE_LIST "+json.dumps(present,default=str),flush=True)
        for code,aliases in LEAGUES.items():
            def key(x):return ''.join(c for c in str(x).lower() if c.isalnum())
            hit=[r[0] for r in present if key(r[0]) in {key(x) for x in aliases}]
            if len(hit)!=1:
                print("AUDIT "+json.dumps({"code":code,"matched_source_leagues":hit,"status":"unresolved"}),flush=True)
                continue
            start="2026-01-01" if code in ("NO1","SE1") else "2026-07-01"
            # Exclude unplayed and substitute rows; require 11 identified starters on each of 2 teams.
            where=f"{league}=? AND try_cast({date} as date)>=? AND try_cast(gameStarted as integer)=1 AND lower(coalesce(cast(position as varchar),''))<>'substitute' AND player_id IS NOT NULL AND team_id IS NOT NULL"
            rows=db.execute(f"""WITH base AS (SELECT * FROM this_year WHERE {where}),
            teams AS (SELECT match_id,team_id,count(*) n,count(distinct player_id) players FROM base GROUP BY 1,2),
            valid AS (SELECT match_id FROM teams GROUP BY 1 HAVING count(*)=2 AND min(n)=11 AND max(n)=11 AND min(players)=11),
            verified AS (SELECT b.* FROM base b JOIN valid USING(match_id))
            SELECT count(distinct match_id),count(*),min(try_cast({date} as date)),max(try_cast({date} as date))
            {''.join(',count('+k+')' for k in measures)} FROM verified""",[hit[0],start]).fetchone()
            print("AUDIT "+json.dumps({"code":code,"source_league":hit[0],"verified_source_matches":rows[0],"starter_rows":rows[1],"first":rows[2],"last":rows[3],"metric_counts":dict(zip(measures,rows[4:]))},default=str),flush=True)
if __name__=="__main__":main()
