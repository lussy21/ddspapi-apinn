import os
import re
import unicodedata
from datetime import datetime
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

# APINN league id -> Sofascore uniqueTournamentId.
APINN_TO_SOFA_TOURNAMENT = {
    1980: 17,      # England - Premier League
    1842: 35,      # Germany - Bundesliga
    2036: 34,      # France - Ligue 1
    2081: 185,     # Greece - Super League
    2436: 23,      # Italy - Serie A
    2196: 8,       # Spain - La Liga
    1817: 38,      # Belgium - Pro League
    1913: 39,      # Denmark - Superliga
    2333: 20,      # Norway - Eliteserien
    1928: 37,      # Netherlands - Eredivisie
    2592: 52,      # Turkey - Super League
    1834: 325,     # Brazil - Serie A
    210697: 155,   # Argentina - Liga Profesional
    1728: 40,      # Sweden - Allsvenskan
    2663: 242,     # USA - MLS
    2627: 7,       # UEFA - Champions League
}

LEAGUE_NAME_TO_SOFA_TOURNAMENT = {
    "finland - veikkausliiga": 41,
    "scotland - premiership": 36,
    "uefa - europa league": 679,
    "uefa - conference league": 17015,
}

DROP_TOKENS = {
    "fc", "cf", "afc", "sc", "fk", "sk", "vfb", "ac",
}

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

    tokens = [token for token in text.split() if token not in DROP_TOKENS]
    text = " ".join(tokens)

    if text in ALIASES:
        text = ALIASES[text]

    return text


def team_score(a, b):
    a = normalize_team(a)
    b = normalize_team(b)

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.96

    seq = SequenceMatcher(None, a, b).ratio()
    ta = set(a.split())
    tb = set(b.split())
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    return max(seq, jaccard)


def sofa_tournament_id(apinn_league_id, league_name):
    try:
        league_id = int(apinn_league_id)
    except (TypeError, ValueError):
        league_id = None

    if league_id in APINN_TO_SOFA_TOURNAMENT:
        return APINN_TO_SOFA_TOURNAMENT[league_id]

    return LEAGUE_NAME_TO_SOFA_TOURNAMENT.get(
        str(league_name or "").strip().lower()
    )


def apify_post(url, token, payload, timeout=180):
    response = requests.post(
        url,
        params={"token": token},
        json=payload,
        headers={"Accept": "application/json"},
        timeout=timeout,
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
        APIFY_FIXTURES_URL,
        token,
        {
            "sports": ["football"],
            "liveOnly": False,
            "dateFrom": date_str,
            "dateTo": date_str,
            "tournamentIds": ids,
            "maxItems": 500,
        },
    )


def fetch_votes(token, event_ids):
    ids = sorted({int(value) for value in event_ids if value})
    if not ids:
        return []

    return apify_post(
        APIFY_MATCH_URL,
        token,
        {
            "eventIds": ids,
            "includeStatistics": False,
            "includeLineups": False,
            "includeIncidents": False,
            "includeShotmap": False,
            "includeGraph": False,
            "includeAveragePositions": False,
            "includeBestPlayers": False,
            "includeTeamStreaks": False,
            "includeVotes": True,
            "includeWinProbability": False,
            "includeManagers": False,
            "includeH2H": False,
            "includeOdds": False,
            "includeComments": False,
            "includeHeatmaps": False,
            "maxItems": len(ids),
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
    best = None
    best_score = 0.0

    for item in fixtures:
        sofa_home = (item.get("homeTeam") or {}).get("name") or ""
        sofa_away = (item.get("awayTeam") or {}).get("name") or ""

        hs = team_score(home, sofa_home)
        aws = team_score(away, sofa_away)
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
            # Exact/near kickoff gets a small bonus.
            combined += max(0.0, 0.05 - (diff_minutes / 2400))

        if combined > best_score:
            best_score = combined
            best = item

    if best is None or best_score < 0.76:
        return None

    return best


def favorite_vote_metric(item, favorite_side):
    votes_root = item.get("votes") or {}
    poll = votes_root.get("vote") or votes_root

    def number(key):
        try:
            return int(float(poll.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    vote1 = number("vote1")
    votex = number("voteX")
    vote2 = number("vote2")
    total = vote1 + votex + vote2

    if total <= 0:
        return None

    favorite_votes = vote1 if favorite_side == "H" else vote2
    favorite_pct = int((favorite_votes * 100 / total) + 0.5)

    return {
        "favorite_pct": favorite_pct,
        "total_votes": total,
        "vote1": vote1,
        "voteX": votex,
        "vote2": vote2,
    }


def main():
    apify_token = os.environ.get("APIFY_TOKEN", "").strip()
    apinn_key = os.environ.get("APINN_API_KEY", "").strip()

    if not apify_token:
        print("SOFASCORE: APIFY_TOKEN missing - skipped")
        return
    if not apinn_key:
        print("SOFASCORE: APINN_API_KEY missing - skipped")
        return

    now = datetime.now(GREECE_TZ)

    # SofaScore snapshots only twice per day: 13:00 and 17:00 Athens time.
    # Render runs every 10 minutes, so minute < 10 ensures only the first run
    # in each target hour performs SofaScore API calls.
    if now.hour not in (13, 17) or now.minute >= 10:
        print("SOFASCORE: outside 13:00/17:00 snapshot window - skipped")
        return

    snapshot_label = f"{now.hour:02d}:00"
    print("SOFASCORE SNAPSHOT:", snapshot_label)

    creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(SHEET_KEY).worksheet(SHEET_NAME)
    rows = sheet.get_all_values()

    # R = APINN event id, D = favourite H/A, N = SofaScore %.
    sheet_by_event = {}
    for row_number, row in enumerate(rows, start=1):
        if row_number < 3 or len(row) < 18:
            continue
        event_id = str(row[17]).strip() if len(row) >= 18 else ""
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

    # One APINN board request. We only care about events already present in the sheet.
    response = requests.get(
        APINN_BOARD_URL,
        headers={"X-API-Key": apinn_key},
        params={
            "sport_id": 29,
            "live": 0,
            "with_odds": 1,
            "limit": 500,
        },
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

        if kickoff.date() != now.date():
            continue

        # At 13:00 and 17:00 we only refresh matches that have not started yet.
        if kickoff <= now:
            continue

        tournament_id = sofa_tournament_id(
            match.get("league_id"),
            match.get("league_name"),
        )
        if not tournament_id:
            print(
                "SOFASCORE TOURNAMENT NOT MAPPED:",
                match.get("league_name"),
                match.get("league_id"),
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

    # Fixtures are fetched only for the exact tournaments that have a candidate now.
    fixture_pool = []
    dates = sorted({item["sofa_date"] for item in candidates})

    for date_str in dates:
        tids = {
            item["tournament_id"]
            for item in candidates
            if item["sofa_date"] == date_str
        }
        fixtures = fetch_fixtures(apify_token, date_str, tids)
        fixture_pool.extend(fixtures)
        print(
            "SOFASCORE FIXTURES:", date_str,
            "| tournaments:", sorted(tids),
            "| matches:", len(fixtures),
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
            "SOFASCORE MATCH:",
            item["home"], "vs", item["away"],
            "| sofa event:", sofa_event_id,
        )

    if not matched:
        print("SOFASCORE: no matched events")
        return

    vote_rows = fetch_votes(
        apify_token,
        [item["sofa_event_id"] for item in matched],
    )
    votes_by_event = {
        str(item.get("eventId")): item
        for item in vote_rows
        if item.get("eventId") is not None
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
            "| vote 1/X/2:",
            metric["vote1"], metric["voteX"], metric["vote2"],
            "| total:", metric["total_votes"],
            "| favorite %:", metric["favorite_pct"],
        )

    if updates:
        sheet.batch_update(updates, value_input_option="USER_ENTERED")
        print("SOFASCORE SHEET UPDATED:", len(updates), "matches")
    else:
        print("SOFASCORE: nothing to write")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Keep the separate SofaScore step from affecting the already-working main job.
        print("SOFASCORE ERROR:", repr(exc))
