import os
import requests

API_KEY = os.environ["APINN_API_KEY"]

url = "https://api.apinn.io/api/board"

params = {
    "sport_id": 29,
    "live": 0,
    "with_odds": 1,
    "limit": 500
}
TARGET_LEAGUE_IDS = {
    1980,  # England - Premier League
    1842,  # Germany - Bundesliga
    2036,  # France - Ligue 1
    2081,  # Greece - Super League
    2436,  # Italy - Serie A
    2196,  # Spain - La Liga
    1817,  # Belgium - Pro League
    1913,  # Denmark - Superliga
    2333,  # Norway - Eliteserien
    1928,  # Netherlands - Eredivisie
    2592,  # Turkey - Super League
    1834,  # Brazil - Serie A
    210697, # Argentina - Liga Pro
    1728,  # Sweden - Allsvenskan
    2663,  # USA - Major League Soccer
    2627,  # UEFA - Champions League
}

headers = {
    "X-API-Key": API_KEY
}
print("KEY FOUND:", bool(API_KEY))
print("KEY LENGTH:", len(API_KEY))
response = requests.get(
    url,
    headers=headers,
    params=params,
    timeout=30
)

response.raise_for_status()
data = response.json()

print("APINN CONNECTION OK")


for match in data:
        if match.get("league_id") not in TARGET_LEAGUE_IDS:
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
    "https://api.apinn.io/api/odds",
    headers=headers,
    params={"event_id": event_id},
    timeout=30
)

event_odds = odds_response.json()

contra = None

for asian in event_odds:
    if asian.get("market") != "spread" or asian.get("period") != 0:
        continue

    if favorite == "1" and asian.get("line") == -0.5:
        contra = asian.get("odds2")

    elif favorite == "2" and asian.get("line") == 0.5:
        contra = asian.get("odds1")
print(
home, "vs", away,
"| 1:", odd1,
"| 2:", odd2,
"| ΦΑΒΟΡΙ:", favorite,
"| ΚΟΝΤΡΑ +0.5:", contra,
"| event:", event_id
)
