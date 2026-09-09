import re
import requests
from html import unescape

URL = "https://arbworld.net/for-webmasters/moneyway/football-1-x-2.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

r = requests.get(URL, headers=HEADERS, timeout=30)

print("ARBWORLD STATUS:", r.status_code)
print("ARBWORLD BYTES:", len(r.text))

html = unescape(r.text)

plain = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
plain = re.sub(r"<style[\s\S]*?</style>", " ", plain, flags=re.I)
plain = re.sub(r"<[^>]+>", " ", plain)
plain = re.sub(r"\s+", " ", plain).strip()

targets = [
    ("Sporting", "Galatasaray"),
    ("Napoli", "Arsenal"),
    ("Liverpool", "Atletico"),
]

for home, away in targets:
    low = plain.lower()
    i = low.find(home.lower())
    j = low.find(away.lower(), i + 1) if i >= 0 else -1

    if i >= 0 and j >= 0:
        start = max(0, i - 150)
        end = min(len(plain), j + 450)
        print(f"\nARBWORLD MATCH {home} - {away}:")
        print(plain[start:end])
    else:
        print(f"\nARBWORL
