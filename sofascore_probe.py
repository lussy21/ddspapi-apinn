import json
import re
import requests

MATCH_URL = "https://www.sofascore.com/football/match/sabah-fk-manchester-united/KsDghc"
BASE_API = "https://www.sofascore.com/api/v1"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": "https://www.sofascore.com/",
}


def pct(value, total):
    return round((value / total) * 100, 1) if total else 0.0


def find_event_id(text):
    patterns = [
        r'"eventId"\s*:\s*(\d+)',
        r'"id"\s*:\s*(\d+)\s*,\s*"slug"\s*:\s*"manchester-united-sabah-fk"',
        r'"id"\s*:\s*(\d+)\s*,\s*"homeTeam"\s*:',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return int(m.group(1))
    return None


def main():
    s = requests.Session()
    s.headers.update(HEADERS)

    page = s.get(MATCH_URL, timeout=30)
    print("MATCH PAGE STATUS:", page.status_code)
    print("MATCH PAGE BYTES:", len(page.text))

    if page.status_code != 200:
        print("MATCH PAGE BODY:", page.text[:500])
        return

    event_id = find_event_id(page.text)

    if not event_id:
        # Print only small diagnostic hints, not the whole page.
        print("EVENT ID NOT FOUND IN PAGE")
        for key in ("eventId", "startTimestamp", "Manchester United", "Sabah FK"):
            print("HAS", key, ":", key in page.text)
        return

    print("EVENT ID:", event_id)

    votes_url = f"{BASE_API}/event/{event_id}/votes"
    vr = s.get(
        votes_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": MATCH_URL,
        },
        timeout=20,
    )

    print("VOTES STATUS:", vr.status_code)

    if vr.status_code != 200:
        print("VOTES BODY:", vr.text[:500])
        return

    data = vr.json()
    votes = data.get("vote") or {}

    v1 = int(votes.get("vote1") or 0)
    vx = int(votes.get("voteX") or 0)
    v2 = int(votes.get("vote2") or 0)
    total = v1 + vx + v2

    print("RAW VOTES 1/X/2:", v1, vx, v2, "TOTAL:", total)

    if total > 0:
        print("PCT 1/X/2:", pct(v1, total), pct(vx, total), pct(v2, total))
        print("RESULT: SOFASCORE VOTES FOUND")
    else:
        print("RESULT: VOTES ENDPOINT WORKS, BUT NO VOTES YET")


if __name__ == "__main__":
    main()
