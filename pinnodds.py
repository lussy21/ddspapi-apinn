"""Pinnodds prematch fallback used by the existing, single Sheet writer.

No collector runs on import. One scheduled bulk request supplies all fixtures;
there are no per-event requests, retries, or substitutions for absent +0.5 odds.
"""

from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import json
import math
import re
import unicodedata
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ATHENS = ZoneInfo("Europe/Athens")
ENDPOINT = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
ID_PREFIX = "pinnodds:"
STATE_TITLE = "PINNODDS STATE"
MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_AGE_MS = 120_000
DAILY_AUTOMATIC_LIMIT = 60


class FeedError(Exception):
    """Safe diagnostic text, without credentials or response bodies."""


def price(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 1 else None


def kickoff_time(value):
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(ATHENS)
    except (TypeError, ValueError):
        return None


def betting_day_start(kickoff):
    anchor = kickoff.replace(hour=11, minute=0, second=0, microsecond=0)
    return anchor - timedelta(days=1) if kickoff < anchor else anchor


def request_slot(now):
    """Allow cron startup delays inside each agreed ten-minute slot, Athens time."""
    local = now.astimezone(ATHENS)
    minute = local.hour * 60 + (local.minute // 10) * 10
    if minute not in (11 * 60, 12 * 60) and not 13 * 60 <= minute <= 22 * 60 + 30:
        return None
    return local.replace(minute=(local.minute // 10) * 10, second=0, microsecond=0)


def _words(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def team_key(value):
    key = _words(value)
    key = " ".join(t for t in key.split() if t not in {"fc", "cf", "afc", "sc", "fk", "sk", "vfb", "ac"})
    return {
        "man utd": "manchester united", "internazionale": "inter",
        "shakhtar donetsk": "shakhtar", "real betis": "betis",
        "lepsia": "rb leipzig", "lans": "lens", "vicking": "viking",
        "bilbao": "athletic bilbao", "lask": "lask linz",
        "sporting lisbon": "sporting cp", "sporting club de portugal": "sporting cp",
        "paris saint germain": "paris st g", "paris sg": "paris st g", "psg": "paris st g",
        "atletico de madrid": "atletico madrid", "club atletico de madrid": "atletico madrid",
    }.get(key, key)


def league_key(value):
    value = str(value or "").removeprefix("ΕΘΝΙΚΕΣ - ")
    key = _words(value)
    countries = {"spain": "spanish", "england": "english", "germany": "german",
                 "italy": "italian", "france": "french", "scotland": "scottish",
                 "portugal": "portuguese", "belgium": "belgian", "greece": "greek"}
    words = key.split()
    if words:
        words[0] = countries.get(words[0], words[0])
    key = " ".join(words)
    return {"usa mls": "usa major league soccer", "turkey super league": "turkey super lig",
            "belgian first division a": "belgian pro league",
            "argentina liga profesional": "argentina liga pro",
            "uefa europa conference league": "uefa conference league"}.get(key, key)


def _is_secondary(value):
    return bool(re.search(r"\b(corners?|bookings?|cards?|women|ladies|female|youth|reserves?|u\s*\d{2}|under\s*\d{2})\b", _words(value)))


def _handicap(spreads, target, side):
    if not isinstance(spreads, dict):
        return None
    quotes = set()
    for key, line in spreads.items():
        if not isinstance(line, dict):
            continue
        try:
            key_number = Decimal(str(key))
            number = Decimal(str(line.get("hdp", key)))
        except InvalidOperation:
            continue
        if not number.is_finite() or not key_number.is_finite():
            continue
        if number != key_number:
            raise FeedError("Conflicting handicap fields; fixture withheld.")
        if number == target:
            quote = price(line.get(side))
            if quote is not None:
                quotes.add(quote)
    if len(quotes) > 1:
        raise FeedError("Conflicting +0.5 quotes; fixture withheld.")
    return next(iter(quotes), None)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_board(api_key):
    request = urllib.request.Request(ENDPOINT, headers={
        "x-portal-apikey": api_key, "Accept": "application/json",
        "User-Agent": "ddspapi-pinnodds-fallback/1.0",
    })
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=25) as response:
            headers = {"status": response.headers.get("X-Data-Status", "unknown"),
                       "board": response.headers.get("X-Data-Board", "unknown"),
                       "age_ms": response.headers.get("X-Data-Age-Ms")}
            raw = response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise FeedError(f"HTTP {exc.code}; no retry.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise FeedError("Connection failed; no retry.") from None
    if len(raw) > MAX_BODY_BYTES:
        raise FeedError("Response exceeds 32 MiB.")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise FeedError("Invalid JSON.") from None
    return payload, headers


def normalize_board(payload, headers, now, accepts_league):
    """Return only fresh, open, full-match men's soccer, in the current betting day."""
    if headers.get("status") != "fresh" or headers.get("board") != "prematch":
        raise FeedError("Fresh prematch data not confirmed.")
    try:
        age = float(headers.get("age_ms"))
    except (TypeError, ValueError):
        raise FeedError("Feed age missing.") from None
    if not math.isfinite(age) or not 0 <= age <= MAX_AGE_MS:
        raise FeedError("Feed is too old.")
    if not isinstance(payload, dict) or str(payload.get("sport_id")) != "1" or not isinstance(payload.get("events"), list):
        raise FeedError("Unexpected soccer board shape.")
    chosen = {}
    for event in payload["events"]:
        if not isinstance(event, dict) or str(event.get("sport_id")) != "1":
            continue
        if event.get("event_type") != "prematch" or event.get("special") or event.get("parent_id"):
            continue
        league, home, away = (str(event.get(k) or "").strip() for k in ("league_name", "home", "away"))
        if not (league and home and away) or any(_is_secondary(v) for v in (league, home, away)):
            continue
        if not accepts_league(league):
            continue
        kickoff = kickoff_time(event.get("starts") or event.get("start_ts"))
        if kickoff is None or (kickoff - now).total_seconds() < 300 or now < betting_day_start(kickoff):
            continue
        periods = event.get("periods")
        period = periods.get("num_0") if isinstance(periods, dict) else None
        if not isinstance(period, dict) or str(period.get("number")) != "0" or period.get("status") != "open":
            continue
        moneyline = period.get("money_line") or {}
        if not isinstance(moneyline, dict):
            continue
        home_price, away_price = price(moneyline.get("home")), price(moneyline.get("away"))
        if home_price is None or away_price is None:
            continue
        event_id = str(event.get("event_id") or "")
        if not event_id.isdecimal():
            continue
        try:
            away_contra = _handicap(period.get("spreads"), Decimal("-0.5"), "away")
            home_contra = _handicap(period.get("spreads"), Decimal("0.5"), "home")
        except FeedError:
            print("PINNODDS FIXTURE WITHHELD: conflicting handicap | event:", event_id)
            continue
        spreads = []
        if away_contra is not None:
            spreads.append({"market": "spread", "period": 0, "line": -0.5, "odds2": away_contra})
        if home_contra is not None:
            spreads.append({"market": "spread", "period": 0, "line": 0.5, "odds1": home_contra})
        match = {"event_id": ID_PREFIX + event_id, "runner_home": home, "runner_away": away,
                 "league_name": league, "starts": kickoff.isoformat(),
                 "odds": {"moneyline": {"odds1": home_price, "odds2": away_price}},
                 "_direct_event_odds": spreads, "_provider": "pinnodds"}
        identity = (league_key(league), team_key(home), team_key(away), kickoff.replace(second=0, microsecond=0))
        previous = chosen.get(identity)
        if previous is None or len(spreads) > len(previous["_direct_event_odds"]):
            chosen[identity] = match
    return sorted(chosen.values(), key=lambda m: (m["starts"], m["league_name"], m["runner_home"]))


def primary_has_prices(matches, now):
    for match in matches:
        kickoff = kickoff_time(match.get("starts"))
        if kickoff is None or kickoff <= now or now < betting_day_start(kickoff):
            continue
        quotes = (match.get("odds") or {}).get("moneyline") or {}
        if price(quotes.get("odds1")) is not None and price(quotes.get("odds2")) is not None:
            return True
    return False


def _reserve_request(spreadsheet, slot):
    """Persistent budget across cron processes/deploys; Render serializes cron runs.

    Reserve BEFORE HTTP, so failed requests consume the automatic budget too.
    State failure disables the fallback for that run, leaving other collectors free.
    """
    import gspread
    try:
        state = spreadsheet.worksheet(STATE_TITLE)
    except gspread.WorksheetNotFound:
        result = spreadsheet.batch_update({"requests": [{"addSheet": {"properties": {
            "title": STATE_TITLE, "hidden": True, "gridProperties": {"rowCount": 3, "columnCount": 6},
        }}}]})
        state = spreadsheet.get_worksheet_by_id(result["replies"][0]["addSheet"]["properties"]["sheetId"])
    values = state.get("A2:D2")
    previous = list(values[0]) if values else []
    previous += [""] * (4 - len(previous))
    day, last_slot, count, _ = previous[:4]
    today = slot.date().isoformat()
    count = int(count or 0) if day == today else 0
    slot_text = slot.isoformat()
    if day == today and last_slot and str(last_slot) >= slot_text:
        print("PINNODDS SKIPPED: slot already reserved")
        return None
    if count < 0 or count >= DAILY_AUTOMATIC_LIMIT:
        print("PINNODDS SKIPPED: automatic daily request cap")
        return None
    state.batch_update([
        {"range": "A1:F1", "values": [["Athens day", "Last reserved slot", "Requests reserved", "Last attempt", "Last fresh board", "Eligible fixtures"]]},
        {"range": "A2:D2", "values": [[today, slot_text, count + 1, datetime.now(ATHENS).isoformat()]]},
    ], value_input_option="RAW")
    return state


def choose_matches(matches, now, spreadsheet, api_key, accepts_league, enabled=True, fetcher=None):
    """Select one odds provider for this run. Working APINN uses zero fallback calls."""
    if primary_has_prices(matches, now):
        print("ODDS SOURCE: APINN | Pinnodds standby")
        return matches
    if not enabled or not api_key:
        print("PINNODDS SKIPPED: fallback disabled or key missing")
        return matches
    slot = request_slot(now)
    if slot is None:
        print("PINNODDS SKIPPED: outside agreed Athens schedule")
        return matches
    try:
        state = _reserve_request(spreadsheet, slot)
        if state is None:
            return matches
        payload, headers = (fetcher or read_board)(api_key)
        selected = normalize_board(payload, headers, datetime.now(ATHENS), accepts_league)
        # Metadata failure cannot invalidate an already checked, fresh board.
        try:
            state.batch_update([{"range": "E2:F2", "values": [[datetime.now(ATHENS).isoformat(), len(selected)]]}], value_input_option="RAW")
        except Exception as exc:
            print("PINNODDS STATE METADATA ERROR:", type(exc).__name__)
        print("ODDS SOURCE: PINNODDS FALLBACK | fixtures:", len(selected), "| age_ms:", headers["age_ms"])
        return selected
    except FeedError as exc:
        print("PINNODDS WITHHELD:", str(exc))
    except Exception as exc:
        print("PINNODDS FALLBACK ERROR:", type(exc).__name__)
    return matches


def link_fixture_rows(sheet_rows, matches, event_rows):
    """Bind both feeds to the same row; keep old APINN IDs during fallback.

    A new fallback row has a namespaced ID, retained when APINN returns so alert
    history and SofaScore cache keys remain stable. The actual APINN request ID
    travels separately in memory; fixed odds snapshots are never changed here.
    Ambiguous or completed fixtures are withheld instead of creating duplicates.
    """
    updates, accepted, seen = [], [], []
    labels = {}
    for row in sheet_rows[2:]:
        if len(row) > 2 and all(str(v).strip() for v in row[:3]):
            label = str(row[0]).removeprefix("ΕΘΝΙΚΕΣ - ")
            labels.setdefault(league_key(label), Counter())[label] += 1
    for original_match in matches:
        match = dict(original_match)
        event_id = str(match.get("event_id") or "").strip()
        kickoff = kickoff_time(match.get("starts"))
        if not event_id or kickoff is None:
            continue
        league = league_key(match.get("league_name"))
        home, away = team_key(match.get("runner_home")), team_key(match.get("runner_away"))
        if any(league == lg and home == h and away == a and abs((kickoff - ko).total_seconds()) <= 300 for lg, h, a, ko in seen):
            continue
        candidates, near = [], []
        known = event_rows.get(event_id)
        for number, row in enumerate(sheet_rows, 1):
            if number < 3 or len(row) <= 17 or league_key(row[0]) != league:
                continue
            rh, ra = team_key(row[1]), team_key(row[2])
            stored_kickoff = kickoff_time(row[76]) if len(row) > 76 else None
            # Previously recorded APINN rows can predate the BY metadata column.
            # A trusted existing ID plus both exact teams/league can repair BY.
            if number == known and stored_kickoff is None and (home, away) == (rh, ra):
                candidates.append(number)
                continue
            if stored_kickoff is None or abs((kickoff - stored_kickoff).total_seconds()) > 300:
                continue
            if (home, away) == (rh, ra):
                candidates.append(number)
            elif min(SequenceMatcher(None, home, rh).ratio(), SequenceMatcher(None, away, ra).ratio()) >= 0.72:
                near.append(number)
        if len(candidates) > 1 or (not candidates and near) or (known and candidates != [known]):
            print("ODDS FIXTURE WITHHELD: ambiguous row identity | event:", event_id)
            continue
        if candidates:
            number = candidates[0]
            row = sheet_rows[number - 1]
            if str(row[15]).strip():
                continue
            # Percentiles group by the literal Sheet league label. Feed aliases
            # must not split one competition into separate statistical groups.
            match["league_name"] = str(row[0]).removeprefix("ΕΘΝΙΚΕΣ - ")
            old_id = str(row[17]).strip()
            if old_id:
                if match.get("_provider") != "pinnodds":
                    match["_apinn_event_id"] = match.get("_apinn_event_id", match["event_id"])
                match["event_id"] = old_id
                event_rows[old_id] = number
            else:
                event_rows[event_id] = number
                if old_id != event_id:
                    updates.append({"range": f"R{number}", "values": [[event_id]]})
                    row[17] = event_id
                    if old_id:
                        event_rows.pop(old_id, None)
                    print("ODDS ROW LINKED:", number, "| source:", match.get("_provider", "apinn"))
        elif match.get("_provider") == "pinnodds" and league in labels:
            match["league_name"] = labels[league].most_common(1)[0][0]
        seen.append((league, home, away, kickoff))
        accepted.append(match)
    matches[:] = accepted
    return updates
