"""Read-only audit for the 2026/27 UEFA competition snapshots in 11footy.

No Neon writes, no billing providers, no SharpVision requests.
"""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict, Counter
import lzma
import sqlite3
import tempfile
from archive_11footy import BASE_URL, MAX_ARCHIVE_BYTES, MAX_DB_BYTES, _download, load_people
from archive_pitch import pitch_from_codes

CUPS={
    "Champions League":"european-cups.champions-league.db.xz",
    "Europa League":"european-cups.europa-league.db.xz",
    "Conference League":"european-cups.conference-league.db.xz",
}

def main():
    with tempfile.TemporaryDirectory(prefix="uefa-audit-") as d:
        root=Path(d)
        people=load_people(root)
        print("Named players in 11footy reference:",len(people),flush=True)
        for name, asset in CUPS.items():
            arch=root/asset
            dbfile=root/(name.replace(" ","_")+".db")
            _download(BASE_URL+asset,arch,MAX_ARCHIVE_BYTES)
            with lzma.open(arch) as xz,dbfile.open("wb") as out:
                total=0
                while True:
                    data=xz.read(1024*1024)
                    if not data:break
                    total+=len(data)
                    if total>MAX_DB_BYTES:raise ValueError("SQLite safety limit exceeded")
                    out.write(data)
            db=sqlite3.connect(dbfile)
            db.row_factory=sqlite3.Row
            print("ASSET",asset,flush=True)
            print("CODES",[dict(r) for r in db.execute(
                "SELECT s.season,m.competition_code,m.status,COUNT(*) AS matches,MIN(m.local_date) AS earliest,"
                "MAX(m.local_date) AS latest FROM matches m JOIN seasons s ON s.season_id=m.season_id "
                "WHERE s.season=2026 GROUP BY s.season,m.competition_code,m.status "
                "ORDER BY m.competition_code,m.status"
            )],flush=True)
            matches=[dict(r) for r in db.execute(
                "SELECT m.match_id,m.competition_code,m.local_date,m.home_team_id,m.away_team_id "
                "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
                "WHERE s.season=2026 AND m.status='played' ORDER BY m.local_date"
            )]
            match_ids=[m["match_id"] for m in matches]
            lines=defaultdict(lambda:defaultdict(list))
            for start in range(0,len(match_ids),80):
                chunk=match_ids[start:start+80]
                markers=",".join("?"*len(chunk))
                for p in db.execute(
                    "SELECT match_id,team_id,player_id,position_code FROM match_players "
                    "WHERE started=1 AND match_id IN ("+markers+")",chunk
                ):
                    lines[p["match_id"]][p["team_id"]].append(dict(p))
            good=0
            failures=Counter()
            codes=Counter()
            for m in matches:
                groups=lines[m["match_id"]]
                h,a=m["home_team_id"],m["away_team_id"]
                if set(groups)!={h,a}:
                    failures["team_count"]+=1
                    continue
                try:
                    for team in (h,a):
                        x=groups[team]
                        for row in x:
                            codes[row["position_code"]]+=1
                            if row["player_id"] not in people:
                                raise ValueError("no_player_name")
                        pitch_from_codes(x)
                except ValueError as exc:
                    failures[str(exc)]+=1
                    continue
                good+=1
            print("AUDIT",name,"games",len(matches),"valid_both_XIs",good,
                  "invalid",dict(failures),"position_codes",dict(codes),flush=True)
            assert len(matches)>0, name+" no games in 2026/27"
            assert good==len(matches), name+" has incomplete starting sheets"
            db.close();dbfile.unlink();arch.unlink()
if __name__=="__main__":
    main()
