"""Lineup Lens: one-time import of confirmed historical 11footy XIs into Neon.

Source: https://github.com/fm-devlab/11footy-dataset
License: CC BY-NC 4.0. This importer is for the PRIVATE, NON-COMMERCIAL
Lineup Lens experiment only; source attribution stays in the app.
The snapshot is dated 10 Nov 2026 and DOES NOT imply today's live coverage.
No Soccer Data requests, no SharpVision or spreadsheet connections.
"""
from __future__ import annotations

import csv
import io
import lzma
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.request import Request, urlopen
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

import season_db
from archive_pitch import pitch_from_codes, ROLE

RELEASE = "11footy-2026-11-10"
BASE_URL = ("https://github.com/fm-devlab/11footy-dataset/"
            "releases/download/" + RELEASE + "/")
SPLITS = {"PL": "england.premier-league.db.xz", "SA": "italy.serie-a.db.xz",
          "BL": "germany.bundesliga.db.xz"}
ARCHIVE_SOURCE = "11footy"
USER_AGENT = "LineupLens-Personal-Research/1.0"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_PLAYER_ZIP_BYTES = 5 * 1024 * 1024
MAX_DB_BYTES = 220 * 1024 * 1024


class ArchiveProblem(ValueError):
    pass


def _download(url, out: Path, max_bytes: int) -> None:
    """Bounded download; do not follow arbitrary user-supplied URLs."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as res, out.open("wb") as dest:
        total = 0
        while True:
            chunk = res.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ArchiveProblem("Archive too large")
            dest.write(chunk)


def load_people(folder: Path) -> dict[int, str]:
    """11footy split league files contain player IDs but not player names."""
    path = folder / "players.csv.zip"
    _download(BASE_URL + "players.csv.zip", path, MAX_PLAYER_ZIP_BYTES)
    with zipfile.ZipFile(path) as zf:
        filenames = [name for name in zf.namelist()
                     if name.split("/")[-1] == "players.csv"]
        if len(filenames) != 1 or zf.getinfo(filenames[0]).file_size > 25_000_000:
            raise ArchiveProblem("Players reference file has unexpected structure")
        with zf.open(filenames[0]) as stream:
            reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"))
            if not {"player_id", "name"}.issubset(set(reader.fieldnames or [])):
                raise ArchiveProblem("Players reference file missing columns")
            people = {}
            for row in reader:
                pid = int(row["player_id"])
                name = (row["name"] or "").strip()
                if name:
                    people[pid] = name
    if len(people) < 300:
        raise ArchiveProblem("Player-name reference file unexpectedly small")
    return people


def read_season_rows(sqlite_file: Path, competition: str, people: dict[int, str]):
    """Only played 2026/27 matches with 11 distinct starters on BOTH teams."""
    con = sqlite3.connect(str(sqlite_file))
    con.row_factory = sqlite3.Row
    try:
        rows = list(con.execute(
            "SELECT m.match_id,m.home_team_id,m.away_team_id,m.kickoff_utc,"
            "m.local_date,m.competition_code,m.status,"
            "h.name AS home_name,a.name AS away_name,h.country AS home_country,"
            "a.country AS away_country "
            "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
            "JOIN teams h ON h.team_id=m.home_team_id "
            "JOIN teams a ON a.team_id=m.away_team_id "
            "WHERE s.season=2026 AND m.competition_code=? AND m.status='played' "
            "ORDER BY m.kickoff_utc,m.match_id", (competition,)
        ))
        if not rows:
            raise ArchiveProblem("No 2026-27 games found in "+competition)
        mids = [int(m["match_id"]) for m in rows]
        starters = defaultdict(lambda: defaultdict(list))
        # Small input (<=380 fixtures); no need to load decades of player records.
        for chunk_start in range(0, len(mids), 90):
            chunk = mids[chunk_start:chunk_start+90]
            marks = ",".join("?" for _ in chunk)
            sql = ("SELECT match_id,team_id,player_id,position_code,shirt_number "
                   "FROM match_players WHERE started=1 AND match_id IN ("+marks+")")
            for p in con.execute(sql, chunk):
                starters[int(p["match_id"])][int(p["team_id"])].append(p)
        full = []
        invalid = []
        for m in rows:
            mid = int(m["match_id"])
            home, away = int(m["home_team_id"]), int(m["away_team_id"])
            groups = starters.get(mid, {})
            acceptable = set(groups) == {home, away}
            for tid in (home, away):
                xi=groups.get(tid, [])
                ids=[int(p["player_id"]) for p in xi]
                if len(ids) != 11 or len(set(ids)) != 11 or not all(pid in people for pid in ids):
                    acceptable=False
            if not acceptable:
                invalid.append(mid)
                continue
            if not isinstance(m["kickoff_utc"], str) or not m["kickoff_utc"].endswith("Z"):
                invalid.append(mid)
                continue
            full.append((dict(m), groups))
        if invalid:
            raise ArchiveProblem(
                "%s has %s games with incomplete or unnamed official XIs; refusing partial import"
                % (competition, len(invalid))
            )
        return full
    finally:
        con.close()


def import_league(competition: str, people: dict[int, str], folder: Path) -> dict:
    if competition not in SPLITS:
        raise ArchiveProblem("Invalid league")
    if not season_db.enabled():
        raise ArchiveProblem("Dedicated Neon connection not configured")
    with season_db.db() as db:
        existing = db.execute(
            "SELECT imported_matches,last_match_date FROM archive_import_state "
            "WHERE source=%s AND release_name=%s AND competition_code=%s",
            (ARCHIVE_SOURCE,RELEASE,competition)
        ).fetchone()
        if existing:
            return {"competition":competition, "status":"already_imported",
                    "matches":existing["imported_matches"],
                    "last_match_date":str(existing["last_match_date"])}
    xz_path = folder / SPLITS[competition]
    db_path = folder / (competition + ".sqlite")
    _download(BASE_URL + SPLITS[competition], xz_path, MAX_ARCHIVE_BYTES)
    with lzma.open(xz_path, "rb") as src, db_path.open("wb") as out:
        n = 0
        while True:
            data=src.read(1024*1024)
            if not data: break
            n+=len(data)
            if n>MAX_DB_BYTES:
                raise ArchiveProblem("Uncompressed SQLite larger than safety limit")
            out.write(data)
    fixtures = read_season_rows(db_path, competition, people)
    player_ids = set()
    teams = {}
    starters = []
    matches = []
    latest_day = None
    for m, by_team in fixtures:
        mid=int(m["match_id"])
        h,a=int(m["home_team_id"]),int(m["away_team_id"])
        teams[h]=(h,m["home_name"],m["home_country"])
        teams[a]=(a,m["away_name"],m["away_country"])
        when=datetime.fromisoformat(m["kickoff_utc"].replace("Z","+00:00"))
        day=m["local_date"]
        latest_day=max(latest_day or day,day)
        matches.append((mid,2026,competition,when,day,h,a,RELEASE))
        for team_id,xi in by_team.items():
            for row in xi:
                pid=int(row["player_id"])
                player_ids.add(pid)
                starters.append((mid,team_id,pid,row["position_code"],row["shirt_number"]))
    with season_db.db() as db:
        with db.cursor() as cur:
            cur.executemany(
                "INSERT INTO archive_players(player_id,player_name) VALUES(%s,%s) "
                "ON CONFLICT(player_id) DO UPDATE SET player_name=EXCLUDED.player_name",
                [(p,people[p]) for p in sorted(player_ids)])
            cur.executemany(
                "INSERT INTO archive_teams(team_id,team_name,country) VALUES(%s,%s,%s) "
                "ON CONFLICT(team_id) DO UPDATE SET team_name=EXCLUDED.team_name,"
                "country=EXCLUDED.country",
                list(teams.values()))
            cur.executemany(
                "INSERT INTO archive_matches(match_id,season_year,competition_code,"
                "kickoff_utc,local_date,home_team_id,away_team_id,source_release) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(match_id) DO UPDATE SET "
                "source_release=EXCLUDED.source_release",
                matches)
            cur.executemany(
                "INSERT INTO archive_starters(match_id,team_id,player_id,"
                "position_code,jersey_number) VALUES(%s,%s,%s,%s,%s) "
                "ON CONFLICT(match_id,team_id,player_id) DO NOTHING",
                starters)
            cur.execute(
                "INSERT INTO archive_import_state(source,release_name,competition_code,"
                "state,imported_matches,last_match_date) "
                "VALUES(%s,%s,%s,'complete',%s,%s) ON CONFLICT DO NOTHING",
                (ARCHIVE_SOURCE,RELEASE,competition,len(matches),latest_day))
    return {"competition":competition, "status":"imported",
            "matches":len(matches),"starter_rows":len(starters),
            "last_match_date":latest_day}


def import_all(log=print) -> list[dict]:
    """Idempotent private backfill. An error rolls back the affected league."""
    if not season_db.enabled():
        log("Archive import skipped: Lineup Lens Neon not configured")
        return []
    with tempfile.TemporaryDirectory(prefix="lineup-11footy-") as directory:
        folder=Path(directory)
        with season_db.db() as db:
            done = db.execute(
                "SELECT competition_code FROM archive_import_state "
                "WHERE source=%s AND release_name=%s AND state='complete'",
                (ARCHIVE_SOURCE,RELEASE)).fetchall()
        pending=[c for c in SPLITS if c not in {r["competition_code"] for r in done}]
        if not pending:
            log("Archive already imported; no download required")
            return []
        people=load_people(folder)
        log("Archive player reference loaded (%d names)" % len(people))
        results=[]
        for code in pending:
            results.append(import_league(code,people,folder))
            log("11footy archive import: "+str(results[-1]))
            # Do not hold both unpacked SQLite league files simultaneously.
            for path in (folder/SPLITS[code],folder/(code+".sqlite")):
                path.unlink(missing_ok=True)
        return results


def archive_status():
    with season_db.db() as db:
        imports = db.execute(
            "SELECT competition_code AS league,imported_matches AS games,"
            "last_match_date AS latest,completed_at "
            "FROM archive_import_state WHERE source=%s AND release_name=%s "
            "ORDER BY competition_code",
            (ARCHIVE_SOURCE,RELEASE)).fetchall()
        count = db.execute("SELECT COUNT(*)::int AS n FROM archive_starters").fetchone()
        return {"source":ARCHIVE_SOURCE,"release":RELEASE,"license":"CC BY-NC 4.0",
                "source_url":"https://github.com/fm-devlab/11footy-dataset",
                "status":list(imports),"starter_rows":count["n"],
                "note":"Archived match-day starters only: snapshot through 8 Nov 2026. Not today's live lineups."}


def archive_teams(competition: str):
    if competition not in SPLITS: raise ArchiveProblem("Invalid league")
    with season_db.db() as db:
        rows=db.execute(
            "SELECT DISTINCT t.team_id,t.team_name,"
            "(SELECT COUNT(*)::int FROM archive_matches m WHERE m.competition_code=%s "
            "AND (m.home_team_id=t.team_id OR m.away_team_id=t.team_id)) AS played "
            "FROM archive_teams t JOIN archive_matches m "
            "ON t.team_id IN (m.home_team_id,m.away_team_id) "
            "WHERE m.competition_code=%s ORDER BY t.team_name",
            (competition,competition)).fetchall()
    return list(rows)


def team_history(competition: str, team_id: int):
    if competition not in SPLITS or not isinstance(team_id,int) or team_id <= 0:
        raise ArchiveProblem("Invalid team request")
    with season_db.db() as db:
        team=db.execute(
            "SELECT team_name FROM archive_teams WHERE team_id=%s", (team_id,)
        ).fetchone()
        if not team: raise ArchiveProblem("Unknown team")
        played=db.execute(
            "SELECT COUNT(*)::int AS n,MAX(local_date) AS latest "
            "FROM archive_matches WHERE competition_code=%s AND season_year=2026 "
            "AND (home_team_id=%s OR away_team_id=%s)",
            (competition,team_id,team_id)).fetchone()
        rows=db.execute(
            "SELECT s.player_id,p.player_name,COUNT(DISTINCT s.match_id)::int AS starts "
            "FROM archive_starters s JOIN archive_matches m ON s.match_id=m.match_id "
            "JOIN archive_players p ON s.player_id=p.player_id "
            "WHERE s.team_id=%s AND m.competition_code=%s AND m.season_year=2026 "
            "GROUP BY s.player_id,p.player_name ORDER BY starts DESC,p.player_name",
            (team_id,competition)).fetchall()
    return {"team_id":team_id,"team_name":team["team_name"],
            "competition":competition,"season":"2026-27",
            "verified_matches":played["n"],
            "last_verified_date":str(played["latest"]) if played["latest"] else None,
            "is_full_current_season":False,
            "players":list(rows),"source":ARCHIVE_SOURCE,"release":RELEASE,
            "latest_match":latest_archive_match(competition,team_id),
            "note":"Συμμετοχές ΒΑΣΙΚΩΝ έως την ημερομηνία αρχείου, όχι έως σήμερα."}


def latest_archive_match(competition: str, team_id: int) -> dict | None:
    """Last REAL archived team match with both XIs and matching starts at that date.

    Never returns a predicted or today's lineup. The denominator is exactly
    the validated fixture count through this match in the stored archive.
    """
    if competition not in SPLITS or not isinstance(team_id,int) or team_id<=0:
        raise ArchiveProblem("Invalid team request")
    with season_db.db() as db:
        m=db.execute(
            "SELECT m.match_id,m.kickoff_utc,m.local_date,m.home_team_id,m.away_team_id,"
            "ht.team_name AS home_name, at.team_name AS away_name "
            "FROM archive_matches m "
            "JOIN archive_teams ht ON ht.team_id=m.home_team_id "
            "JOIN archive_teams at ON at.team_id=m.away_team_id "
            "WHERE m.season_year=2026 AND m.competition_code=%s "
            "AND (m.home_team_id=%s OR m.away_team_id=%s) "
            "ORDER BY m.kickoff_utc DESC,m.match_id DESC LIMIT 1",
            (competition,team_id,team_id)
        ).fetchone()
        if not m: return None
        xi=db.execute(
            "SELECT s.team_id,s.player_id,p.player_name,"
            "s.position_code,s.jersey_number "
            "FROM archive_starters s JOIN archive_players p ON p.player_id=s.player_id "
            "WHERE s.match_id=%s ORDER BY s.team_id,s.player_id",
            (m["match_id"],)
        ).fetchall()
        counts=db.execute(
            "SELECT s.team_id,s.player_id,COUNT(DISTINCT s.match_id)::int AS starts "
            "FROM archive_starters s JOIN archive_matches m ON m.match_id=s.match_id "
            "WHERE m.season_year=2026 AND m.competition_code=%s "
            "AND m.kickoff_utc <= %s AND s.team_id IN (%s,%s) "
            "GROUP BY s.team_id,s.player_id",
            (competition,m["kickoff_utc"],m["home_team_id"],m["away_team_id"])
        ).fetchall()
        played={}
        for tid in (m["home_team_id"],m["away_team_id"]):
            played[tid]=db.execute(
                "SELECT COUNT(*)::int AS n FROM archive_matches "
                "WHERE competition_code=%s AND season_year=2026 AND kickoff_utc<=%s "
                "AND (home_team_id=%s OR away_team_id=%s)",
                (competition,m["kickoff_utc"],tid,tid)
            ).fetchone()["n"]
    starts={(r["team_id"],r["player_id"]):r["starts"] for r in counts}
    sides={}
    for side,tid,name in (("home",m["home_team_id"],m["home_name"]),
                          ("away",m["away_team_id"],m["away_name"])):
        records=[dict(x) for x in xi if x["team_id"]==tid]
        try:
            formation,ordered=pitch_from_codes(records)
        except ValueError as exc:
            raise ArchiveProblem("Stored match has incomplete position data") from exc
        sides[side]={
            "id":tid,"name":name,"formation":formation,
            "played":played[tid],"verified":True, "archive":True,
            "starting_xi":[{
                "id":p["player_id"],"name":p["player_name"],
                "number":p["jersey_number"],"position":ROLE[p["position_code"]],
                "position_code":p["position_code"],
                "starts":starts.get((tid,p["player_id"]),0)
            } for p in ordered]
        }
    return {
        "match_id":m["match_id"],"date":str(m["local_date"]),
        "competition":competition,
        "home":sides["home"],"away":sides["away"],
        "formation_is_derived":True,
        "source":ARCHIVE_SOURCE,
        "historical":True,
        "current_lineup":False,
        "note":"Τελευταία καταγεγραμμένη επίσημη 11άδα, με θέσεις και ενάρξεις "
               "μέχρι την ημέρα του συγκεκριμένου ιστορικού αγώνα."
    }
