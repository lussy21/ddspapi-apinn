from datetime import datetime
from zoneinfo import ZoneInfo
import requests

BASE_URL = "https://www.sofascore.com/api/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.sofascore.com/",
}

# Test teams only. We use team event feeds instead of the blocked daily schedule endpoint.
TEST_TEAMS = {
    "Barcelona": 2817,
    "Feyenoord": 2959,
    "Atletico Madrid": 2836,
}


def pct(value, total):
    return round((value / total) * 100, 1) if total else 0.0


def event_date_athens(event):
    ts = event.get("startTimestamp")
    if not ts:
        return None
    return datetime.fromtimestamp(ts, ZoneInfo("Europe/Athens")).date().isoformat()


def main():
    today = datetime.now(ZoneInfo("Europe/Athens")).date().isoformat()
    session = requests.Session()
    session.headers.update(HEADERS)

    print("DATE:", today)
    seen = {}
    good_feed = False

    # Try normal team event feeds. No login/captcha bypass.
    for team_name, team_id in TEST_TEAMS.items():
        for direction in ("next", "last"):
            url = f"{BASE_URL}/team/{team_id}/events/{direction}/0"
            try:
                r = session.get(url, timeout=25)
            except Exception as exc:
                print("TEAM FEED ERROR:", team_name, direction, repr(exc))
                continue

            print("TEAM FEED:", team_name, direction, "STATUS:", r.status_code)

            if r.status_code != 200:
                continue

            good_feed = True

            try:
                payload = r.json()
            except Exception:
                continue

            for event in payload.get("events") or []:
                event_id = event.get("id")
                if not event_id or event_id in seen:
                    continue

                home = (event.get("homeTeam") or {}).get("name") or "?"
                away = (event.get("awayTeam") or {}).get("name") or "?"
                date_athens = event_date_athens(event)

                # Keep today's events, plus print nearby events if today's date
                # is missing from the provider payload.
                if date_athens != today:
                    continue

                seen[event_id] = (home, away)

    print("TODAY EVENTS FOUND:", len(seen))

    found_votes = 0

    for event_id, (home, away) in seen.items():
        votes_url = f"{BASE_URL}/event/{event_id}/votes"
        try:
            vr = session.get(votes_url, timeout=20)
        except Exception as exc:
            print("VOTES ERROR:", event_id, repr(exc))
            continue

        print("VOTES STATUS:", event_id, home, "-", away, vr.status_code)

        if vr.status_code != 200:
            continue

        try:
            vote_payload = vr.json()
        except Exception:
            continue

        votes = vote_payload.get("vote") or {}
        v1 = int(votes.get("vote1") or 0)
        vx = int(votes.get("voteX") or 0)
        v2 = int(votes.get("vote2") or 0)
        total = v1 + vx + v2

        if total <= 0:
            continue

        found_votes += 1
        print("---")
        print("MATCH:", home, "-", away)
        print("EVENT ID:", event_id)
        print("RAW VOTES 1/X/2:", v1, vx, v2, "TOTAL:", total)
        print("PCT 1/X/2:", pct(v1, total), pct(vx, total), pct(v2, total))

    if found_votes:
        print("RESULT: SOFASCORE VOTES FOUND")
    elif good_feed:
        print("RESULT: TEAM FEEDS WORK, BUT NO VOTES FOUND")
    else:
        print("RESULT: SOFASCORE TEAM FEEDS BLOCKED")


if __name__ == "__main__":
    main()
