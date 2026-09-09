import os
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
GREECE_TZ = ZoneInfo("Europe/Athens")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS = Credentials.from_service_account_file(
    "/etc/secrets/google-credentials.json",
    scopes=SCOPES
)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key("1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM").worksheet("PINNACLE")
TODAY = datetime.now(GREECE_TZ).date()
NOW = datetime.now(GREECE_TZ)
API_KEY = os.environ["APINN_API_KEY"]

BOARD_URL = "https://api.apinn.io/api/board"
ODDS_URL = "https://api.apinn.io/api/odds"

headers = {
    "X-API-Key": API_KEY
}

# Πρωταθλήματα με επιβεβαιωμένο league_id
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

# Αυτά τα κρατάμε προσωρινά με όνομα
# μέχρι να πιάσουμε και τα δικά τους league_id
TARGET_LEAGUE_NAMES = {
    "Finland - Veikkausliiga",
    "Scotland - Premiership",
    "UEFA - Europa League",
    "UEFA - Conference League",
}

matches = []
seen_events = set()

# Παίρνουμε ξεχωριστά κάθε επιβεβαιωμένο πρωτάθλημα
for league_id in TARGET_LEAGUE_IDS:
    response = requests.get(
        BOARD_URL,
        headers=headers,
        params={
            "sport_id": 29,
            "league_id": league_id,
            "live": 0,
            "with_odds": 1,
            "limit": 100
        },
        timeout=30
    )

    response.raise_for_status()

    for match in response.json():
        event_id = match.get("event_id")

        if event_id and event_id not in seen_events:
            seen_events.add(event_id)
            matches.append(match)

# Προσωρινό fallback για τις λίγκες που δεν έχουμε ακόμα ID
response = requests.get(
    BOARD_URL,
    headers=headers,
    params={
        "sport_id": 29,
        "live": 0,
        "with_odds": 1,
        "limit": 500
    },
    timeout=30
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

for match in matches:
    starts = match.get("starts")
    if not starts or datetime.fromisoformat(starts.replace("Z", "+00:00")).astimezone(GREECE_TZ).date() != TODAY:
        continue
    home = match.get("runner_home")
    away = match.get("runner_away")
    event_id = match.get("event_id")

    moneyline = (match.get("odds") or {}).get("moneyline") or {}

    odd1 = moneyline.get("odds1")
    odd2 = moneyline.get("odds2")

    if not odd1 or not odd2:
        continue

    favorite = "1" if odd1 < odd2 else "2"

    odds_response = requests.get(
        ODDS_URL,
        headers=headers,
        params={"event_id": event_id},
        timeout=30
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

            # ΦΑΒΟΡΙ 1 -> ΚΟΝΤΡΑ = 2 +0.5
            if favorite == "1" and asian.get("line") == -0.5:
                contra = asian.get("odds2")
                break

            # ΦΑΒΟΡΙ 2 -> ΚΟΝΤΡΑ = 1 +0.5
            if favorite == "2" and asian.get("line") == 0.5:
                contra = asian.get("odds1")
                break

    print(
      datetime.fromisoformat(starts.replace("Z", "+00:00")).astimezone(GREECE_TZ).strftime("%d/%m %H:%M"), "|",  home, "vs", away,
        "| 1:", odd1,
        "| 2:", odd2,
        "| ΦΑΒΟΡΙ:", favorite,
        "| ΚΟΝΤΡΑ +0.5:", contra,
        "| event:", event_id
    )
    fav_odd = odd1 if favorite == "1" else odd2
    kickoff = datetime.fromisoformat(
        starts.replace("Z", "+00:00")
    ).astimezone(GREECE_TZ)

    minutes_to_kickoff = (kickoff - NOW).total_seconds() / 60

    fav_side = "H" if favorite == "1" else "A"
    event_id_text = str(event_id)
    league_name = match.get("league_name") or ""

    # Βρίσκουμε αν το ματς υπάρχει ήδη στο Sheet
    event_ids = SHEET.col_values(18)

    try:
        row_number = event_ids.index(event_id_text) + 1
    except ValueError:
        print("NEW MATCH -> WRITING TO SHEET:", home, "vs", away)
        SHEET.append_row(
            [league_name, home, away, fav_side] +
            [""] * 13 +
            [event_id_text]
        )
        row_number = len(SHEET.get_all_values())

    
    # OPEN -> μία φορά γύρω στις 11:00
    if NOW.hour == 11 and NOW.minute < 10:
        if not SHEET.cell(row_number, 5).value:
            SHEET.update_cell(row_number, 5, fav_odd)
            SHEET.update_cell(row_number, 8, contra)

    # 90MIN -> μία φορά περίπου 90 λεπτά πριν
    if 85 <= minutes_to_kickoff <= 95:
        if not SHEET.cell(row_number, 6).value:
            SHEET.update_cell(row_number, 6, fav_odd)
            SHEET.update_cell(row_number, 9, contra)

    # CLOSE -> μία φορά περίπου 5 λεπτά πριν
    if 0 < minutes_to_kickoff <= 7:
        if not SHEET.cell(row_number, 7).value:
            SHEET.update_cell(row_number, 7, fav_odd)
            SHEET.update_cell(row_number, 10, contra)
