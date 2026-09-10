import os
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import gspread
import requests
from google.oauth2.service_account import Credentials

GREECE_TZ = ZoneInfo("Europe/Athens")
UTC_TZ = ZoneInfo("UTC")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_KEY = "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM"
SHEET_NAME = "PINNACLE"
GOOGLE_CREDS = "/etc/secrets/google-credentials.json"

APINN_BOARD_URL = "https://api.apinn.io/api/board"
APIFY_FIXTURES_URL = (
    "https://api.apify.com/v2/acts/"
    "incognito_mode~sofascore-live-scores-scraper/"
    "run-sync-get-dataset-items"
)
APIFY_MATCH_URL = (
    "https://api.apify.com/v2/acts/"
    "incognito_mode~sofascore-match-analytics-scraper/"
    "run-sync-get-dataset-items"
)

APINN_TO_SOFA_TOURNAMENT = {
    1980: 17, 1842: 35, 2036: 34, 2081: 185, 2436: 23, 2196: 8,
    1817: 38, 1913: 39, 2333: 20, 1928: 37, 2592: 52, 1834: 325,
    210697: 155, 1728: 40, 2663: 242, 2627: 7,
}

LEAGUE_NAME_TO_SOFA_TOURNAMENT = {
    "england - premier league": 17,
    "germany - bundesliga": 35,
    "france - ligue 1": 34,
    "greece - super league": 185,
    "italy - serie a": 23,
    "spain - la liga": 8,
    "belgium - pro league": 38,
    "denmark - superliga": 39,
    "norway - eliteserien": 20,
    "netherlands - eredivisie": 37,
    "turkey - super league": 52,
    "turkey - super lig": 52,
    "brazil - serie a": 325,
    "argentina - liga profesional": 155,
    "sweden - allsvenskan": 40,
    "usa - mls": 242,
    "mls": 242,
    "uefa - champions league": 7,
    "finland - veikkausliiga": 41,
    "scotland - premiership": 36,
    "uefa - europa league": 679,
    "uefa - conference league": 17015,
}

DROP_TOKENS = {"fc", "cf", "afc", "sc", "fk", "sk", "vfb", "ac"}

ALIASES = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "manchester utd": "manchester united",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "sporting cp": "sporting lisbon",
    "sporting club de portugal": "sporting lisbon",
    "atletico de madrid": "atletico madrid",
    "club atletico de madrid": "atletico madrid",
    "bayern munchen": "bayern munich",
    "fc bayern munchen": "bayern munich",
    "internazionale": "inter milan",
    "inter": "inter milan",
}


def _ascii_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    replacements = {
        "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
        "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def normalize_team(value):
    text = _ascii_text(value).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in ALIASES:
        text = ALIASES[text]
    text = " ".join(token for token in text.split() if token not in DROP_TOKENS)
    if text in ALIASES:
        text = ALIASES[text]
    return text


def team_score(a, b):
    a, b = normalize_team(a), normalize_team(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.96
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    return max(seq, jaccard)


def sofa_tournament_id(apinn_league_id, league_name):
    try:
        league_id = int(apinn_league_id)
    except (TypeError, ValueError):
        league_id = None
    if league_id in APINN_TO_SOFA_TOURNAMENT:
        return APINN_TO_SOFA_TOURNAMENT[league_id]
    return LEAGUE_NAME_TO_SOFA_TOURNAMENT.get(str(league_name or "").strip().lower())


def sheet_league_tournament_id(league_name):
    name = str(league_name or "").strip().lower()
    if not name:
        return None
    if name in LEAGUE_NAME_TO_SOFA_TOURNAMENT:
        return LEAGUE_NAME_TO_SOFA_TOURNAMENT[name]
    checks = [
        ("premier league", 17), ("bundesliga", 35), ("ligue 1", 34),
        ("greece", 185), ("serie a", 23), ("la liga", 8),
        ("pro league", 38), ("superliga", 39), ("eliteserien", 20),
        ("eredivisie", 37), ("super lig", 52), ("allsvenskan", 40),
        ("mls", 242), ("champions league", 7), ("veikkausliiga", 41),
        ("scotland", 36), ("europa league", 679), ("conference league", 17015),
    ]
    for keyword, tournament_id in checks:
        if keyword in name:
            return tournament_id
    return None


def apify_post(url, token, payload, timeout=180):
    response = requests.post(
        url, params={"token": token}, json=payload,
        headers={"Accept": "application/json"}, timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected Apify dataset response")
    return data


def fetch_fixtures(token, date_str, tournament_ids):
    ids = sorted({int(value) for value in tournament_ids if value})
    if not ids:
        return []
    return apify_post(
        APIFY_FIXTURES_URL, token,
        {
            "sports": ["football"], "liveOnly": False,
            "dateFrom": date_str, "dateTo": date_str,
            "tournamentIds": ids, "maxItems": 500,
        },
    )


def fetch_votes(token, event_ids):
    ids = sorted({int(value) for value in event_ids if value})
    if not ids:
        return []
    return apify_post(
        APIFY_MATCH_URL, token,
        {
            "eventIds": ids,
            "includeStatistics": False, "includeLineups": False,
            "includeIncidents": False, "includeShotmap": False,
            "includeGraph": False, "includeAveragePositions": False,
            "includeBestPlayers": False, "includeTeamStreaks": False,
            "includeVotes": True, "includeWinProbability": False,
            "includeManagers": False, "includeH2H": False,
            "includeOdds": False, "includeComments": False,
            "includeHeatmaps": False, "maxItems": len(ids),
        },
    )


def parse_sofa_start(item):
    raw = item.get("startTimeIso")
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            pass
    ts = item.get("startTimestamp")
    if ts:
        try:
            return datetime.fromtimestamp(float(ts), UTC_TZ)
        except (TypeError, ValueError, OSError):
            pass
    return None


def find_sofa_match(home, away, kickoff, fixtures):
    best, best_score = None, 0.0
    for item in fixtures:
        sofa_home = (item.get("homeTeam") or {}).get("name") or ""
        sofa_away = (item.get("awayTeam") or {}).get("name") or ""
        hs, aws = team_score(home, sofa_home), team_score(away, sofa_away)
        combined = (hs + aws) / 2
        if hs < 0.68 or aws < 0.68:
            continue
        sofa_start = parse_sofa_start(item)
        if sofa_start is not None:
            if sofa_start.tzinfo is None:
                sofa_start = sofa_start.replace(tzinfo=UTC_TZ)
            diff_minutes = abs(
                (sofa_start.astimezone(GREECE_TZ) - kickoff).total_seconds()
            ) / 60
            if diff_minutes > 120:
                continue
            combined += max(0.0, 0.05 - (diff_minutes / 2400))
        if combined > best_score:
            best_score, best = combined, item
    return best if best is not None and best_score >= 0.76 else None


def favorite_vote_metric(item, favorite_side):
    votes_root = item.get("votes") or {}
    poll = votes_root.get("vote") or votes_root

    def number(key):
        try:
            return int(float(poll.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    vote1, votex, vote2 = number("vote1"), number("voteX"), number("vote2")
    total = vote1 + votex + vote2
    if total <= 0:
        return None
    favorite_votes = vote1 if favorite_side == "H" else vote2
    return {
        "favorite_pct": int((favorite_votes * 100 / total) + 0.5),
        "total_votes": total, "vote1": vote1, "voteX": votex, "vote2": vote2,
    }


def is_finished(item):
    status = item.get("status") or {}
    if isinstance(status, dict):
        status_type = str(status.get("type") or "").strip().lower()
        try:
            status_code = int(status.get("code") or 0)
        except (TypeError, ValueError):
            status_code = 0
        return status_type == "finished" or status_code == 100
    return str(status).strip().lower() == "finished"


def extract_score(value):
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("current", "display", "normaltime", "normalTime"):
            if value.get(key) is not None:
                try:
                    return int(float(value.get(key)))
                except (TypeError, ValueError):
                    pass
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def find_finished_match(home, away, fixtures):
    best, best_score = None, 0.0
    for item in fixtures:
        if not is_finished(item):
            continue
        sofa_home = (item.get("homeTeam") or {}).get("name") or ""
        sofa_away = (item.get("awayTeam") or {}).get("name") or ""
        hs, aws = team_score(home, sofa_home), team_score(away, sofa_away)
        if hs < 0.72 or aws < 0.72:
            continue
        combined = (hs + aws) / 2
        if combined > best_score:
            best_score, best = combined, item
    return best if best is not None and best_score >= 0.80 else None


def update_results(sheet, rows, apify_token, now):
    print("SOFASCORE RESULTS: starting")
    pending = []
    for row_number, row in enumerate(rows, start=1):
        if row_number < 3:
            continue
        league = row[0] if len(row) > 0 else ""
        home = row[1] if len(row) > 1 else ""
        away = row[2] if len(row) > 2 else ""
        result = row[15] if len(row) > 15 else ""
        if not home or not away or str(result).strip():
            continue
        tournament_id = sheet_league_tournament_id(league)
        if not tournament_id:
            print("SOFASCORE RESULT LEAGUE NOT MAPPED:", league, "|", home, "vs", away)
            continue
        pending.append({
            "row": row_number, "league": league, "home": home, "away": away,
            "tournament_id": tournament_id,
        })

    if not pending:
        print("SOFASCORE RESULTS: no blank results to check")
        return

    tournament_ids = {item["tournament_id"] for item in pending}
    if now.hour == 7:
        result_dates = [
            (now.date() - timedelta(days=1)).isoformat(),
            now.date().isoformat(),
        ]
    else:
        result_dates = [now.date().isoformat()]

    fixture_pool = []
    for date_str in result_dates:
        fixtures = fetch_fixtures(apify_token, date_str, tournament_ids)
        fixture_pool.extend(fixtures)
        print(
            "SOFASCORE RESULT FIXTURES:", date_str,
            "| tournaments:", sorted(tournament_ids), "| matches:", len(fixtures),
        )

    if not fixture_pool:
        print("SOFASCORE RESULTS: no fixtures returned")
        return

    updates = []
    for item in pending:
        same_tournament = []
        for fixture in fixture_pool:
            tournament = fixture.get("tournament") or {}
            try:
                fixture_tid = int(tournament.get("uniqueTournamentId") or 0)
            except (TypeError, ValueError):
                fixture_tid = 0
            if fixture_tid and fixture_tid != item["tournament_id"]:
                continue
            same_tournament.append(fixture)

        match = find_finished_match(item["home"], item["away"], same_tournament)
        if not match:
            print("SOFASCORE RESULT NOT FINISHED/FOUND:", item["home"], "vs", item["away"])
            continue

        home_score = extract_score(match.get("homeScore"))
        away_score = extract_score(match.get("awayScore"))
        if home_score is None or away_score is None:
            print("SOFASCORE RESULT SCORE MISSING:", item["home"], "vs", item["away"])
            continue

        result_text = f"{home_score}-{away_score}"
        updates.append({"range": f'P{item["row"]}', "values": [[result_text]]})
        print("SOFASCORE RESULT WRITE:", item["home"], "vs", item["away"], "|", result_text)

    if updates:
        sheet.batch_update(updates, value_input_option="USER_ENTERED")
        print("SOFASCORE RESULTS UPDATED:", len(updates), "matches")
    else:
        print("SOFASCORE RESULTS: nothing to write")


def update_votes(sheet, rows, apify_token, apinn_key, now):
    snapshot_label = f"{now.hour:02d}:00"
    print("SOFASCORE SNAPSHOT:", snapshot_label)

    sheet_by_event = {}
    for row_number, row in enumerate(rows, start=1):
        if row_number < 3 or len(row) < 18:
            continue
        event_id = str(row[17]).strip()
        if not event_id:
            continue
        sheet_by_event[event_id] = {
            "row": row_number,
            "home": row[1] if len(row) > 1 else "",
            "away": row[2] if len(row) > 2 else "",
            "favorite_side": row[3] if len(row) > 3 else "",
            "sofa_value": row[13] if len(row) > 13 else "",
        }

    if not sheet_by_event:
        print("SOFASCORE: no sheet events")
        return

    response = requests.get(
        APINN_BOARD_URL,
        headers={"X-API-Key": apinn_key},
        params={"sport_id": 29, "live": 0, "with_odds": 1, "limit": 500},
        timeout=30,
    )
    response.raise_for_status()
    board = response.json()

    candidates = []
    for match in board:
        event_id = str(match.get("event_id") or "").strip()
        sheet_item = sheet_by_event.get(event_id)
        if not sheet_item:
            continue
        starts = match.get("starts")
        if not starts:
            continue
        try:
            kickoff = datetime.fromisoformat(
                str(starts).replace("Z", "+00:00")
            ).astimezone(GREECE_TZ)
        except ValueError:
            continue
        if kickoff.date() != now.date() or kickoff <= now:
            continue
        tournament_id = sofa_tournament_id(match.get("league_id"), match.get("league_name"))
        if not tournament_id:
            print(
                "SOFASCORE TOURNAMENT NOT MAPPED:",
                match.get("league_name"), match.get("league_id"),
            )
            continue
        candidates.append({
            **sheet_item,
            "kickoff": kickoff,
            "tournament_id": tournament_id,
            "sofa_date": kickoff.astimezone(UTC_TZ).date().isoformat(),
        })

    if not candidates:
        print("SOFASCORE: no upcoming matches for this snapshot")
        return

    fixture_pool = []
    dates = sorted({item["sofa_date"] for item in candidates})
    for date_str in dates:
        tids = {
            item["tournament_id"] for item in candidates
            if item["sofa_date"] == date_str
        }
        fixtures = fetch_fixtures(apify_token, date_str, tids)
        fixture_pool.extend(fixtures)
        print(
            "SOFASCORE FIXTURES:", date_str,
            "| tournaments:", sorted(tids), "| matches:", len(fixtures),
        )

    matched = []
    for item in candidates:
        fixture = find_sofa_match(
            item["home"], item["away"], item["kickoff"], fixture_pool
        )
        if not fixture:
            print("SOFASCORE MATCH NOT FOUND:", item["home"], "vs", item["away"])
            continue
        sofa_event_id = fixture.get("eventId")
        if not sofa_event_id:
            continue
        matched.append({**item, "sofa_event_id": int(sofa_event_id)})
        print(
            "SOFASCORE MATCH:", item["home"], "vs", item["away"],
            "| sofa event:", sofa_event_id,
        )

    if not matched:
        print("SOFASCORE: no matched events")
        return

    vote_rows = fetch_votes(
        apify_token, [item["sofa_event_id"] for item in matched]
    )
    votes_by_event = {
        str(item.get("eventId")): item
        for item in vote_rows if item.get("eventId") is not None
    }

    updates = []
    for item in matched:
        vote_item = votes_by_event.get(str(item["sofa_event_id"]))
        if not vote_item:
            print("SOFASCORE VOTES NOT RETURNED:", item["home"], "vs", item["away"])
            continue
        metric = favorite_vote_metric(vote_item, item["favorite_side"])
        if not metric:
            print("SOFASCORE NO 1X2 VOTES:", item["home"], "vs", item["away"])
            continue
        updates.append({
            "range": f'N{item["row"]}',
            "values": [[metric["favorite_pct"]]],
        })
        print(
            f"SOFASCORE WRITE {snapshot_label}:",
            item["home"], "vs", item["away"],
            "| fav side:", item["favorite_side"],
            "| vote 1/X/2:", metric["vote1"], metric["voteX"], metric["vote2"],
            "| total:", metric["total_votes"],
            "| favorite %:", metric["favorite_pct"],
        )

    if updates:
        sheet.batch_update(updates, value_input_option="USER_ENTERED")
        print("SOFASCORE SHEET UPDATED:", len(updates), "matches")
    else:
        print("SOFASCORE: nothing to write")


def main():
    apify_token = os.environ.get("APIFY_TOKEN", "").strip()
    if not apify_token:
        print("SOFASCORE: APIFY_TOKEN missing - skipped")
        return

    now = datetime.now(GREECE_TZ)

    # Render runs every 10 minutes. Only these windows make paid SofaScore calls.
    vote_window = now.hour in (13, 17) and now.minute < 10
    result_window = (
        (now.hour == 7 and now.minute < 10)
        or (now.hour == 22 and 30 <= now.minute < 40)
    )

    if not vote_window and not result_window:
        print("SOFASCORE: outside scheduled windows - skipped")
        return

    creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(SHEET_KEY).worksheet(SHEET_NAME)
    rows = sheet.get_all_values()

    if result_window:
        update_results(sheet, rows, apify_token, now)
        return

    apinn_key = os.environ.get("APINN_API_KEY", "").strip()
    if not apinn_key:
        print("SOFASCORE: APINN_API_KEY missing - vote snapshot skipped")
        return

    update_votes(sheet, rows, apify_token, apinn_key, now)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("SOFASCORE ERROR:", repr(exc))
