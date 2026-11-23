"""Read-only audit of the published CC BY-NC 4.0 11footy Serie A SQLite snapshot.

Downloads temporary file in GitHub Actions only. Never imports player data
or writes the user's Neon database. Intended for personal source evaluation.
"""
import lzma
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

URL = (
    "https://github.com/fm-devlab/11footy-dataset/releases/download/"
    "11footy-2026-11-10/italy.serie-a.db.xz"
)

def check():
    with TemporaryDirectory() as folder:
        database_file=Path(folder)/"seriea.db"
        req=Request(URL,headers={"User-Agent":"LineupLens-Research-Audit/1.0"})
        print("Downloading 11footy dated release for a read-only coverage audit",flush=True)
        with urlopen(req,timeout=90) as resp:
            with lzma.LZMAFile(resp) as xz, open(database_file,"wb") as fh:
                shutil.copyfileobj(xz,fh,length=1024*1024)
        print("Decompressed database size:", database_file.stat().st_size,flush=True)
        con=sqlite3.connect(str(database_file))
        con.row_factory=sqlite3.Row
        versions=con.execute("SELECT * FROM format_version").fetchall()
        print("Dataset version:",[dict(r) for r in versions],flush=True)
        print("Recent seasons:",[
            dict(r) for r in con.execute(
                "SELECT s.season,s.name,COUNT(m.match_id) AS matches,"
                "SUM(CASE WHEN m.status='played' THEN 1 ELSE 0 END) played,"
                "MIN(m.local_date) first_day,MAX(m.local_date) last_day "
                "FROM seasons s JOIN matches m ON s.season_id=m.season_id "
                "GROUP BY s.season,s.name ORDER BY s.season DESC LIMIT 5")
        ],flush=True)

        print("2026-27 started counts:",[
            dict(r) for r in con.execute(
                "SELECT m.status AS status,COUNT(DISTINCT m.match_id) AS matches,"
                "COUNT(DISTINCT CASE WHEN mp.started=1 THEN m.match_id END) AS with_starters,"
                "COUNT(CASE WHEN mp.started=1 THEN 1 END) AS starting_players "
                "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
                "LEFT JOIN match_players mp ON mp.match_id=m.match_id "
                "WHERE s.season=2026 GROUP BY m.status")
        ],flush=True)

        full = list(con.execute(
            "SELECT m.match_id, m.local_date, m.status, COUNT(DISTINCT mp.team_id) AS team_sides,"
            "COUNT(*) AS n_starters "
            "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
            "JOIN match_players mp ON mp.match_id=m.match_id AND mp.started=1 "
            "WHERE s.season=2026 GROUP BY m.match_id,m.local_date,m.status"
        ))
        complete=[r for r in full if r["team_sides"]==2 and r["n_starters"]==22]
        print("2026/27 matches with ANY starters:",len(full),flush=True)
        print("2026/27 matches with exactly 22 starters across both teams:",len(complete),flush=True)
        print("LATEST matches with XI: ",[
            dict(r) for r in sorted(complete,key=lambda r:r["local_date"],reverse=True)[:6]
        ],flush=True)
        print("Dates with started data: min/max",min((r["local_date"] for r in full), default=None),
              max((r["local_date"] for r in full), default=None),flush=True)
        assert len(complete)>0, "No complete 2026-27 XIs in release"
        con.close()

if __name__=="__main__": check()
