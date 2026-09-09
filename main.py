import os
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from zoneinfo import ZoneInfo

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
    response = requests.get(
        BOARD_URL,
        headers=HEADERS,
        params={
            "sport_id": 29,
            "league_id": league_id,
            "live": 0,
            "with_odds": 1,
            "limit": 100,
        },
        timeout=30,
    )
    response.raise_for_status()

    for match in response.json():
        event_id = match.get("event_id")
        if event_id and event_id not in seen_events:
            seen_events.add(event_id)
            matches.append(match)

response = requests.get(
    BOARD_URL,
    headers=HEADERS,
    params={
        "sport_id": 29,
        "live": 0,
        "with_odds": 1,
        "limit": 500,
    },
    timeout=30,
)
response.raise_for_status()

for match in response.json():
    if match.get("league_name") not in TARGET_LEAGUE_NAMES:
        continue

    event_id = match.get("event_id")
    if event_id and event_id not in seen_events:
        seen_events.add(event_id)
        matches.append(match)

print("APINN CONNECTION OK")
print("MATCHES FOUND:", len(matches))

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

    odds_response = requests.get(
        ODDS_URL,
        headers=HEADERS,
        params={"event_id": event_id},
        timeout=30,
    )
    odds_response.raise_for_status()
    event_odds = odds_response.json()

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
            "range": f"A{row_number}:R{row_number}",
            "values": [new_row],
        })

        while len(sheet_rows) < row_number:
            sheet_rows.append([])
        sheet_rows[row_number - 1] = new_row

        print("SHEET ROW CREATED:", row_number, home, "vs", away)

    current_row = sheet_rows[row_number - 1] if row_number <= len(sheet_rows) else []
    open_already = len(current_row) >= 5 and current_row[4] != ""
    min90_already = len(current_row) >= 6 and current_row[5] != ""

    minutes_to_kickoff = (kickoff - NOW).total_seconds() / 60

    # OPEN: γράφεται μία φορά γύρω στις 11:00.
    if NOW.hour == 11 and NOW.minute < 20 and not open_already:
        updates.append({"range": f"E{row_number}", "values": [[fav_odd]]})
        updates.append({
            "range": f"H{row_number}",
            "values": [["" if contra is None else contra]],
        })

    # 90MIN: γράφεται μία φορά περίπου 90 λεπτά πριν.
    if 85 <= minutes_to_kickoff <= 95 and not min90_already:
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

if updates:
    SHEET.batch_update(
        updates,
        value_input_option="USER_ENTERED",
    )
    print("SHEET UPDATED:", len(updates), "ranges")
else:
    print("NO SHEET UPDATES NEEDED")
