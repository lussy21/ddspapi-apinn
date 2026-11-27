"""Research-only current-season Opta fixture and xmetrics schema audit."""
import tempfile,json
from pathlib import Path
from urllib.request import urlopen,Request
import duckdb
BASE="https://github.com/peteowen1/pannadata/releases/download/opta-latest/"
def download(name,path,limit):
    with urlopen(Request(BASE+name,headers={"User-Agent":"LineupLens-Personal-Research/1.0"}),timeout=90) as r,path.open("wb") as w:
        n=0
        while (chunk:=r.read(1024*1024)):
            n+=len(chunk)
            if n>limit:raise ValueError("download limit")
            w.write(chunk)
def main():
    with tempfile.TemporaryDirectory() as td:
        db=duckdb.connect()
        for alias,name,limit in [("fixtures","opta_fixtures.parquet",30_000_000),("xm","opta_xmetrics_bymatch.parquet",450_000_000)]:
            p=Path(td)/name
            download(name,p,limit)
            db.execute(f"CREATE VIEW {alias} AS SELECT * FROM read_parquet('{p}')")
            cols=[x[0] for x in db.execute(f"DESCRIBE {alias}").fetchall()]
            print("SCHEMA "+alias+" "+json.dumps(cols),flush=True)
            selected=[x for x in ["competition","league","season","match_id","match_date","home_team","away_team","home_team_id","away_team_id","match_status","xg","xa"] if x in cols]
            league=next((x for x in ("competition","league") if x in cols),None)
            if "season" in cols and league:
                print("CURRENT "+alias+" "+json.dumps(db.execute(f"SELECT {league},season,count(*) FROM {alias} WHERE cast(season as varchar) IN ('2026','2026-2027') GROUP BY 1,2 ORDER BY 1,2").fetchall(),default=str),flush=True)
            if selected and "season" in cols:print("SAMPLE "+alias+" "+json.dumps(db.execute(f"SELECT {','.join(selected)} FROM {alias} WHERE cast(season as varchar)='2026-2027' LIMIT 2").fetchall(),default=str),flush=True)
if __name__=="__main__":main()
