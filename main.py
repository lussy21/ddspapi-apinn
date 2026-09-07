import os
import requests

API_KEY = os.environ["APINN_API_KEY"]

url = "https://api.apinn.io/api/board"

params = {
    "sport_id": 29,
    "live": 0,
    "with_odds": 1,
    "limit": 10
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
    home = match.get("runner_home")
    away = match.get("runner_away")
    event_id = match.get("event_id")

    moneyline = (match.get("odds") or {}).get("moneyline") or {}
    odd1 = moneyline.get("odds1")
    odd2 = moneyline.get("odds2")
    if not odd1 or not odd2:
        continue

    favorite = "1" if odd1 < odd2 else "2"

    print(
        home, "vs", away,
        "| 1:", odd1,
        "| 2:", odd2,
        "| ΦΑΒΟΡΙ:", favorite,
        "| event:", event_id
    )
