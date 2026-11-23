"""Lineup Lens's own persistent season history (independent from SharpVision).

Only the LINEUP_DATABASE_URL secret is used. Never imports or edits a sheet.
Historical counts derive exclusively from 11-player *confirmed* team sheets.
"""
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import psycopg
from psycopg.rows import dict_row
from season_core import normalize_official, InvalidXI

URL = os.getenv("LINEUP_DATABASE_URL", "").strip()

def enabled():
    return bool(URL)

@contextmanager
def db():
    if not URL:
        raise RuntimeError("Η βάση ιστορικού Lineup Lens δεν έχει συνδεθεί.")
    with psycopg.connect(URL, connect_timeout=12, row_factory=dict_row) as conn:
        yield conn

def _when(s):
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def last_scan(mid_match, team_id):
    with db() as conn:
        result = conn.execute(
            "SELECT fixture_list_at,total_finished FROM season_sync_state "
            "WHERE team_id=%s AND season_id=%s AND competition_id=%s",
            (team_id, mid_match["season_id"], mid_match["competition_id"]),
        ).fetchone()
    return result

def record_fixture_list(current_match, team_id, listing):
    """Store all earlier FINISHED season fixtures, once per provider scan.

    A provider response of 100 fixtures may be truncated and is not accepted.
    This prevents fabricated full-season denominators.
    """
    if not isinstance(listing, list) or len(listing) >= 100:
        raise ValueError("Η λίστα αγώνων είναι ελλιπής ή έχει ξεπεράσει τις 100 εγγραφές.")
    cutoff = _when(current_match["utc_date"])
    sid = current_match["season_id"]
    cid = current_match["competition_id"]
    fixtures = []
    for m in listing:
        if not isinstance(m, dict) or m.get("season_id") != sid or m.get("competition_id") != cid:
            continue
        home = (m.get("home_team") or {}).get("id")
        away = (m.get("away_team") or {}).get("id")
        try:
            time = _when(m["utc_date"])
        except (TypeError, KeyError, ValueError, AttributeError):
            continue
        if (m.get("id") != current_match["id"] and time < cutoff
                and team_id in (home, away) and home != away
                and isinstance(m.get("id"), str) and m["id"].startswith("match_")):
            fixtures.append((m["id"], cid, sid, time, home, away, "finished"))
    fixtures = list({m[0]: m for m in fixtures}.values())
    with db() as conn:
        for item in fixtures:
            conn.execute(
                "INSERT INTO season_matches(match_id,competition_id,season_id,kickoff_utc,"
                "home_team_id,away_team_id,status) VALUES(%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(match_id) DO UPDATE SET status=EXCLUDED.status,"
                "last_seen_at=NOW()", item)
        conn.execute(
            "INSERT INTO season_sync_state(team_id,season_id,competition_id,total_finished,"
            "fixture_list_at) VALUES(%s,%s,%s,%s,NOW()) "
            "ON CONFLICT(team_id,season_id,competition_id) DO UPDATE "
            "SET fixture_list_at=NOW(),total_finished=EXCLUDED.total_finished",
            (team_id, sid, cid, len(fixtures)))
    return len(fixtures)

def record_confirmed(current_match, lineup, source_reference):
    """Atomically add both teams' official starting XI, never a predicted XI."""
    norm = normalize_official(current_match, lineup, source_reference)
    home, away = norm["teams"]
    status = str(current_match.get("status") or "scheduled").lower()
    with db() as conn:
        conn.execute(
            "INSERT INTO season_matches(match_id,competition_id,season_id,kickoff_utc,"
            "home_team_id,away_team_id,status) VALUES(%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(match_id) DO UPDATE SET status=CASE "
            "WHEN EXCLUDED.status='finished' THEN 'finished' ELSE season_matches.status END,"
            "last_seen_at=NOW()",
            (norm["match_id"], norm["competition_id"], norm["season_id"],
             norm["kickoff_utc"], home["id"], away["id"], status),
        )
        for team in norm["teams"]:
            conn.execute(
                "INSERT INTO season_official_lineups(match_id,team_id,source_name,"
                "source_reference,verified_at) VALUES(%s,%s,%s,%s,NOW()) "
                "ON CONFLICT(match_id,team_id) DO NOTHING",
                (norm["match_id"], team["id"], norm["source"], norm["source_reference"]),
            )
            for player in team["starters"]:
                conn.execute(
                    "INSERT INTO season_starters(match_id,team_id,player_id,player_name,"
                    "position_code,jersey_number) VALUES(%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(match_id,team_id,player_id) DO NOTHING",
                    (norm["match_id"], team["id"], player["id"], player["name"],
                     player["position"], player["number"]),
                )
        conn.execute(
            "INSERT INTO season_lineup_attempts(match_id,result,checked_at,retry_after) "
            "VALUES(%s,'confirmed',NOW(),NULL) "
            "ON CONFLICT(match_id) DO UPDATE SET result='confirmed',"
            "checked_at=NOW(),retry_after=NULL", (norm["match_id"],))
    return norm

def record_missing(match_id):
    with db() as conn:
        conn.execute(
            "INSERT INTO season_lineup_attempts(match_id,result,checked_at,retry_after) "
            "VALUES(%s,'missing',NOW(),NOW()+INTERVAL '24 hours') "
            "ON CONFLICT(match_id) DO UPDATE SET result='missing',checked_at=NOW(),"
            "retry_after=NOW()+INTERVAL '24 hours'", (match_id,))

def pending_matches(match, team_id, limit):
    """Only call the provider for completed fixtures lacking an official XI."""
    with db() as conn:
        return conn.execute(
            "SELECT m.match_id,m.kickoff_utc FROM season_matches m "
            "LEFT JOIN season_complete_xi x ON x.match_id=m.match_id AND x.team_id=%s "
            "LEFT JOIN season_lineup_attempts a ON a.match_id=m.match_id "
            "WHERE m.season_id=%s AND m.competition_id=%s AND m.status='finished' "
            "AND m.kickoff_utc < %s AND (m.home_team_id=%s OR m.away_team_id=%s) "
            "AND x.match_id IS NULL "
            "AND (a.retry_after IS NULL OR a.retry_after<NOW()) "
            "ORDER BY m.kickoff_utc DESC LIMIT %s",
            (team_id, match["season_id"], match["competition_id"], _when(match["utc_date"]),
             team_id, team_id, limit),
        ).fetchall()

def summary(match, team_id):
    """Full-season ratio is certified only when every finished fixture has 11 starters.

    Any missing official team sheet means each 'starts' count is a lower bound,
    clearly marked as such in the browser.
    """
    with db() as conn:
        state = conn.execute(
            "SELECT fixture_list_at,total_finished FROM season_sync_state "
            "WHERE team_id=%s AND season_id=%s AND competition_id=%s",
            (team_id, match["season_id"], match["competition_id"]),
        ).fetchone()
        if not state:
            return {"ready": False, "played": None, "official": 0, "starts": {},
                    "verified": False, "missing": None, "pending": 0,
                    "message": "Δεν έχει γίνει ακόμα συλλογή αγώνων για αυτή τη σεζόν."}
        summary_row = conn.execute(
            "SELECT COUNT(*)::int AS played,COUNT(x.match_id)::int AS official "
            "FROM season_matches m "
            "LEFT JOIN season_complete_xi x ON x.match_id=m.match_id AND x.team_id=%s "
            "WHERE m.season_id=%s AND m.competition_id=%s AND m.status='finished' "
            "AND m.kickoff_utc<%s AND (m.home_team_id=%s OR m.away_team_id=%s)",
            (team_id, match["season_id"], match["competition_id"], _when(match["utc_date"]),
             team_id, team_id),
        ).fetchone()
        starts_rows = conn.execute(
            "SELECT s.player_id,COUNT(DISTINCT s.match_id)::int AS starts "
            "FROM season_starters s JOIN season_matches m ON m.match_id=s.match_id "
            "JOIN season_complete_xi x ON x.match_id=s.match_id AND x.team_id=s.team_id "
            "WHERE s.team_id=%s AND m.season_id=%s AND m.competition_id=%s "
            "AND m.status='finished' AND m.kickoff_utc<%s "
            "GROUP BY s.player_id",
            (team_id, match["season_id"], match["competition_id"], _when(match["utc_date"])),
        ).fetchall()
        pending = conn.execute(
            "SELECT COUNT(*)::int AS n FROM season_matches m "
            "LEFT JOIN season_complete_xi x ON x.match_id=m.match_id AND x.team_id=%s "
            "WHERE m.season_id=%s AND m.competition_id=%s AND m.status='finished' "
            "AND m.kickoff_utc<%s AND (m.home_team_id=%s OR m.away_team_id=%s) "
            "AND x.match_id IS NULL",
            (team_id, match["season_id"], match["competition_id"], _when(match["utc_date"]),
             team_id, team_id),
        ).fetchone()["n"]
    played, official = summary_row["played"], summary_row["official"]
    # A truncated/inconsistent listing must never be labeled complete.
    complete = (played == state["total_finished"] and played == official)
    return {"ready": True, "played": played, "official": official,
            "starts": {r["player_id"]: r["starts"] for r in starts_rows},
            "verified": complete, "missing": max(0, played-official),
            "pending": pending, "source": "confirmed_official_lineups",
            "message": "Ολόκληρη η σεζόν" if complete else
            "Μερική κάλυψη επίσημων ενδεκάδων — οι ενάρξεις είναι κατώτατα όρια."}
