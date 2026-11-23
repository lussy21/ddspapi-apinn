"""Unit tests for full-season source validation. No DB credentials required."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from archive_11footy import read_season_rows, ArchiveProblem


def sample_sqlite(file: Path, corrupt=False):
    conn=sqlite3.connect(file)
    conn.executescript("""
    CREATE TABLE seasons(season_id INTEGER PRIMARY KEY,season INTEGER);
    CREATE TABLE teams(team_id INTEGER PRIMARY KEY,name TEXT,country TEXT);
    CREATE TABLE matches(match_id INTEGER PRIMARY KEY,season_id INTEGER,competition_code TEXT,
      status TEXT,kickoff_utc TEXT,local_date TEXT,home_team_id INTEGER,away_team_id INTEGER);
    CREATE TABLE match_players(match_id INTEGER,team_id INTEGER,player_id INTEGER,
      started INTEGER,position_code TEXT,shirt_number INTEGER);
    INSERT INTO seasons VALUES(11,2026);
    INSERT INTO teams VALUES(1,'Everton','England');
    INSERT INTO teams VALUES(2,'Brentford','England');
    INSERT INTO matches VALUES(9,11,'PL','played','2026-11-08T20:00:00Z','2026-11-08',1,2);
    """)
    data=[]
    for tid in (1,2):
        for i in range(11):
            pid=tid*100+i
            data.append((9,tid,pid,1,"G" if i==0 else "M",i+1))
    if corrupt: data.pop()
    conn.executemany("INSERT INTO match_players VALUES(?,?,?,?,?,?)",data)
    conn.commit()
    conn.close()
    return {tid*100+i:f"Player_{tid}_{i}" for tid in (1,2) for i in range(11)}


class ImportValidation(unittest.TestCase):
    def test_reject_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn=Path(tmp)/"test.db"
            people=sample_sqlite(fn,True)
            with self.assertRaises(ArchiveProblem):
                read_season_rows(fn,"PL",people)

    def test_accept_two_sides_with_real_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn=Path(tmp)/"test.db"
            people=sample_sqlite(fn)
            rows=read_season_rows(fn,"PL",people)
            self.assertEqual(len(rows),1)
            self.assertEqual([len(rows[0][1][tid]) for tid in (1,2)],[11,11])

    def test_reject_unknown_player_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn=Path(tmp)/"test.db"
            people=sample_sqlite(fn)
            del people[100]
            with self.assertRaises(ArchiveProblem):
                read_season_rows(fn,"PL",people)

if __name__=="__main__":unittest.main()
