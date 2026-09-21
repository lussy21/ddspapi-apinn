import os
import bisect
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
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


def turnover_percentile(sheet_rows, row_number, league_name, turnover):
    """Rank current turnover only against the same league, replacing this row's old K."""
    values = []
    for idx, row in enumerate(sheet_rows, start=1):
        if idx == row_number:
            continue
        if not row or str(row[0]).strip() != str(league_name).strip():
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

def turnover_90_percentile(sheet_rows, row_number, league_name, turnover):
    """Rank the 90-minute turnover against 90-minute snapshots from the same league."""
    values = []
    for idx, row in enumerate(sheet_rows, start=1):
        if idx == row_number:
            continue
        if not row or str(row[0]).strip() != str(league_name).strip():
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

NOW = datetime.now(GREECE_TZ)
TODAY = NOW.date()
DAY_START = NOW.replace(hour=11, minute=0, second=0, microsecond=0)

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
        if match.get("league_name") not in TARGET_LEAGUE_NAMES:
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

    if kickoff.date() != TODAY:
        continue

    home = match.get("runner_home")
    away = match.get("runner_away")
    event_id = match.get("event_id")
    league_name = match.get("league_name") or ""

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
            league_name,
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

    # NEW DATA-DRIVEN ALERTS.
    # Existing strong alerts keep priority. These formulas are refreshed
    # for each active match and only become eligible near the close.
    excluded_new_alert_leagues = (
        "^(Finland|Norway|Sweden|Denmark|Scotland|USA|Brazil|Argentina) - "
    )

    new_fav_turnover_formula = (
        f'=IF(AND($P{row_number}="";$BQ{row_number}="CLOSE";'
        f'NOT(REGEXMATCH($A{row_number};"{excluded_new_alert_leagues}"));'
        f'ISNUMBER($E{row_number});$E{row_number}>=1,2;$E{row_number}<=1,5;'
        f'ISNUMBER($BM{row_number});$BM{row_number}>=65);'
        '"🔔💎 ΦΑΒΟΡΙ ΤΖΙΡΟΥ";"")'
    )

    new_fav_sofa_turnover_formula = (
        f'=IF(AND($P{row_number}="";$BQ{row_number}="CLOSE";'
        f'NOT(REGEXMATCH($A{row_number};"{excluded_new_alert_leagues}"));'
        f'ISNUMBER($E{row_number});$E{row_number}>=1,2;$E{row_number}<=1,7;'
        f'ISNUMBER($N{row_number});$N{row_number}>=82;'
        f'ISNUMBER($BM{row_number});$BM{row_number}>=65);'
        '"🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ";"")'
    )

    new_contra_reversal_formula = (
        f'=IF(AND($P{row_number}="";$BQ{row_number}="CLOSE";'
        f'NOT(REGEXMATCH($A{row_number};"{excluded_new_alert_leagues}"));'
        f'ISNUMBER($E{row_number});$E{row_number}>=1,6;$E{row_number}<=2,1;'
        f'ISNUMBER($F{row_number});ISNUMBER($G{row_number});'
        f'$F{row_number}<=$E{row_number};$G{row_number}>=$F{row_number};'
        f'ISNUMBER($K{row_number});ISNUMBER($W{row_number});'
        f'$W{row_number}>0;$K{row_number}/$W{row_number}>=1,5);'
        '"🔔💎 ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ";"")'
    )

    alert_formula = (
        f'=IF($BG{row_number}<>"";$BG{row_number};'
        f'IF($BH{row_number}<>"";$BH{row_number};'
        f'IF($BO{row_number}<>"";$BO{row_number};'
        f'IF($BN{row_number}<>"";$BN{row_number};'
        f'IF($BP{row_number}<>"";$BP{row_number};'
        f'IF($BI{row_number}<>"";$BI{row_number};'
        f'IF($BJ{row_number}<>"";$BJ{row_number};$BK{row_number})))))))'
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
        "range": f"O{row_number}",
        "values": [[alert_formula]],
    })

    # With the 10-minute cron, the last turnover snapshot normally lands
    # inside this window. Mark it as close-ready so the new rules do not
    # flash hours before kickoff.
    if 0 < minutes_to_kickoff <= 15:
        updates.append({
            "range": f"BQ{row_number}",
            "values": [["CLOSE"]],
        })

    # OPEN: γράφεται μία φορά. Στόχος είναι γύρω στις 11:00.
    # Αν τα 11:00 runs χαθούν, κρατάμε την πρώτη επιτυχημένη τιμή μετά τις 11:00
    # αντί να αφήσουμε το OPEN κενό.
    if NOW >= DAY_START and minutes_to_kickoff > 0 and not open_already:
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

    # CLOSE: από τις 11:00 και μετά ανανεώνεται σε κάθε run μέχρι τη σέντρα.
    if NOW >= DAY_START and minutes_to_kickoff > 0:
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
                    NOW >= DAY_START
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
                        sheet_rows, row_number, league_name, turnover
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
                        sheet_rows, row_number, league_name, turnover
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
