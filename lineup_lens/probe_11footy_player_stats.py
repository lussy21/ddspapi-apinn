"""Read-only pilot for 11footy bulk player statistics.

Run from lineup_lens: python probe_11footy_player_stats.py PL
Optional: --sqlite /path/to/unpacked.db (avoids download).
Uses the already approved private 11footy snapshot (CC BY-NC 4.0).
No Soccer Data calls, no database writes, no automatic deployment.
"""
import argparse
import json
import lzma
import sqlite3
import tempfile
from pathlib import Path
from collections import defaultdict, Counter

import archive_11footy as archive
import season_db

FIELDS = ("minutes_played", "goals", "assists", "shots", "shots_on_target",
          "key_passes", "fouls_committed", "fouls_suffered", "yellow_cards",
          "red_cards", "saves", "goals_conceded")

def audit(path, competition, expected):
    """Compare exact (match, team, player) IDs, not fuzzy names."""
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(player_match_statistics)")}
        required = {"match_id", "team_id", "player_id", *FIELDS}
        if not required <= cols:
            raise ValueError("Missing columns: " + ", ".join(sorted(required-cols)))
        source = defaultdict(set)
        for row in con.execute(
            "SELECT p.match_id,p.team_id,p.player_id FROM match_players p "
            "JOIN matches m ON m.match_id=p.match_id JOIN seasons s ON s.season_id=m.season_id "
            "WHERE s.season=2026 AND m.status='played' AND m.competition_code=? AND p.started=1",
            (competition,)):
            source[row["match_id"]].add((row["team_id"],row["player_id"]))
        counts = Counter()
        missing = []
        complete = []
        for mid, xi in sorted(expected.items()):
            if len(xi) != 22 or source.get(mid) != xi:
                counts["xi_mismatch"] += 1
                missing.append(mid)
                continue
            rows = list(con.execute(
                "SELECT team_id,player_id,"+",".join(FIELDS)+
                " FROM player_match_statistics WHERE match_id=?", (mid,)))
            keys = [(r["team_id"],r["player_id"]) for r in rows]
            if len(keys) != len(set(keys)) or not xi <= set(keys):
                counts["missing_or_duplicate_player_rows"] += 1
                missing.append(mid)
                continue
            starters = [r for r in rows if (r["team_id"],r["player_id"]) in xi]
            if any(r["minutes_played"] is None or not 0 <= r["minutes_played"] <= 130
                   for r in starters):
                counts["missing_or_invalid_minutes"] += 1
                missing.append(mid)
                continue
            counts["verified_matches"] += 1
            counts["verified_starters"] += 22
            counts["all_player_rows"] += len(rows)
            complete.append(mid)
            for field in FIELDS:
                counts["non_null_"+field] += sum(r[field] is not None for r in starters)
        return {"competition":competition,"release":archive.RELEASE,
                "archive_matches_checked":len(expected),"counts":dict(counts),
                "verified_match_ids":complete,"failed_match_ids":missing,
                "note":"NULL stays unknown; xG/advanced defensive stats are not in this probe."}
    finally:
        con.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("competition",choices=sorted(archive.SPLITS))
    parser.add_argument("--sqlite",type=Path)
    args = parser.parse_args()
    expected = defaultdict(set)
    with season_db.db() as db:
        rows=db.execute(
            "SELECT s.match_id,s.team_id,s.player_id FROM archive_starters s "
            "JOIN archive_matches m USING(match_id) WHERE m.competition_code=%s "
            "AND m.season_year=2026 AND m.source_release=%s",
            (args.competition,archive.RELEASE)).fetchall()
        for row in rows:
            expected[row["match_id"]].add((row["team_id"],row["player_id"]))
    if not expected:
        raise ValueError("No matching canonical fixtures in Neon")
    if args.sqlite:
        result=audit(args.sqlite,args.competition,expected)
    else:
        with tempfile.TemporaryDirectory(prefix="lineup-player-probe-") as tmp:
            compressed=Path(tmp)/"source.db.xz"
            unpacked=Path(tmp)/"source.db"
            archive._download(archive.BASE_URL+archive.SPLITS[args.competition],
                              compressed,archive.MAX_ARCHIVE_BYTES)
            total=0
            with lzma.open(compressed,"rb") as inp, unpacked.open("wb") as out:
                while True:
                    data=inp.read(1024*1024)
                    if not data:
                        break
                    total+=len(data)
                    if total>archive.MAX_DB_BYTES:
                        raise ValueError("Archive exceeds size limit")
                    out.write(data)
            result=audit(unpacked,args.competition,expected)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
