import re
import unicodedata
from difflib import SequenceMatcher

import requests

API_URL = "https://arbworld.net/api/get-runners"

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

DROP_TOKENS = {
    "fc", "cf", "afc", "sc", "fk", "sk", "vfb", "ac",
}

ALIASES = {
    "sporting cp": "sporting lisbon",
    "sporting club de portugal": "sporting lisbon",
    "paris saint germain": "paris st g",
    "paris sg": "paris st g",
    "psg": "paris st g",
    "atletico de madrid": "atletico madrid",
    "club atletico de madrid": "atletico madrid",
}


def _ascii_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_team(value):
    text = _ascii_text(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if text in ALIASES:
        text = ALIASES[text]

    tokens = [t for t in text.split() if t not in DROP_TOKENS]
    text = " ".join(tokens)

    if text in ALIASES:
        text = ALIASES[text]

    return text


def _team_score(a, b):
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


def fetch_today(timeout=30):
    response = requests.get(
        API_URL,
        params=PARAMS,
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()

    payload = response.json()
    if not payload.get("success", True):
        raise RuntimeError("Arbworld API returned success=false")

    data = payload.get("data") or []
    if not isinstance(data, list):
        raise RuntimeError("Unexpected Arbworld data format")

    return data


def find_match(home, away, rows):
    best = None
    best_score = 0.0

    for item in rows:
        arb_home = item.get("home") or ""
        arb_away = item.get("away") or ""

        home_score = _team_score(home, arb_home)
        away_score = _team_score(away, arb_away)
        combined = (home_score + away_score) / 2

        if home_score < 0.68 or away_score < 0.68:
            continue

        if combined > best_score:
            best_score = combined
            best = item

    if best is None or best_score < 0.76:
        return None

    return best


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def metrics(item, favorite_side):
    volume_1 = _num(item.get("volume_1"))
    volume_x = _num(item.get("volume_x"))
    volume_2 = _num(item.get("volume_2"))

    total = volume_1 + volume_x + volume_2
    if total <= 0:
        return None

    favorite_volume = volume_1 if favorite_side == "H" else volume_2
    favorite_pct = (favorite_volume / total) * 100
    contra_pct = 100 - favorite_pct

    return {
        "turnover": round(total, 2),
        "favorite_pct": round(favorite_pct, 1),
        "contra_pct": round(contra_pct, 1),
        "volume_1": round(volume_1, 2),
        "volume_x": round(volume_x, 2),
        "volume_2": round(volume_2, 2),
        "arb_home": item.get("home") or "",
        "arb_away": item.get("away") or "",
    }
