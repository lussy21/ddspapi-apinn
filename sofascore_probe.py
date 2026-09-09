from datetime import datetime
from zoneinfo import ZoneInfo
import time

import requests

BASE_URL = "https://www.sofascore.com/api/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.sofascore.com/",
}


def pct(value, total):
    if not total:
        return 0.0
    return round((value / total) * 100, 1)


def main():
    today = datetime.now(ZoneInfo("Europe/Athens")).date().isoformat()
    session = requests.Session()
    session.headers.update(HEADERS)

    schedule_url = f"{BASE_URL}/sport/football/scheduled-events/{today}"
    response = session.get(schedule_url, timeout=30)
    print("SCHEDULE STATUS:", response.status_code)
    print("DATE:", today)

    if response.status_code != 200:
        print("SCHEDULE BODY:", response.text[:500])
        return

    payload = response.json()
    events = payload.get("events") or []
    print("EVENTS FOUND:", len(events))

    def popularity(event):
        tournament = event.get("tournament") or {}
        unique = tournament.get("uniqueTournament") or {}
        return max(
            int(event.get("userCount") or 0),
            int(tournament.get("userCount") or 0),
            int(unique.get("userCount") or 0),
        )

    events = sorted(events, key=popularity, reverse=True)
    found = 0

    for event in events[:40]:
        event_id = event.get("id")
        home = (event.get("homeTeam") or {}).get("name") or "?"
        away = (event.get("awayTeam") or {}).get("name") or "?"
        status = (event.get("status") or {}).get("type") or "?"

        if not event_id:
            continue

        votes_url = f"{BASE_URL}/event/{event_id}/votes"
        try:
            vote_response = session.get(votes_url, timeout=20)
        except Exception as exc:
            print("VOTES ERROR:", event_id, home, "-", away, repr(exc))
            continue

        if vote_response.status_code != 200:
            continue

        try:
            votes_payload = vote_response.json()
        except Exception:
            continue

        votes = votes_payload.get("vote") or {}
        vote_1 = int(votes.get("vote1") or 0)
        vote_x = int(votes.get("voteX") or 0)
        vote_2 = int(votes.get("vote2") or 0)
        total = vote_1 + vote_x + vote_2

        if total <= 0:
            continue

        found += 1
        print("---")
        print("MATCH:", home, "-", away)
        print("EVENT ID:", event_id, "STATUS:", status)
        print("RAW VOTES 1/X/2:", vote_1, vote_x, vote_2, "TOTAL:", total)
        print(
            "PCT 1/X/2:",
            pct(vote_1, total),
            pct(vote_x, total),
            pct(vote_2, total),
        )

        if found >= 10:
            break

        time.sleep(0.15)

    if found:
        print("RESULT: SOFASCORE VOTES FOUND")
    else:
        print("RESULT: NO SOFASCORE VOTES FOUND")


if __name__ == "__main__":
    main()
