import os
import re
import time
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
CACHE_SHEET_NAME = "SOFA CACHE"
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

SOFA_API_BASE = "https://api.sofascore.com/api/v1"
SOFA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}

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
    "argentina - liga pro": 155,
    "sweden - allsvenskan": 40,
    "usa - mls": 242,
    "usa - major league soccer": 242,
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


def apify_post(url, token, payload, timeout=180, attempts=3):
    """Call an Apify actor with bounded retries and useful diagnostics."""
    last_error = None
    for attempt in range(1, attempts + 1):
        response = requests.post(
            url, params={"token": token}, json=payload,
            headers={"Accept": "application/json"}, timeout=timeout,
        )
        if response.ok:
            data = response.json()
            if not isinstance(data, list):
                raise RuntimeError("Unexpected Apify dataset response")
            return data

        body = (response.text or "")[:1500].replace(token, "***")
        print(
            "APIFY POST ERROR:",
            response.status_code,
            "| attempt:", f"{attempt}/{attempts}",
            "| actor:", url.rsplit("/", 2)[-2],
            "| response:", body,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            last_error = exc

        # Actor runs can fail transiently even with valid input. Retry 400/429/5xx.
        if attempt < attempts and (
            response.status_code == 400
            or response.status_code == 429
            or response.status_code >= 500
        ):
            time.sleep(2 * attempt)
            continue
        if last_error is not None:
            raise last_error

    if last_error is not None:
        raise last_error
    raise RuntimeError("Apify request failed")


def sofa_get(path, attempts=3, timeout=20):
    """Small resilient GET wrapper for SofaScore's public JSON endpoints."""
    url = f"{SOFA_API_BASE}{path}"
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                headers=SOFA_HEADERS,
                timeout=timeout,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            print(
                "SOFASCORE DIRECT GET ERROR:",
                path,
                "| attempt:", attempt,
                "|", repr(exc),
            )
            if attempt < attempts:
                time.sleep(2 * attempt)
    if last_error is not None:
        raise last_error
    return None


def fetch_sofa_schedule(date_str):
    payload = sofa_get(f"/sport/football/scheduled-events/{date_str}")
    if not isinstance(payload, dict):
        return []
    events = payload.get("events") or []
    return events if isinstance(events, list) else []


def fetch_sofa_event(event_id):
    payload = sofa_get(f"/event/{int(event_id)}")
    if not isinstance(payload, dict):
        return None
    event = payload.get("event")
    return event if isinstance(event, dict) else None


def fetch_sofa_votes_direct(event_id):
    payload = sofa_get(f"/event/{int(event_id)}/votes", attempts=2)
    if not isinstance(payload, dict):
        return None
    vote = payload.get("vote") or payload.get("votes")
    if not isinstance(vote, dict):
        return None
    return {
        "eventId": int(event_id),
        "votes": {"vote": vote},
    }


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


def fetch_all_fixtures(token, date_str):
    """Fallback for national-team competitions whose Sofa tournament ID is not pre-mapped."""
    return apify_post(
        APIFY_FIXTURES_URL, token,
        {
            "sports": ["football"], "liveOnly": False,
            "dateFrom": date_str, "dateTo": date_str,
            "maxItems": 500,
        },
    )


def is_national_sheet_league(value):
    text = str(value or "").strip().lower()
    return (
        text.startswith("εθνικ")
        and "friendly" not in text
        and "friendlies" not in text
    )


def fetch_votes(token, event_ids):
    ids = sorted({int(value) for value in event_ids if value})
    if not ids:
        return []

    # Prefer SofaScore's own lightweight votes endpoint. Apify stays as a
    # fallback for transient direct-access blocks or endpoint changes.
    rows = []
    fallback_ids = []
    for event_id in ids:
        try:
            item = fetch_sofa_votes_direct(event_id)
        except Exception as exc:
            print("SOFASCORE DIRECT VOTES ERROR:", event_id, repr(exc))
            item = None
            fallback_ids.append(event_id)
        if item is not None:
            rows.append(item)
        else:
            fallback_ids.append(event_id)

    if not fallback_ids:
        return rows

    print("SOFASCORE VOTES APIFY FALLBACK:", len(fallback_ids), "events")
    batch_size = 5
    for start in range(0, len(fallback_ids), batch_size):
        batch = fallback_ids[start:start + batch_size]
        payload = {
            "eventIds": batch,
            "includeStatistics": False, "includeLineups": False,
            "includeIncidents": False, "includeShotmap": False,
            "includeGraph": False, "includeAveragePositions": False,
            "includeBestPlayers": False, "includeTeamStreaks": False,
            "includeVotes": True, "includeWinProbability": False,
            "includeManagers": False, "includeH2H": False,
            "includeOdds": False, "includeComments": False,
            "includeHeatmaps": False, "maxItems": len(batch),
        }
        try:
            rows.extend(
                apify_post(
                    APIFY_MATCH_URL, token, payload,
                    timeout=45, attempts=1,
                )
            )
        except requests.RequestException as exc:
            print("SOFASCORE VOTES FALLBACK BATCH FAILED:", batch, repr(exc))
    return rows

def load_sofa_cache(book):
    try:
        cache_sheet = book.worksheet(CACHE_SHEET_NAME)
    except gspread.WorksheetNotFound:
        cache_sheet = book.add_worksheet(
            title=CACHE_SHEET_NAME, rows=2000, cols=7
        )
        cache_sheet.update(
            "A1:G1",
            [[
                "APINN EVENT ID", "SOFA EVENT ID", "HOME", "AWAY", "DATE",
                "FINAL 90 DONE", "FINAL 90 AT",
            ]],
            value_input_option="USER_ENTERED",
        )
        try:
            cache_sheet.hide()
        except Exception:
            pass

    cache = {}
    final_done = set()
    cache_rows = {}
    for row_number, row in enumerate(cache_sheet.get_all_values()[1:], start=2):
        if len(row) < 2:
            continue
        apinn_event_id = str(row[0] or "").strip()
        sofa_event_id = str(row[1] or "").strip()
        if not apinn_event_id or not sofa_event_id:
            continue
        try:
            cache[apinn_event_id] = int(float(sofa_event_id))
            cache_rows[apinn_event_id] = row_number
        except (TypeError, ValueError):
            continue
        final_flag = str(row[5] if len(row) > 5 else "").strip().upper()
        if final_flag == "DONE":
            final_done.add(apinn_event_id)
    return cache_sheet, cache, final_done, cache_rows


def append_sofa_cache(cache_sheet, rows):
    if not rows:
        return
    cache_sheet.append_rows(
        [
            [
                item["apinn_event_id"],
                item["sofa_event_id"],
                item["home"],
                item["away"],
                item["kickoff"].date().isoformat(),
                "",
                "",
            ]
            for item in rows
        ],
        value_input_option="USER_ENTERED",
    )


def mark_final_done(cache_sheet, cache_rows, event_ids, now):
    updates = []
    stamp = now.strftime("%Y-%m-%d %H:%M")
    for event_id in event_ids:
        row_number = cache_rows.get(event_id)
        if not row_number:
            continue
        updates.append({
            "range": f"F{row_number}:G{row_number}",
            "values": [["DONE", stamp]],
        })
    if updates:
        cache_sheet.batch_update(updates, value_input_option="USER_ENTERED")


def run_one_off_result_catchup(book, sheet, rows, apify_token, now):
    cache_sheet = book.worksheet(CACHE_SHEET_NAME)

    # Keep historical repair markers separate so a new repair does not erase
    # the fact that the previous one completed.
    repairs = [
        ("H2", "RESULT CATCHUP 2026-09-24 DONE", "2026-09-24"),
        ("H3", "RESULT CATCHUP 2026-09-25 DONE", "2026-09-25"),
    ]
    for cell, target_marker, date_str in repairs:
        marker = str(cache_sheet.acell(cell).value or "").strip()
        if marker == target_marker:
            continue

        print("SOFASCORE ONE-OFF RESULT CATCHUP:", date_str)
        update_results(
            book,
            sheet,
            rows,
            apify_token,
            now,
            result_dates=[date_str],
        )
        cache_sheet.update(
            f"{cell}:{cell}",
            [[target_marker]],
            value_input_option="USER_ENTERED",
        )
        if cell == "H2":
            cache_sheet.update(
                "H1",
                [["ONE-OFF STATUS"]],
                value_input_option="USER_ENTERED",
            )
        print("SOFASCORE ONE-OFF RESULT CATCHUP SAVED:", date_str)
        return True

    return False


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


def update_results(book, sheet, rows, apify_token, now, result_dates=None):
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
        pending.append({
            "row": row_number,
            "league": league,
            "home": home,
            "away": away,
            "tournament_id": sheet_league_tournament_id(league),
            "national_match": is_national_sheet_league(league),
            "apinn_event_id": str(row[17] if len(row) > 17 else "").strip(),
        })

    if not pending:
        print("SOFASCORE RESULTS: no blank results to check")
        return

    if result_dates is None:
        if now.hour == 7:
            result_dates = [
                (now.date() - timedelta(days=1)).isoformat(),
                now.date().isoformat(),
            ]
        else:
            result_dates = [now.date().isoformat()]

    # Primary result source: SofaScore's own daily schedule JSON.
    # This avoids depending on a paid Actor just to read final scores.
    fixture_pool = []
    direct_schedule_failed = False
    for date_str in result_dates:
        try:
            fixtures = fetch_sofa_schedule(date_str)
            fixture_pool.extend(fixtures)
            print(
                "SOFASCORE DIRECT SCHEDULE:",
                date_str,
                "| events:", len(fixtures),
            )
        except Exception as exc:
            direct_schedule_failed = True
            print(
                "SOFASCORE DIRECT SCHEDULE ERROR:",
                date_str,
                repr(exc),
            )

    # Exact cached Sofa event IDs are a second independent matching path.
    # Restrict exact-event checks to the requested result date(s) so future
    # matches are not queried unnecessarily.
    cache_sheet, sofa_cache, _, _ = load_sofa_cache(book)
    target_dates = set(result_dates)
    cache_dates = {}
    for cache_row in cache_sheet.get_all_values()[1:]:
        if len(cache_row) < 5:
            continue
        apinn_id = str(cache_row[0] or "").strip()
        date_value = str(cache_row[4] or "").strip()
        if apinn_id and date_value:
            cache_dates[apinn_id] = date_value
    exact_cache = {}

    updates = []
    for item in pending:
        match = find_finished_match(
            item["home"], item["away"], fixture_pool
        )

        if match is None:
            sofa_id = sofa_cache.get(item["apinn_event_id"])
            cache_date = cache_dates.get(item["apinn_event_id"])
            if sofa_id and cache_date in target_dates:
                key = str(sofa_id)
                if key not in exact_cache:
                    try:
                        exact_cache[key] = fetch_sofa_event(sofa_id)
                    except Exception as exc:
                        exact_cache[key] = None
                        print(
                            "SOFASCORE DIRECT EVENT ERROR:",
                            sofa_id,
                            repr(exc),
                        )
                direct_match = exact_cache.get(key)
                if direct_match and is_finished(direct_match):
                    match = direct_match

        if not match:
            print(
                "SOFASCORE RESULT NOT FINISHED/FOUND:",
                item["home"], "vs", item["away"],
            )
            continue

        home_score = extract_score(match.get("homeScore"))
        away_score = extract_score(match.get("awayScore"))
        if home_score is None or away_score is None:
            print(
                "SOFASCORE RESULT SCORE MISSING:",
                item["home"], "vs", item["away"],
            )
            continue

        result_text = f"{home_score}-{away_score}"
        updates.append({
            "range": f'P{item["row"]}',
            "values": [[result_text]],
        })
        print(
            "SOFASCORE RESULT WRITE:",
            item["home"], "vs", item["away"],
            "|", result_text,
        )

    if updates:
        sheet.batch_update(
            updates,
            value_input_option="USER_ENTERED",
        )
        print("SOFASCORE RESULTS UPDATED:", len(updates), "matches")
    else:
        print("SOFASCORE RESULTS: nothing to write")

    # Keep one-off repair pending when the direct schedule route failed.
    # The next 10-minute run will retry; do not launch long failing Actor runs.
    if direct_schedule_failed and not fixture_pool:
        raise RuntimeError("Direct SofaScore result schedule call failed")

def update_votes(
    sheet, rows, book, apify_token, apinn_key, now,
    only_blank=False, allow_fixture_lookup=True,
    minutes_window=None, mark_final=False,
):
    snapshot_label = f"{now.hour:02d}:00"
    print("SOFASCORE SNAPSHOT:", snapshot_label)

    sheet_by_event = {}
    for row_number, row in enumerate(rows, start=1):
        if row_number < 3 or len(row) < 18:
            continue
        event_id = str(row[17]).strip()
        if not event_id:
            continue
        sofa_value = row[13] if len(row) > 13 else ""
        if only_blank and str(sofa_value).strip():
            continue
        sheet_by_event[event_id] = {
            "row": row_number,
            "apinn_event_id": event_id,
            "home": row[1] if len(row) > 1 else "",
            "away": row[2] if len(row) > 2 else "",
            "favorite_side": row[3] if len(row) > 3 else "",
            "league": row[0] if len(row) > 0 else "",
            "sofa_value": sofa_value,
        }

    if not sheet_by_event:
        print("SOFASCORE: no sheet events")
        return True

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
        minutes_to_kickoff = (kickoff - now).total_seconds() / 60
        if minutes_window is not None:
            low, high = minutes_window
            if not (low <= minutes_to_kickoff <= high):
                continue
        tournament_id = sofa_tournament_id(
            match.get("league_id"), match.get("league_name")
        )
        national_match = is_national_sheet_league(sheet_item.get("league"))
        if not tournament_id and not national_match:
            print(
                "SOFASCORE TOURNAMENT NOT MAPPED:",
                match.get("league_name"), match.get("league_id"),
            )
            continue
        candidates.append({
            **sheet_item,
            "kickoff": kickoff,
            "tournament_id": tournament_id,
            "national_match": national_match,
            "sofa_date": kickoff.astimezone(UTC_TZ).date().isoformat(),
        })

    if not candidates:
        print("SOFASCORE: no upcoming matches for this snapshot")
        return True

    cache_sheet, sofa_cache, final_done, cache_rows = load_sofa_cache(book)

    if mark_final:
        candidates = [
            item for item in candidates
            if item["apinn_event_id"] not in final_done
        ]
        if not candidates:
            print("SOFASCORE FINAL 90: no matches due")
            return True

    matched = []
    needs_lookup = []
    for item in candidates:
        cached_id = sofa_cache.get(item["apinn_event_id"])
        if cached_id:
            matched.append({**item, "sofa_event_id": cached_id})
            print(
                "SOFASCORE CACHE HIT:", item["home"], "vs", item["away"],
                "| sofa event:", cached_id,
            )
        else:
            needs_lookup.append(item)

    newly_cached = []
    if needs_lookup and allow_fixture_lookup:
        fixture_pool = []
        dates = sorted({item["sofa_date"] for item in needs_lookup})
        for date_str in dates:
            try:
                fixtures = fetch_sofa_schedule(date_str)
            except Exception as exc:
                fixtures = []
                print(
                    "SOFASCORE DIRECT FIXTURES ERROR:",
                    date_str, repr(exc),
                )
            fixture_pool.extend(fixtures)
            print(
                "SOFASCORE DIRECT FIXTURES:",
                date_str,
                "| events:", len(fixtures),
            )

        for item in needs_lookup:
            fixture = find_sofa_match(
                item["home"], item["away"], item["kickoff"], fixture_pool
            )
            if not fixture:
                print(
                    "SOFASCORE MATCH NOT FOUND:",
                    item["home"], "vs", item["away"],
                )
                continue
            sofa_event_id = fixture.get("id") or fixture.get("eventId")
            if not sofa_event_id:
                continue
            cached_item = {**item, "sofa_event_id": int(sofa_event_id)}
            matched.append(cached_item)
            newly_cached.append(cached_item)
            sofa_cache[item["apinn_event_id"]] = int(sofa_event_id)
            print(
                "SOFASCORE MATCH:",
                item["home"], "vs", item["away"],
                "| sofa event:", sofa_event_id,
            )

        append_sofa_cache(cache_sheet, newly_cached)
        if newly_cached:
            print("SOFASCORE CACHE SAVED:", len(newly_cached), "matches")
            cache_sheet, sofa_cache, final_done, cache_rows = load_sofa_cache(book)
    elif needs_lookup:
        print(
            "SOFASCORE CACHE MISS:",
            len(needs_lookup),
            "matches skipped until a full fixture lookup",
        )

    if not matched:
        print("SOFASCORE: no matched events")
        return True

    vote_rows = fetch_votes(
        apify_token, [item["sofa_event_id"] for item in matched]
    )
    votes_by_event = {
        str(item.get("eventId")): item
        for item in vote_rows if item.get("eventId") is not None
    }

    updates = []
    final_completed = []
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
        if mark_final:
            final_completed.append(item["apinn_event_id"])
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
        if mark_final and final_completed:
            mark_final_done(
                cache_sheet, cache_rows, final_completed, now
            )
            print(
                "SOFASCORE FINAL 90 SAVED:",
                len(final_completed),
                "matches",
            )
    else:
        print("SOFASCORE: nothing to write")

    return True


def main():
    apify_token = os.environ.get("APIFY_TOKEN", "").strip()
    if not apify_token:
        print("SOFASCORE: APIFY_TOKEN missing - skipped")
        return

    now = datetime.now(GREECE_TZ)

    # Retry result collection across a wider window. A single transient
    # provider failure can no longer make us wait until the next day.
    result_window = (
        (now.hour == 7 and now.minute < 50)
        or (now.hour == 22 and now.minute >= 30)
        or (now.hour == 23 and now.minute < 20)
    )

    creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=SCOPES)
    gc = gspread.authorize(creds)
    book = gc.open_by_key(SHEET_KEY)
    sheet = book.worksheet(SHEET_NAME)
    rows = sheet.get_all_values()

    if run_one_off_result_catchup(
        book, sheet, rows, apify_token, now
    ):
        return

    if result_window:
        update_results(book, sheet, rows, apify_token, now)
        return

    apinn_key = os.environ.get("APINN_API_KEY", "").strip()
    if not apinn_key:
        print("SOFASCORE: APINN_API_KEY missing - vote snapshot skipped")
        return

    control = book.worksheet("ALERT STATS")

    # One full daily SofaScore vote snapshot for ALL today's upcoming matches.
    # Target time: 12:30 Greece time.
    initial_slot = f"{now.date().isoformat()}-1230"
    last_initial_slot = str(control.acell("L2").value or "").strip()

    after_initial_time = (now.hour, now.minute) >= (12, 30)
    if after_initial_time and last_initial_slot != initial_slot:
        print(
            "SOFASCORE DAILY FULL SNAPSHOT:",
            initial_slot,
            "| last:", last_initial_slot or "none",
        )
        ok = update_votes(
            sheet, rows, book, apify_token, apinn_key, now,
            only_blank=False,
            allow_fixture_lookup=True,
        )
        if ok:
            control.update(
                "L1:L2",
                [["SOFA DAILY 12:30"], [initial_slot]],
            )
            print("SOFASCORE DAILY SLOT SAVED:", initial_slot)
            rows = sheet.get_all_values()

    # Final SofaScore refresh around 90 minutes before EACH match.
    # The runner executes every 10 minutes, so 80-100' guarantees one
    # refresh close to the requested 90' point. Each match is marked DONE
    # after a successful final refresh and will not be charged again.
    update_votes(
        sheet, rows, book, apify_token, apinn_key, now,
        only_blank=False,
        allow_fixture_lookup=True,
        minutes_window=(80, 100),
        mark_final=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("SOFASCORE ERROR:", repr(exc))
