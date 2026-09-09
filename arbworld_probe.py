import json
import requests

URL = "https://arbworld.net/api/get-runners"
PARAMS = {
    "type": "mw",
    "sport": "soccer",
    "market": "MATCH_ODDS",
    "order": "percentage_desc",
    "day": "today",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://arbworld.net/for-webmasters/moneyway/football-1-x-2.php",
}

TARGETS = [
    ("Sporting", "Galatasaray"),
    ("Napoli", "Arsenal"),
    ("Liverpool", "Atletico"),
    ("Barcelona", "Feyenoord"),
]

r = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=30)
print("API STATUS:", r.status_code)
print("CONTENT-TYPE:", r.headers.get("content-type"))
print("BYTES:", len(r.content))
r.raise_for_status()

data = r.json()
print("TOP TYPE:", type(data).__name__)
if isinstance(data, dict):
    print("TOP KEYS:", sorted(data.keys()))

text = json.dumps(data, ensure_ascii=False)

for home, away in TARGETS:
    i = text.lower().find(home.lower())
    j = text.lower().find(away.lower(), i + 1) if i >= 0 else -1
    if i >= 0 and j >= 0:
        start = max(0, i - 500)
        end = min(len(text), j + 1400)
        print(f"\nTARGET {home} - {away}: FOUND")
        print(text[start:end])
    else:
        print(f"\nTARGET {home} - {away}: NOT FOUND")
