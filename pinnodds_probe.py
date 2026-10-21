"""Inspect Pinnodds without importing or writing to the production collectors.

Default invocation prints the proposed request budget; it makes no API calls.
Set PINNODDS_API_KEY privately, then pass --fetch for one prematch request.
Output is a diagnostic JSON report on stdout. No files, Sheets, cron schedules,
production configuration, favorite selections or historical prices are changed.
"""

import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import os
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


ATHENS = ZoneInfo("Europe/Athens")
ENDPOINT = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
MAX_BODY_BYTES = 32 * 1024 * 1024


class ProbeError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the API credential to a different URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def decimal_price(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return float(number) if number.is_finite() and number > 1 else None


def half_goal_price(spreads, home_handicap, side):
    """Report the specified side's +0.5 quote, never an adjacent handicap."""
    if not isinstance(spreads, dict):
        return None
    prices = set()
    for key, line in spreads.items():
        if not isinstance(line, dict):
            continue
        try:
            key_handicap = Decimal(str(key))
            handicap = Decimal(str(line.get("hdp", key)))
        except InvalidOperation:
            continue
        if not key_handicap.is_finite() or not handicap.is_finite():
            continue
        if key_handicap != handicap:
            raise ProbeError("Handicap key and hdp disagree; manual review required.")
        if handicap == home_handicap:
            price = decimal_price(line.get(side))
            if price is not None:
                prices.add(price)
    if len(prices) > 1:
        raise ProbeError("Conflicting prices for the same handicap; manual review required.")
    return next(iter(prices), None)


def read_board(api_key):
    request = urllib.request.Request(
        ENDPOINT,
        headers={
            "x-portal-apikey": api_key,
            "Accept": "application/json",
            "User-Agent": "ddspapi-pinnodds-readonly-probe/1.0",
        },
        method="GET",
    )
    # One request only: no retries, extra health calls, per-event lookups or loops.
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=25) as response:
            headers = {
                "status": response.headers.get("X-Data-Status", "unknown"),
                "board": response.headers.get("X-Data-Board", "unknown"),
                "age_ms": response.headers.get("X-Data-Age-Ms"),
            }
            raw = response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ProbeError(f"Pinnodds HTTP {exc.code}; no retry attempted.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ProbeError("Pinnodds connection failed; no retry attempted.") from None
    if len(raw) > MAX_BODY_BYTES:
        raise ProbeError("Response exceeds the probe's 32 MiB limit.")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProbeError("Response is not valid JSON.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ProbeError("Unexpected response shape; expected an events list.")
    if str(payload.get("sport_id")) != "1":
        raise ProbeError("Response is not the requested soccer board.")
    return payload, headers


def inspect_events(events, requested_date, now):
    rows = []
    invalid_events = 0
    for event in events:
        if not isinstance(event, dict):
            invalid_events += 1
            continue
        if event.get("event_type") != "prematch" or event.get("special"):
            continue
        if str(event.get("sport_id")) != "1":
            invalid_events += 1
            continue
        try:
            kickoff = datetime.fromisoformat(
                str(event.get("starts") or event.get("start_ts") or "").replace("Z", "+00:00")
            )
            if kickoff.tzinfo is None:
                raise ValueError("Kickoff has no timezone")
        except ValueError:
            invalid_events += 1
            continue
        local_kickoff = kickoff.astimezone(ATHENS)
        if local_kickoff.date() != requested_date or local_kickoff <= now:
            continue
        periods = event.get("periods")
        full_match = periods.get("num_0") if isinstance(periods, dict) else None
        if not isinstance(full_match, dict):
            invalid_events += 1
            continue
        moneyline = full_match.get("money_line") or {}
        if not isinstance(moneyline, dict):
            invalid_events += 1
            continue
        spreads = full_match.get("spreads")
        rows.append({
            "pinnodds_event_id": event.get("event_id"),
            "league": event.get("league_name"),
            "home": event.get("home"),
            "away": event.get("away"),
            "kickoff_greece": local_kickoff.isoformat(),
            "home_1x2": decimal_price(moneyline.get("home")),
            "draw_1x2": decimal_price(moneyline.get("draw")),
            "away_1x2": decimal_price(moneyline.get("away")),
            "home_plus_0_5": half_goal_price(spreads, Decimal("0.5"), "home"),
            "away_plus_0_5": half_goal_price(spreads, Decimal("-0.5"), "away"),
        })
    rows.sort(key=lambda row: (row["kickoff_greece"], str(row["league"]), str(row["home"])))
    return rows, invalid_events


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Make exactly one API request.")
    parser.add_argument("--date", type=date.fromisoformat, help="Greece calendar date, YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum sample rows to print (0-200).")
    args = parser.parse_args(argv)
    if not 0 <= args.limit <= 200:
        parser.error("--limit must be between 0 and 200")
    report = {
        "mode": "read_only_probe",
        "production_writes": False,
        "api_requests_attempted": 0,
        "proposed_schedule_only": {
            "timezone": "Europe/Athens",
            "single_requests_greece": ["11:00", "12:00"],
            "ten_minute_window_greece": "13:00-22:30 inclusive",
            "interval_minutes": 10,
            "base_requests_per_day": 60,
            "free_daily_limit": 100,
            "remaining_for_checks_and_retries": 40,
            "schedule_created": False,
        },
    }
    if not args.fetch:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    api_key = os.environ.get("PINNODDS_API_KEY", "").strip()
    if not api_key:
        report["error"] = "PINNODDS_API_KEY is missing; no API request was made."
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    report["api_requests_attempted"] = 1
    try:
        payload, headers = read_board(api_key)
        report["feed"] = headers
        if headers["status"] != "fresh" or headers["board"] != "prematch":
            raise ProbeError("Fresh prematch data is not confirmed; quotes withheld.")
        now = datetime.now(ATHENS)
        requested_date = args.date or now.date()
        rows, invalid_events = inspect_events(payload["events"], requested_date, now)
        report.update({
            "fetched_at_greece": now.isoformat(),
            "selected_date_greece": requested_date.isoformat(),
            "board_events_returned": len(payload["events"]),
            "selected_upcoming_fixtures": len(rows),
            "events_with_unexpected_fields": invalid_events,
            "fixtures_with_home_plus_0_5": sum(row["home_plus_0_5"] is not None for row in rows),
            "fixtures_with_away_plus_0_5": sum(row["away_plus_0_5"] is not None for row in rows),
            "sample": rows[:args.limit],
            "note": "Both +0.5 sides are reported; no production favorite or contra is selected.",
        })
    except ProbeError as exc:
        report["error"] = str(exc)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
