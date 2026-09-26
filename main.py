import os
import sys
import bisect
import math
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from arbworld import fetch_today as fetch_arbworld_today
from arbworld import find_match as find_arbworld_match
from arbworld import metrics as arbworld_metrics

GREECE_TZ = ZoneInfo("Europe/Athens")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CREDS = Credentials.from_service_account_file(
    "/etc/secrets/google-credentials.json",
    scopes=SCOPES,
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key(
    "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM"
).worksheet("PINNACLE")

API_KEY = os.environ["APINN_API_KEY"]
BOARD_URL = "https://api.apinn.io/api/board"
ODDS_URL = "https://api.apinn.io/api/odds"
HEADERS = {"X-API-Key": API_KEY}

def apinn_get(url, params, attempts=3):
    """APINN request with retry. Returns None after repeated temporary failures."""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            print(
                f"APINN REQUEST ERROR attempt {attempt}/{attempts}:",
                repr(exc),
                "| params:",
                params,
            )
            if attempt < attempts:
                time.sleep(3 * attempt)
    return None

def _as_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def percentile_rank_inc(values, x):
    """Inclusive percentile rank, 0-100, with linear interpolation."""
    nums = sorted(v for v in (_as_float(v) for v in values) if v is not None)
    x = _as_float(x)
    if x is None or not nums:
        return None
    if len(nums) == 1:
        return 100.0
    if x <= nums[0]:
        return 0.0
    if x >= nums[-1]:
        return 100.0

    left = bisect.bisect_left(nums, x)
    right = bisect.bisect_right(nums, x)

    if right > left:
        index = (left + right - 1) / 2
        return round((index / (len(nums) - 1)) * 100, 1)

    lo = left - 1
    hi = left
    span = nums[hi] - nums[lo]
    fraction = 0.0 if span == 0 else (x - nums[lo]) / span
    rank = (lo + fraction) / (len(nums) - 1)
    return round(rank * 100, 1)


def turnover_percentile(
                        sheet_rows, row_number, sheet_league_name, turnover
                    ):
    """Rank current turnover only against the same league, replacing this row's old K."""
    values = []
    for idx, row in enumerate(sheet_rows, start=1):
        if idx == row_number:
            continue
        if not row or str(row[0]).strip() != str(sheet_league_name).strip():
            continue
        if len(row) > 10:
            value = _as_float(row[10])
            if value is not None:
                values.append(value)

    current = _as_float(turnover)
    if current is None:
        return None
    values.append(current)
    return percentile_rank_inc(values, current)

def turnover_90_percentile(
                        sheet_rows, row_number, sheet_league_name, turnover
                    ):
    """Rank the 90-minute turnover against 90-minute snapshots from the same league."""
    values = []
    for idx, row in enumerate(sheet_rows, start=1):
        if idx == row_number:
            continue
        if not row or str(row[0]).strip() != str(sheet_league_name).strip():
            continue
        if len(row) > 22:
            value = _as_float(row[22])
            if value is not None:
                values.append(value)

    current = _as_float(turnover)
    if current is None:
        return None
    values.append(current)
    return percentile_rank_inc(values, current)


SELECTOR_COL = "BX"
SELECTOR_FAV_TOKENS = {
    "STRONG_FAV", "FAV", "WATCH_FAV", "FAV_TURN",
    "FAV_SOFA_TURN", "FAV60", "FAV75", "TURN_UP",
}
SELECTOR_CONTRA_TOKENS = {
    "STRONG_CONTRA", "STRONG_CONTRA10", "CONTRA",
    "WATCH_CONTRA", "CONTRA_REVERSAL",
}

def _selector_num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _selector_result(value):
    """Parse score text, including old score cells auto-converted to date serials."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("–", "-").replace("—", "-")
    parts = [part.strip() for part in normalized.split("-")]
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        return int(parts[0]), int(parts[1])

    slash = [part.strip() for part in text.split("/")]
    if len(slash) >= 2 and slash[0].isdigit() and slash[1].isdigit():
        home_goals = int(slash[0])
        away_goals = int(slash[1])
        if 0 <= home_goals <= 20 and 0 <= away_goals <= 20:
            return home_goals, away_goals

    serial = _selector_num(text)
    if serial is not None and 30000 <= serial <= 60000:
        try:
            date_value = datetime(1899, 12, 30) + timedelta(days=int(serial))
            if 0 <= date_value.day <= 20 and 1 <= date_value.month <= 12:
                return date_value.day, date_value.month
        except (OverflowError, ValueError):
            pass
    return None


def _selector_favorite_won(row):
    if len(row) <= 15:
        return None
    score = _selector_result(row[15])
    if score is None:
        return None
    side = str(row[3]).strip().upper() if len(row) > 3 else ""
    home_goals, away_goals = score
    if side == "H":
        return home_goals > away_goals
    if side == "A":
        return away_goals > home_goals
    return None


def _selector_tokens_from_text(text):
    tokens = []
    for raw in str(text or "").split("|"):
        part = raw.strip().upper()
        if not part:
            continue
        token = None
        if "ΔΥΝΑΤΟ ΚΟΝΤΡΑ (+10)" in part:
            token = "STRONG_CONTRA10"
        elif "ΔΥΝΑΤΟ ΚΟΝΤΡΑ" in part:
            token = "STRONG_CONTRA"
        elif "ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ" in part:
            token = "CONTRA_REVERSAL"
        elif "WATCH ΚΟΝΤΡΑ" in part:
            token = "WATCH_CONTRA"
        elif "ΚΟΝΤΡΑ" in part:
            token = "CONTRA"
        elif "ΔΥΝΑΤΟ ΦΑΒΟΡΙ" in part:
            token = "STRONG_FAV"
        elif "ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ" in part:
            token = "FAV_SOFA_TURN"
        elif "ΦΑΒΟΡΙ ΤΖΙΡΟΥ" in part:
            token = "FAV_TURN"
        elif "ΦΑΒ 75+" in part:
            token = "FAV75"
        elif "ΦΑΒ 60+" in part:
            token = "FAV60"
        elif "ΤΖΙΡΟΣ ↑" in part:
            token = "TURN_UP"
        elif "WATCH ΦΑΒΟΡΙ" in part:
            token = "WATCH_FAV"
        elif "ΦΑΒΟΡΙ" in part:
            token = "FAV"
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _selector_visible_alert_text(row):
    primary = str(row[14]).strip() if len(row) > 14 else ""
    details = str(row[73]).strip() if len(row) > 73 else ""
    return details or primary


def _selector_reconstructed_tokens(row):
    """Rebuild the alert profile from pre-match fields for historical learning."""
    e = _selector_num(row[4]) if len(row) > 4 else None
    f90 = _selector_num(row[5]) if len(row) > 5 else None
    g = _selector_num(row[6]) if len(row) > 6 else None
    h = _selector_num(row[7]) if len(row) > 7 else None
    j = _selector_num(row[9]) if len(row) > 9 else None
    k = _selector_num(row[10]) if len(row) > 10 else None
    l = _selector_num(row[11]) if len(row) > 11 else None
    n = _selector_num(row[13]) if len(row) > 13 else None
    w = _selector_num(row[22]) if len(row) > 22 else None
    bl = _selector_num(row[63]) if len(row) > 63 else None
    bm = _selector_num(row[64]) if len(row) > 64 else None
    tokens = []

    if e is not None and l is not None and n is not None:
        if 1.5 <= e <= 2.4 and l < 60 and n >= 50:
            tokens.append("STRONG_CONTRA")
        elif 1.7 <= e <= 2.4 and l <= 70 and n >= 50 and (n - l) >= 10:
            tokens.append("STRONG_CONTRA10")
        elif 1.25 <= e <= 1.9 and l >= 90 and n >= 82:
            tokens.append("STRONG_FAV")
        elif 1.5 <= e <= 2.4 and l <= 70 and n >= 50 and n >= l:
            tokens.append("CONTRA")
        elif 1.25 <= e <= 1.9 and l >= 80 and n >= 82:
            tokens.append("FAV")
        elif 1.5 <= e <= 2.4 and l < 75 and n >= 65 and n > l:
            tokens.append("WATCH_CONTRA")
        elif 1.25 <= e <= 2.1 and l >= 80 and n >= 75:
            tokens.append("WATCH_FAV")

    if e is not None and bm is not None:
        if 1.2 <= e <= 1.5 and bm >= 65:
            tokens.append("FAV_TURN")
        if 1.2 <= e <= 1.7 and n is not None and n >= 82 and bm >= 65:
            tokens.append("FAV_SOFA_TURN")
        if e <= 1.7 and bm >= 75:
            tokens.append("FAV75")
        elif e <= 1.7 and bm >= 60:
            tokens.append("FAV60")

    if (
        e is not None and f90 is not None and g is not None
        and k is not None and w is not None and w > 0
        and 1.6 <= e <= 2.1 and f90 <= e and g >= f90
        and (k / w) >= 1.5
    ):
        tokens.append("CONTRA_REVERSAL")

    if bl is not None and bm is not None and bl <= 75 and bm > 75:
        tokens.append("TURN_UP")

    return list(dict.fromkeys(tokens))


def _selector_signature(row, prefer_visible=False):
    visible = _selector_tokens_from_text(_selector_visible_alert_text(row))
    if prefer_visible and visible:
        return visible
    combined = _selector_reconstructed_tokens(row)
    for token in visible:
        if token not in combined:
            combined.append(token)
    return combined


def _selector_side(tokens, alert_text=""):
    # For a multi-alert row, the first visible signal is the same primary family
    # used by the sheet. This only resolves rare opposite-side combinations.
    visible = _selector_tokens_from_text(alert_text)
    ordered = visible or list(tokens)
    for token in ordered:
        if token in SELECTOR_CONTRA_TOKENS:
            return "CONTRA"
        if token in SELECTOR_FAV_TOKENS:
            return "FAV"
    return None


def _selector_league_bucket(row):
    league = str(row[0]).strip() if row else ""
    if league.startswith("ΕΘΝΙΚΕΣ - "):
        return "NATIONAL"
    if league.startswith(("USA - ", "Brazil - ", "Argentina - ")):
        return "AMERICA"
    if league.startswith(("Finland - ", "Norway - ", "Sweden - ", "Denmark - ", "Scotland - ")):
        return "OTHER_EUROPE"
    return "MAIN"


def _selector_features(row):
    def n(index):
        return _selector_num(row[index]) if len(row) > index else None

    e, f90, g = n(4), n(5), n(6)
    h, i90, j = n(7), n(8), n(9)
    k, fav_pct, sofa = n(10), n(11), n(13)
    w, fav90 = n(22), n(23)
    bl, bm = n(63), n(64)

    features = {
        "open_fav": e,
        "close_fav": g if g is not None else (f90 if f90 is not None else e),
        "open_contra": h,
        "close_contra": j if j is not None else (i90 if i90 is not None else h),
        "fav_pct": fav_pct,
        "sofa": sofa,
        "turn90_pct": bl,
        "turn_pct": bm,
        "fav_home": 1.0 if len(row) > 3 and str(row[3]).strip().upper() == "H" else 0.0,
    }
    if e and g:
        features["fav_move"] = (g - e) / e
    else:
        features["fav_move"] = None
    if h and j:
        features["contra_move"] = (j - h) / h
    else:
        features["contra_move"] = None
    if k and w:
        features["turn_growth"] = k / w
    else:
        features["turn_growth"] = None
    if fav_pct is not None and fav90 is not None:
        features["fav_pct_move"] = fav_pct - fav90
    else:
        features["fav_pct_move"] = None
    if sofa is not None and fav_pct is not None:
        features["sofa_gap"] = sofa - fav_pct
    else:
        features["sofa_gap"] = None
    return features


def _selector_scales(records):
    keys = set()
    for record in records:
        keys.update(record["features"].keys())
    scales = {}
    for key in keys:
        values = [
            record["features"].get(key)
            for record in records
            if record["features"].get(key) is not None
        ]
        if len(values) < 2:
            scales[key] = 1.0
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        scales[key] = max(math.sqrt(variance), 0.01)
    return scales


def _selector_distance(candidate, historical, scales):
    squared = []
    for key, value in candidate["features"].items():
        other = historical["features"].get(key)
        if value is None or other is None:
            continue
        scale = scales.get(key, 1.0)
        squared.append(((value - other) / scale) ** 2)

    if len(squared) < 4:
        return None
    distance = math.sqrt(sum(squared) / len(squared))

    current_tokens = set(candidate["tokens"])
    old_tokens = set(historical["tokens"])
    union = current_tokens | old_tokens
    if union:
        overlap = len(current_tokens & old_tokens) / len(union)
        distance += 0.75 * (1.0 - overlap)

    if candidate["league_bucket"] != historical["league_bucket"]:
        distance += 0.20
    return distance


def _selector_score(candidate, historical_rows):
    side = candidate["side"]
    eligible = []
    for record in historical_rows:
        tokens = set(record["tokens"])
        if side == "FAV" and not (tokens & SELECTOR_FAV_TOKENS):
            continue
        if side == "CONTRA" and not (tokens & SELECTOR_CONTRA_TOKENS):
            continue
        eligible.append(record)

    if len(eligible) < 8:
        eligible = list(historical_rows)
    if not eligible:
        return None, None

    scales = _selector_scales(eligible)
    distances = []
    for record in eligible:
        distance = _selector_distance(candidate, record, scales)
        if distance is not None:
            distances.append((distance, record))
    if not distances:
        return None, None

    distances.sort(key=lambda item: item[0])
    k = min(18, max(8, int(math.sqrt(len(distances)) * 2.5)))
    nearest = distances[:k]

    weighted_total = 0.0
    weight_sum = 0.0
    for distance, record in nearest:
        weight = 1.0 / (0.35 + distance)
        fav_won = record["fav_won"]
        success = fav_won if side == "FAV" else not fav_won
        weighted_total += weight * (1.0 if success else 0.0)
        weight_sum += weight

    if weight_sum <= 0:
        return None, None

    # Small shrink toward the relevant historical base so tiny neighbour sets
    # cannot dominate the ranking. The score is internal; the sheet shows rank only.
    successes = [
        (r["fav_won"] if side == "FAV" else not r["fav_won"])
        for r in eligible
    ]
    base = sum(1.0 for success in successes if success) / len(successes)
    score = (weighted_total + (3.0 * base)) / (weight_sum + 3.0)
    avg_distance = sum(distance for distance, _ in nearest) / len(nearest)
    return score, avg_distance


def _selector_strength_text(score, stage):
    if score is None or score < 0:
        return ""
    value = max(0.0, min(10.0, score * 10.0))
    value_text = f"{value:.1f}".replace(".", ",")
    return f"{value_text}/10 · {stage}"


def _selector_live_stage(row):
    close_ready = len(row) > 68 and str(row[68]).strip().upper() == "CLOSE"
    if close_ready:
        return "FINAL"

    has_90 = any(
        len(row) > index and str(row[index]).strip()
        for index in (5, 8, 22, 23, 24, 63)
    )
    if has_90:
        return "90'"
    return "EARLY"


def _selector_backfill_strengths(all_rows):
    """Walk forward through finished rows and score each one only from earlier rows."""
    prior_history = []
    updates = []

    for row_number, row in enumerate(all_rows[2:], start=3):
        fav_won = _selector_favorite_won(row)
        if fav_won is None:
            continue

        tokens = _selector_signature(row, prefer_visible=False)
        if not tokens:
            continue

        alert_text = _selector_visible_alert_text(row)
        side = _selector_side(tokens, alert_text)
        if side is None:
            continue

        existing = str(row[75]).strip() if len(row) > 75 else ""
        if "/10" not in existing and prior_history:
            candidate = {
                "row": row_number,
                "features": _selector_features(row),
                "tokens": tokens,
                "league_bucket": _selector_league_bucket(row),
                "side": side,
            }
            score, _ = _selector_score(candidate, prior_history)
            strength = _selector_strength_text(score, "FINAL")
            if strength:
                updates.append({
                    "range": f"{SELECTOR_COL}{row_number}",
                    "values": [[strength]],
                })

        prior_history.append({
            "row": row_number,
            "features": _selector_features(row),
            "tokens": tokens,
            "league_bucket": _selector_league_bucket(row),
            "fav_won": fav_won,
        })

    return updates


def update_selector_ranking(sheet, all_rows, matches, now):
    """Show each live alert's own model strength instead of a relative daily rank."""
    historical = []
    for row_number, row in enumerate(all_rows[2:], start=3):
        fav_won = _selector_favorite_won(row)
        if fav_won is None:
            continue
        tokens = _selector_signature(row, prefer_visible=False)
        if not tokens:
            continue
        historical.append({
            "row": row_number,
            "features": _selector_features(row),
            "tokens": tokens,
            "league_bucket": _selector_league_bucket(row),
            "fav_won": fav_won,
        })

    row_by_event = {}
    for row_number, row in enumerate(all_rows, start=1):
        if len(row) > 17 and str(row[17]).strip():
            row_by_event[str(row[17]).strip()] = row_number

    upcoming_rows = []
    for match in matches:
        starts = match.get("starts")
        event_id = match.get("event_id")
        if not starts or event_id is None:
            continue
        try:
            kickoff = datetime.fromisoformat(
                starts.replace("Z", "+00:00")
            ).astimezone(GREECE_TZ)
        except ValueError:
            continue
        if kickoff.date() != now.date() or kickoff <= now:
            continue
        row_number = row_by_event.get(str(event_id))
        if row_number:
            upcoming_rows.append(row_number)

    selector_updates = _selector_backfill_strengths(all_rows)
    live_count = 0

    for row_number in sorted(set(upcoming_rows)):
        row = all_rows[row_number - 1]
        alert_text = _selector_visible_alert_text(row)
        if not alert_text or alert_text.startswith("#"):
            selector_updates.append({
                "range": f"{SELECTOR_COL}{row_number}",
                "values": [[""]],
            })
            continue

        tokens = _selector_signature(row, prefer_visible=True)
        side = _selector_side(tokens, alert_text)
        if side is None:
            selector_updates.append({
                "range": f"{SELECTOR_COL}{row_number}",
                "values": [[""]],
            })
            continue

        candidate = {
            "row": row_number,
            "features": _selector_features(row),
            "tokens": tokens,
            "league_bucket": _selector_league_bucket(row),
            "side": side,
        }
        score, avg_distance = _selector_score(candidate, historical)
        stage = _selector_live_stage(row)
        strength = _selector_strength_text(score, stage)

        selector_updates.append({
            "range": f"{SELECTOR_COL}{row_number}",
            "values": [[strength]],
        })
        live_count += 1
        print(
            "SELECTOR STRENGTH:",
            strength,
            "| row:", row_number,
            "| raw score:", None if score is None else round(score, 4),
            "| avg distance:", None if avg_distance is None else round(avg_distance, 4),
            "| alerts:", ",".join(tokens),
        )

    if selector_updates:
        sheet.batch_update(
            selector_updates,
            value_input_option="USER_ENTERED",
        )
        print(
            "SELECTOR UPDATED:",
            live_count,
            "live strengths |",
            len(selector_updates) - live_count,
            "clears/backfills",
        )
    else:
        print("SELECTOR: NO UPDATES")


TARGET_LEAGUE_IDS = {
    1980,    # England - Premier League
    1842,    # Germany - Bundesliga
    2036,    # France - Ligue 1
    2081,    # Greece - Super League
    2436,    # Italy - Serie A
    2196,    # Spain - La Liga
    1817,    # Belgium - Pro League
    1913,    # Denmark - Superliga
    2333,    # Norway - Eliteserien
    1928,    # Netherlands - Eredivisie
    2592,    # Turkey - Super League
    1834,    # Brazil - Serie A
    210697,  # Argentina - Liga Pro
    1728,    # Sweden - Allsvenskan
    2663,    # USA - Major League Soccer
    2627,    # UEFA - Champions League
}

TARGET_LEAGUE_NAMES = {
    "Finland - Veikkausliiga",
    "Scotland - Premiership",
    "UEFA - Europa League",
    "UEFA - Conference League",
}

NATIONAL_COMPETITION_TERMS = (
    "nations league",
    "world cup",
    "fifa internationals",
    "fifa - internationals",
    "european championship",
    "euro qualifier",
    "euro qualification",
    "euro qualifying",
    "copa america",
    "africa cup of nations",
    "african cup of nations",
    "afcon",
    "asian cup",
    "gold cup",
    "concacaf nations",
)

NATIONAL_COMPETITION_EXCLUSIONS = (
    "club world cup",
    "friendly",
    "friendlies",
    "women",
    "u17",
    "u18",
    "u19",
    "u20",
    "u21",
    "u22",
    "u23",
    "youth",
    "olympic",
)

def is_national_team_competition(league_name):
    name = str(league_name or "").strip().lower()
    if not name:
        return False
    if any(term in name for term in NATIONAL_COMPETITION_EXCLUSIONS):
        return False
    return any(term in name for term in NATIONAL_COMPETITION_TERMS)

def betting_day_start_for(kickoff):
    """Our daily OPEN anchor: 11:00 Greece time before the match's betting day."""
    anchor = kickoff.replace(hour=11, minute=0, second=0, microsecond=0)
    if kickoff < anchor:
        anchor -= timedelta(days=1)
    return anchor


NOW = datetime.now(GREECE_TZ)
TODAY = NOW.date()

matches = []
seen_events = set()

for league_id in TARGET_LEAGUE_IDS:
    response = apinn_get(
        BOARD_URL,
        {
            "sport_id": 29,
            "league_id": league_id,
            "live": 0,
            "with_odds": 1,
            "limit": 100,
        },
    )
    if response is None:
        print("APINN LEAGUE SKIPPED AFTER RETRIES:", league_id)
        continue

    for match in response.json():
        event_id = match.get("event_id")
        if event_id and event_id not in seen_events:
            seen_events.add(event_id)
            matches.append(match)

response = apinn_get(
    BOARD_URL,
    {
        "sport_id": 29,
        "live": 0,
        "with_odds": 1,
        "limit": 500,
    },
)

if response is not None:
    for match in response.json():
        league_name = match.get("league_name") or ""
        if (
            league_name not in TARGET_LEAGUE_NAMES
            and not is_national_team_competition(league_name)
        ):
            continue

        event_id = match.get("event_id")
        if event_id and event_id not in seen_events:
            seen_events.add(event_id)
            matches.append(match)
else:
    print("APINN ALL-LEAGUES REQUEST SKIPPED AFTER RETRIES")

print("APINN CONNECTION OK")
print("MATCHES FOUND:", len(matches))

# Arbworld: one request per run for all today's 1X2 Moneyway data.
try:
    ARBWORLD_ROWS = fetch_arbworld_today()
    print("ARBWORLD CONNECTION OK")
    print("ARBWORLD MATCHES FOUND:", len(ARBWORLD_ROWS))
except Exception as exc:
    ARBWORLD_ROWS = []
    print("ARBWORLD ERROR:", repr(exc))

sheet_rows = SHEET.get_all_values()
event_rows = {}

for row_number, row in enumerate(sheet_rows, start=1):
    if len(row) >= 18 and row[17]:
        event_rows[str(row[17])] = row_number

next_row = max(3, len(sheet_rows) + 1)
updates = []

for match in matches:
    starts = match.get("starts")
    if not starts:
        continue

    kickoff = datetime.fromisoformat(
        starts.replace("Z", "+00:00")
    ).astimezone(GREECE_TZ)

    match_day_start = betting_day_start_for(kickoff)

    # Keep today's upcoming matches visible even before 11:00 so a missed
    # 11:00 run cannot make the whole day disappear. OPEN snapshots still
    # start at match_day_start below. Overnight matches (00:00-10:59) keep
    # belonging to the previous betting day from 11:00.
    if NOW >= kickoff:
        continue
    if kickoff.date() != TODAY and NOW < match_day_start:
        continue

    home = match.get("runner_home")
    away = match.get("runner_away")
    event_id = match.get("event_id")
    league_name = match.get("league_name") or ""
    national_match = is_national_team_competition(league_name)
    sheet_league_name = (
        f"ΕΘΝΙΚΕΣ - {league_name}" if national_match else league_name
    )

    moneyline = (match.get("odds") or {}).get("moneyline") or {}
    odd1 = moneyline.get("odds1")
    odd2 = moneyline.get("odds2")

    if not odd1 or not odd2:
        continue

    favorite = "1" if odd1 < odd2 else "2"
    fav_side = "H" if favorite == "1" else "A"
    fav_odd = odd1 if favorite == "1" else odd2
    event_id_text = str(event_id)

    odds_response = apinn_get(
        ODDS_URL,
        {"event_id": event_id},
    )
    event_odds = odds_response.json() if odds_response is not None else []

    contra = None

    if isinstance(event_odds, list):
        for asian in event_odds:
            if asian.get("market") != "spread":
                continue
            if asian.get("period") != 0:
                continue

            if favorite == "1" and asian.get("line") == -0.5:
                contra = asian.get("odds2")
                break

            if favorite == "2" and asian.get("line") == 0.5:
                contra = asian.get("odds1")
                break

    print(
        kickoff.strftime("%d/%m %H:%M"),
        "|", home, "vs", away,
        "| 1:", odd1,
        "| 2:", odd2,
        "| ΦΑΒΟΡΙ:", favorite,
        "| ΚΟΝΤΡΑ +0.5:", contra,
        "| event:", event_id,
    )

    if event_id_text in event_rows:
        row_number = event_rows[event_id_text]
    else:
        row_number = next_row
        next_row += 1
        event_rows[event_id_text] = row_number

        new_row = [
            sheet_league_name,
            home,
            away,
            fav_side,
            "", "", "",
            "", "", "",
            "", "", "", "",
            "", "", "",
            event_id_text,
        ]

        updates.append({
    "range": f"A{row_number}:N{row_number}",
    "values": [new_row[:14]],
})
        updates.append({
    "range": f"P{row_number}:R{row_number}",
    "values": [new_row[15:18]],
})

        while len(sheet_rows) < row_number:
            sheet_rows.append([])
        sheet_rows[row_number - 1] = new_row

        print("SHEET ROW CREATED:", row_number, home, "vs", away)

    current_row = sheet_rows[row_number - 1] if row_number <= len(sheet_rows) else []
    open_already = len(current_row) >= 5 and current_row[4] != ""
    min90_already = len(current_row) >= 6 and current_row[5] != ""

    minutes_to_kickoff = (kickoff - NOW).total_seconds() / 60

    # Preserve any hand-written note in Q. Automatic multi-alert details are
    # rendered from hidden helpers, while the original manual text lives in BW.
    existing_comment = (
        str(current_row[16]).strip() if len(current_row) > 16 else ""
    )
    stored_manual_comment = (
        str(current_row[74]).strip() if len(current_row) > 74 else ""
    )
    auto_comment_visible = (
        existing_comment.startswith("⚡") or " | ⚡" in existing_comment
    )
    if existing_comment and not stored_manual_comment and not auto_comment_visible:
        updates.append({
            "range": f"BW{row_number}",
            "values": [[existing_comment]],
        })

    # NEW DATA-DRIVEN ALERTS.
    # Existing strong alerts keep priority. These formulas are refreshed
    # for each active match and only become eligible near the close.
    excluded_new_alert_leagues = (
        "^(Finland|Norway|Sweden|Denmark|Scotland|USA|Brazil|Argentina) - "
    )

    new_fav_turnover_formula = (
        f'=IF(AND('
        f'NOT(REGEXMATCH($A{row_number};"{excluded_new_alert_leagues}"));'
        f'ISNUMBER($E{row_number});$E{row_number}>=1,2;$E{row_number}<=1,5;'
        f'ISNUMBER($BM{row_number});$BM{row_number}>=65);'
        '"🔔💎 ΦΑΒΟΡΙ ΤΖΙΡΟΥ";"")'
    )

    new_fav_sofa_turnover_formula = (
        f'=IF(AND('
        f'NOT(REGEXMATCH($A{row_number};"{excluded_new_alert_leagues}"));'
        f'ISNUMBER($E{row_number});$E{row_number}>=1,2;$E{row_number}<=1,7;'
        f'ISNUMBER($N{row_number});$N{row_number}>=82;'
        f'ISNUMBER($BM{row_number});$BM{row_number}>=65);'
        '"🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ";"")'
    )

    new_contra_reversal_formula = (
        f'=IF(AND('
        f'NOT(REGEXMATCH($A{row_number};"{excluded_new_alert_leagues}"));'
        f'ISNUMBER($E{row_number});$E{row_number}>=1,6;$E{row_number}<=2,1;'
        f'ISNUMBER($F{row_number});ISNUMBER($G{row_number});'
        f'$F{row_number}<=$E{row_number};$G{row_number}>=$F{row_number};'
        f'ISNUMBER($K{row_number});ISNUMBER($W{row_number});'
        f'$W{row_number}>0;IFERROR($K{row_number}/$W{row_number}>=1,5;FALSE));'
        '"🔔💎 ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ";"")'
    )

    # Turnover alerts discovered from the historical PINNACLE sample.
    # They are tracked for every league category; stats pages split the results.
    fav_60_formula = (
        f'=IF(AND('
        f'ISNUMBER($E{row_number});$E{row_number}<=1,7;'
        f'ISNUMBER($BM{row_number});$BM{row_number}>=60);'
        '"🔔 ΦΑΒ 60+";"")'
    )

    fav_75_formula = (
        f'=IF(AND('
        f'ISNUMBER($E{row_number});$E{row_number}<=1,7;'
        f'ISNUMBER($BM{row_number});$BM{row_number}>=75);'
        '"🔔 ΦΑΒ 75+";"")'
    )

    turnover_up_formula = (
        f'=IF(AND('
        f'ISNUMBER($BL{row_number});$BL{row_number}<=75;'
        f'ISNUMBER($BM{row_number});$BM{row_number}>75);'
        '"🔔 ΤΖΙΡΟΣ ↑";"")'
    )

    # Existing STRONG / SIMPLE / WATCH rules are hierarchical. Count only
    # the highest active one from that family so a strong alert is not
    # artificially counted again as simple/watch. Independent turnover/model
    # alerts count separately.
    alert_count_formula = (
        f'=IF(IF($BG{row_number}<>"";$BG{row_number};$BH{row_number})<>"";1;0)'
        f'+IF(AND($BQ{row_number}="CLOSE";$BO{row_number}<>"");1;0)'
        f'+IF(AND($BQ{row_number}="CLOSE";$BN{row_number}<>"");1;0)'
        f'+IF(AND($BQ{row_number}="CLOSE";$BP{row_number}<>"");1;0)'
        f'+IF(AND($BQ{row_number}="CLOSE";$BT{row_number}<>"");1;0)'
        f'+IF(AND($BQ{row_number}="CLOSE";$BS{row_number}<>"");1;0)'
        f'+IF(AND($BQ{row_number}="CLOSE";$BR{row_number}<>"");1;0)'
        f'+IF(AND($BG{row_number}="";$BH{row_number}="";'
        f'IF($BI{row_number}<>"";$BI{row_number};$BJ{row_number})<>"");1;0)'
        f'+IF(AND($BG{row_number}="";$BH{row_number}="";'
        f'$BI{row_number}="";$BJ{row_number}="";$BK{row_number}<>"");1;0)'
    )

    alert_list_formula = (
        f'=TEXTJOIN(" | ";TRUE;'
        f'IF($BG{row_number}<>"";$BG{row_number};$BH{row_number});'
        f'IF(AND($BQ{row_number}="CLOSE";$BO{row_number}<>"");$BO{row_number};"");'
        f'IF(AND($BQ{row_number}="CLOSE";$BN{row_number}<>"");$BN{row_number};"");'
        f'IF(AND($BQ{row_number}="CLOSE";$BP{row_number}<>"");$BP{row_number};"");'
        f'IF(AND($BQ{row_number}="CLOSE";$BT{row_number}<>"");$BT{row_number};"");'
        f'IF(AND($BQ{row_number}="CLOSE";$BS{row_number}<>"");$BS{row_number};"");'
        f'IF(AND($BQ{row_number}="CLOSE";$BR{row_number}<>"");$BR{row_number};"");'
        f'IF(AND($BG{row_number}="";$BH{row_number}="");'
        f'IF($BI{row_number}<>"";$BI{row_number};$BJ{row_number});"");'
        f'IF(AND($BG{row_number}="";$BH{row_number}="";'
        f'$BI{row_number}="";$BJ{row_number}="");$BK{row_number};""))'
    )

    primary_alert_expr = (
        f'IF($BG{row_number}<>"";$BG{row_number};'
        f'IF($BH{row_number}<>"";$BH{row_number};'
        f'IF(AND($BQ{row_number}="CLOSE";$BO{row_number}<>"");$BO{row_number};'
        f'IF(AND($BQ{row_number}="CLOSE";$BN{row_number}<>"");$BN{row_number};'
        f'IF(AND($BQ{row_number}="CLOSE";$BP{row_number}<>"");$BP{row_number};'
        f'IF(AND($BQ{row_number}="CLOSE";$BT{row_number}<>"");$BT{row_number};'
        f'IF(AND($BQ{row_number}="CLOSE";$BS{row_number}<>"");$BS{row_number};'
        f'IF(AND($BQ{row_number}="CLOSE";$BR{row_number}<>"");$BR{row_number};'
        f'IF($BI{row_number}<>"";$BI{row_number};'
        f'IF($BJ{row_number}<>"";$BJ{row_number};$BK{row_number}))))))))))'
    )
    # O is the visual "at a glance" column: primary alert + selector strength.
    # The real alert state still lives in the helper columns; BX keeps the full score/stage.
    alert_formula = (
        f'=LET(pa;{primary_alert_expr};'
        f'IF(pa<>"";pa&IF(AND($BX{row_number}<>"";REGEXMATCH(TO_TEXT($BX{row_number});"/10"));'
        f'" · "&IFERROR(LEFT($BX{row_number};FIND(" · ";$BX{row_number})-1);$BX{row_number});"");""))'
    )
    comment_formula = (
        f'=IF($BU{row_number}>=2;'
        f'IF($BW{row_number}<>"";$BW{row_number}&" | ⚡"&$BU{row_number}&": "&$BV{row_number};'
        f'"⚡"&$BU{row_number}&": "&$BV{row_number});'
        f'$BW{row_number})'
    )

    updates.append({
        "range": f"BN{row_number}:BP{row_number}",
        "values": [[
            new_fav_turnover_formula,
            new_fav_sofa_turnover_formula,
            new_contra_reversal_formula,
        ]],
    })
    updates.append({
        "range": f"BR{row_number}:BV{row_number}",
        "values": [[
            fav_60_formula,
            fav_75_formula,
            turnover_up_formula,
            alert_count_formula,
            alert_list_formula,
        ]],
    })
    updates.append({
        "range": f"O{row_number}",
        "values": [[alert_formula]],
    })
    updates.append({
        "range": f"Q{row_number}",
        "values": [[comment_formula]],
    })

    # With the 10-minute cron, the last turnover snapshot normally lands
    # inside this window. Mark it as close-ready so the new rules do not
    # flash hours before kickoff.
    if 0 < minutes_to_kickoff <= 15:
        updates.append({
            "range": f"BQ{row_number}",
            "values": [["CLOSE"]],
        })

    # OPEN ΗΜΕΡΑΣ: γράφεται μία φορά από τις 11:00 ώρα Ελλάδας
    # της στοιχηματικής ημέρας του αγώνα. Για ματς 00:00-10:59,
    # το OPEN ξεκινά στις 11:00 της προηγούμενης ημερολογιακής ημέρας.
    # Αν χαθεί το ακριβές 11:00 run, κρατάμε την πρώτη επιτυχημένη τιμή μετά.
    if NOW >= match_day_start and minutes_to_kickoff > 0 and not open_already:
        updates.append({"range": f"E{row_number}", "values": [[fav_odd]]})
        updates.append({
            "range": f"H{row_number}",
            "values": [["" if contra is None else contra]],
        })

    # 90MIN: γράφεται μία φορά περίπου 90 λεπτά πριν.
    # Αν χαθεί το ακριβές 85-95' παράθυρο, κρατάμε την πρώτη
    # επιτυχημένη τιμή πριν τη σέντρα αντί να μείνει κενό.
    if 0 < minutes_to_kickoff <= 95 and not min90_already:
        updates.append({"range": f"F{row_number}", "values": [[fav_odd]]})
        updates.append({
            "range": f"I{row_number}",
            "values": [["" if contra is None else contra]],
        })

    # CLOSE: ανανεώνεται από το OPEN ΗΜΕΡΑΣ (11:00) μέχρι τη σέντρα,
    # ακόμη κι όταν η σέντρα είναι μετά τα μεσάνυχτα.
    if NOW >= match_day_start and minutes_to_kickoff > 0:
        updates.append({"range": f"G{row_number}", "values": [[fav_odd]]})
        updates.append({
            "range": f"J{row_number}",
            "values": [["" if contra is None else contra]],
        })

    # ---------------- ARBWORLD ----------------
    # K/L/M = τρέχοντα στοιχεία. Ανανεώνονται μέχρι 5' πριν και μετά παγώνουν.
    # T:V = snapshot 11:00.
    # W:Y = snapshot περίπου 90' πριν.
    # K:M = CLOSE, που ανανεώνεται κάθε run και παγώνει στα 5' πριν.
    if minutes_to_kickoff > 0 and ARBWORLD_ROWS:
        arb_match = find_arbworld_match(home, away, ARBWORLD_ROWS)

        if arb_match:
            arb = arbworld_metrics(arb_match, fav_side)

            if arb:
                turnover = arb["turnover"]
                favorite_pct = arb["favorite_pct"]
                contra_pct = arb["contra_pct"]

                morning_already = (
                    len(current_row) >= 22
                    and any(str(v).strip() for v in current_row[19:22])
                )

                snap90_already = (
                    len(current_row) >= 25
                    and any(str(v).strip() for v in current_row[22:25])
                )

                # 11:00 snapshot: γράφεται μία φορά.
                # Αν χαθούν τα 11:00 runs, κρατάμε το πρώτο διαθέσιμο snapshot
                # μετά τις 11:00 ώστε τα αρχικά πονταρίσματα να μη μένουν κενά.
                if (
                    NOW >= match_day_start
                    and minutes_to_kickoff > 0
                    and not morning_already
                ):
                    updates.append({
                        "range": f"T{row_number}:V{row_number}",
                        "values": [[turnover, favorite_pct, contra_pct]],
                    })
                    print(
                        "ARBWORLD 11:00 SNAPSHOT:",
                        home, "vs", away,
                        "| turnover:", turnover,
                        "| fav%:", favorite_pct,
                        "| contra%:", contra_pct,
                    )

                # 90' snapshot: γράφεται μία φορά.
                # Αν χαθεί το ακριβές 85-95' παράθυρο, κρατάμε το πρώτο
                # διαθέσιμο snapshot πριν τη σέντρα.
                if 0 < minutes_to_kickoff <= 95 and not snap90_already:
                    turnover_90_pct = turnover_90_percentile(
                        sheet_rows, row_number, sheet_league_name, turnover
                    )

                    updates.append({
                        "range": f"W{row_number}:Y{row_number}",
                        "values": [[turnover, favorite_pct, contra_pct]],
                    })
                    if turnover_90_pct is not None:
                        updates.append({
                            "range": f"BL{row_number}",
                            "values": [[turnover_90_pct]],
                        })

                    while len(sheet_rows[row_number - 1]) < 64:
                        sheet_rows[row_number - 1].append("")
                    sheet_rows[row_number - 1][22] = turnover
                    if turnover_90_pct is not None:
                        sheet_rows[row_number - 1][63] = turnover_90_pct

                    print(
                        "ARBWORLD 90 SNAPSHOT:",
                        home, "vs", away,
                        "| turnover:", turnover,
                        "| fav%:", favorite_pct,
                        "| contra%:", contra_pct,
                    )
                    print(
                        "TURNOVER 90 PERCENTILE:",
                        home, "vs", away,
                        "| league:", league_name,
                        "| pct:", turnover_90_pct,
                    )

                # CLOSE:
                # Ανανεώνεται σε κάθε run από τις 11:00 μέχρι και 5' πριν.
                # Στα τελευταία <5' δεν αλλάζει ξανά.
                if minutes_to_kickoff >= 5:
                    turnover_pct = turnover_percentile(
                        sheet_rows, row_number, sheet_league_name, turnover
                    )

                    updates.append({
                        "range": f"K{row_number}:M{row_number}",
                        "values": [[turnover, favorite_pct, contra_pct]],
                    })
                    if turnover_pct is not None:
                        updates.append({
                            "range": f"BM{row_number}",
                            "values": [[turnover_pct]],
                        })

                    # Keep the in-memory sheet snapshot current so the next
                    # match in the same league is ranked against fresh values.
                    while len(sheet_rows[row_number - 1]) < 65:
                        sheet_rows[row_number - 1].append("")
                    sheet_rows[row_number - 1][10] = turnover
                    if turnover_pct is not None:
                        sheet_rows[row_number - 1][64] = turnover_pct

                    print(
                        "TURNOVER PERCENTILE:",
                        home, "vs", away,
                        "| league:", league_name,
                        "| pct:", turnover_pct,
                    )

                print(
                    "ARBWORLD MATCH:",
                    home, "vs", away,
                    "=>", arb["arb_home"], "vs", arb["arb_away"],
                    "| 1:", arb["volume_1"],
                    "| X:", arb["volume_x"],
                    "| 2:", arb["volume_2"],
                    "| total:", turnover,
                    "| fav%:", favorite_pct,
                    "| contra%:", contra_pct,
                )
        else:
            print("ARBWORLD MATCH NOT FOUND:", home, "vs", away)

if updates:
    SHEET.batch_update(
        updates,
        value_input_option="USER_ENTERED",
    )
    print("SHEET UPDATED:", len(updates), "ranges")
else:
    print("NO SHEET UPDATES NEEDED")

# Re-read after formula/turnover writes so the daily selector sees the current
# alert state. Only the integer rank is shown in BX; its internal score stays hidden.
time.sleep(1)
try:
    selector_rows = SHEET.get_all_values()
    update_selector_ranking(SHEET, selector_rows, matches, NOW)
except Exception as exc:
    # Ranking must never stop the odds/turnover collector.
    print("SELECTOR ERROR:", repr(exc))

# Render runs the collectors with shell &&. On some heavy 11:00 runs the
# Python interpreter has remained alive after all synchronous work completed,
# which prevents the SofaScore result runner from starting. All sheet writes
# above are already complete, so exit explicitly and let the next command run.
print("MAIN COMPLETE")
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)

