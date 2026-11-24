"""Read-only Ligue 1 season 2026-27 11footy source audit.

Checks BOTH real teams' 11 unique named starters and pitch positions.
Does not write to Neon or call paid providers.
"""
from collections import Counter,defaultdict
from pathlib import Path
import tempfile,lzma,sqlite3
from archive_11footy import BASE_URL,_download,load_people,MAX_ARCHIVE_BYTES,MAX_DB_BYTES
from archive_pitch import pitch_from_codes

ARCHIVE="france.ligue-1.db.xz"

def run():
    with tempfile.TemporaryDirectory(prefix="lens-ligue1-") as temp:
        path=Path(temp)
        people=load_people(path)
        xz=path/ARCHIVE
        raw=path/"ligue1.sqlite"
        _download(BASE_URL+ARCHIVE,xz,MAX_ARCHIVE_BYTES)
        with lzma.open(xz) as src,raw.open("wb") as dst:
            n=0
            while True:
                data=src.read(1024*1024)
                if not data:break
                n+=len(data)
                if n>MAX_DB_BYTES:raise ValueError("Database uncompressed too large")
                dst.write(data)
        db=sqlite3.connect(raw)
        db.row_factory=sqlite3.Row
        print("COMPETITION_CODES_2026",[dict(x) for x in db.execute(
          "SELECT s.season,m.competition_code,m.status,COUNT(*) AS matches,"
          "MIN(m.local_date) AS first_day,MAX(m.local_date) AS last_day "
          "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
          "WHERE s.season=2026 GROUP BY s.season,m.competition_code,m.status "
          "ORDER BY m.competition_code,m.status")],flush=True)
        matches=list(db.execute(
          "SELECT m.match_id,m.home_team_id,m.away_team_id,m.competition_code,m.local_date "
          "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
          "WHERE s.season=2026 AND m.status='played' "
          "ORDER BY m.local_date,m.match_id"))
        ids=[m["match_id"] for m in matches]
        teams=defaultdict(lambda:defaultdict(list))
        for st in range(0,len(ids),80):
            subset=ids[st:st+80]
            placeholders=",".join("?" for _ in subset)
            for row in db.execute(
                "SELECT match_id,team_id,player_id,position_code FROM match_players "
                "WHERE started=1 AND match_id IN ("+placeholders+")",subset):
                teams[row["match_id"]][row["team_id"]].append(dict(row))
        counts=Counter();bad=Counter();positions=Counter();sample=[]
        for m in matches:
            tids=(m["home_team_id"],m["away_team_id"])
            xi=teams[m["match_id"]]
            if set(xi)!=set(tids):
                bad["team_count"]+=1
                continue
            try:
                for team in tids:
                    players=xi[team]
                    if any(p["player_id"] not in people for p in players):
                        raise ValueError("unnamed_player")
                    for p in players:positions[p["position_code"]]+=1
                    pitch_from_codes(players)
                counts[m["competition_code"]]+=1
                if len(sample)<3:sample.append([m["match_id"],m["local_date"],m["competition_code"]])
            except ValueError as error:
                bad[str(error)]+=1
        print("FULL_XIS_BY_CODE",dict(counts),flush=True)
        print("INVALID_XIS",dict(bad),flush=True)
        print("POSITIONS",dict(positions),flush=True)
        print("SAMPLE_GAMES",sample,flush=True)
        assert len(matches)>=50,"Unusually small historical league"
        assert sum(counts.values())==len(matches),"Historical XI incomplete"
        assert len(counts)==1, "Unexpected multiple competitions in French league"
        print("AUDIT_SUCCEEDED",len(matches),flush=True)
        db.close()

if __name__=="__main__":run()
