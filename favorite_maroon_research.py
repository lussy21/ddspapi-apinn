"""Prospective Maroon Favorite research; consumes existing Sheet observations only."""

import hashlib
import json
import math
import re
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from contra_rise_research import ATHENS, BIG_LEAGUES, normalize, number, parse_time

ALERT_NAME = "ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ −2%"
SHEET_NAME = "ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ −2%"
RULE_VERSION = "favorite-maroon-drop2-v1"
START_AT = datetime.fromisoformat("2026-10-28T02:45:00+02:00")
FIRST_DATA_ROW = 7
HEADERS = [
    "ΚΛΕΙΔΙ", "ΓΡΑΜΜΗ", "ΔΙΟΡΓΑΝΩΣΗ", "ΑΓΩΝΑΣ", "ΑΡΧΙΚΟ ΦΑΒΟΡΙ",
    "ΣΕΝΤΡΑ", "ΚΑΤΑΜΕΤΡΗΣΗ", "ΤΕΛΕΥΤΑΙΑ ΠΑΡΑΤΗΡΗΣΗ", "ΑΠΟΔΟΣΗ −90′",
    "ΤΕΛΕΥΤΑΙΑ ΑΠΟΔΟΣΗ", "ΠΤΩΣΗ ΣΤΗΝ ΕΙΣΟΔΟ", "ΤΖΙΡΟΣ ΣΤΗΝ ΕΙΣΟΔΟ",
    "ΚΑΤΑΤΑΞΗ ΤΖΙΡΟΥ", "ΤΙΜΗ ΦΑΒΟΡΙ ΣΤΗΝ ΕΙΣΟΔΟ", "ΣΚΟΡ",
    "ΑΠΟΤΕΛΕΣΜΑ", "ΚΑΤΑΣΤΑΣΗ", "ΜΟΝΑΔΕΣ", "ΣΤΟΙΧΕΙΑ ΚΑΤΑΓΡΑΦΗΣ", "ΕΚΔΟΣΗ",
]


def fixture(row, sheet_row):
    def cell(index):
        return row[index] if len(row) > index else ""

    league, home, away, side = [str(cell(i) or "").strip() for i in range(4)]
    kickoff = parse_time(cell(76))
    if league not in BIG_LEAGUES or not home or not away or side not in ("H", "A") or kickoff is None:
        return None
    identity = "|".join([normalize(league), normalize(home), normalize(away),
                         str(int(kickoff.timestamp() // 60))])
    key = "maroon2:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return {"key": key, "row": sheet_row, "league": league, "home": home, "away": away,
            "side": side, "kickoff": kickoff, "F": number(cell(5)), "G": number(cell(6)),
            "K": number(cell(10)), "score": str(cell(15) or "").strip(),
            "provider_id": str(cell(17) or ""), "rank": None, "population": 0}


def turnover_ranks(leagues, turnovers, first_row=3):
    """Exact current K color formula: rank >87 within the same league, ties included."""
    populations = defaultdict(list)
    observations = []
    for offset, (league_cell, turnover_cell) in enumerate(zip(leagues, turnovers)):
        league = str(league_cell[0] or "").strip() if league_cell else ""
        value = number(turnover_cell[0]) if turnover_cell else None
        if league and value is not None and value >= 0:
            observations.append((first_row + offset, league, value))
            populations[league].append(value)
    for values in populations.values():
        values.sort()
    return {row: {"K": value, "rank": 100 * (bisect_right(populations[league], value) - 1)
                  / max(1, len(populations[league]) - 1), "population": len(populations[league])}
            for row, league, value in observations}


def qualifies(f90, current, rank):
    if any(value is None or not math.isfinite(value) for value in (f90, current, rank)):
        return False
    return (f90 > 1 and current > 1 and rank > 87
            and Decimal(str(current)) <= Decimal(str(f90)) * Decimal("0.98"))


def evidence(record):
    try:
        value = json.loads(str(record[18] or "{}"))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def result_for(score, side):
    match = re.fullmatch(r"(\d+)\s*[-–—]\s*(\d+)", str(score or "").strip())
    if not match or side not in ("H", "A"):
        return None
    home, away = map(int, match.groups())
    return home > away if side == "H" else away > home


def advance_record(old, item, now, fresh=False, enabled=True):
    """Count the first fresh qualifying -90..-5 quote once; freeze entry evidence."""
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(ATHENS)
    if now < START_AT or item["kickoff"] < START_AT:
        return old
    minutes = (item["kickoff"] - now).total_seconds() / 60
    observable = fresh and enabled and 5 <= minutes <= 90
    active = qualifies(item["F"], item["G"], item["rank"])
    if old is None and not (observable and active):
        return None
    record = (list(old) + [""] * 20)[:20] if old is not None else [""] * 20
    if old is None:
        record[:9] = [item["key"], item["row"], item["league"],
                      item["home"] + " – " + item["away"],
                      item["home"] if item["side"] == "H" else item["away"],
                      item["kickoff"].isoformat(), now.isoformat(), now.isoformat(), item["F"]]
        record[9:14] = [item["G"], 1 - item["G"] / item["F"], item["K"],
                         item["rank"], item["G"]]
        record[18] = json.dumps({
            "rule": RULE_VERSION, "favorite_side": item["side"], "observed_at": now.isoformat(),
            "minutes_before": minutes, "F": item["F"], "G": item["G"], "K": item["K"],
            "turnover_rank": item["rank"], "league_population": item["population"],
            "color": "#800000", "source_row": item["row"], "provider_id": item["provider_id"],
            "market": "original_favorite_win", "window": "-90..-5",
        }, ensure_ascii=False, sort_keys=True)
        record[19] = RULE_VERSION
    frozen = evidence(record)
    side = frozen.get("favorite_side")
    if observable and side != item["side"]:
        record[16] = "ΕΛΕΓΧΟΣ ΑΡΧΙΚΗΣ ΠΛΕΥΡΑΣ"
        return record
    if observable and item["F"] != number(frozen.get("F")):
        record[16] = "ΕΛΕΓΧΟΣ ΣΤΙΓΜΙΟΤΥΠΟΥ −90′"
        return record
    if observable:
        record[1], record[7], record[9] = item["row"], now.isoformat(), item["G"]
        record[16] = "ΕΝΕΡΓΟ" if active else "ΕΦΥΓΕ"
    if minutes <= 0:
        won = result_for(item["score"], side)
        if won is None:
            record[16] = "ΑΝΑΜΟΝΗ ΣΚΟΡ"
        else:
            record[14] = item["score"]
            record[15] = "ΕΠΙΤΥΧΙΑ" if won else "ΑΠΟΤΥΧΙΑ"
            price = number(record[13])
            record[17] = round(price - 1, 6) if won and price and price > 1 else -1 if price and price > 1 else ""
            record[16] = "ΟΛΟΚΛΗΡΩΘΗΚΕ"
    return record


def update_research(spreadsheet, pinnacle_rows, now, fresh_rows=(), first_row=1, quote_sheet=None):
    """Write the dedicated research ledger only; existing O and alerts stay separate."""
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    if now < START_AT:
        return {"ok": True, "reason": "before_start", "changed": 0, "counted": 0}
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
        levels = spreadsheet.worksheet("ALERT LEVELS")
    except Exception as exc:
        print("FAV MAROON2 SKIP | setup_missing |", type(exc).__name__)
        return {"ok": False, "reason": "setup_missing"}
    ledger_values = sheet.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if len(ledger_values) < 6 or ledger_values[5][:20] != HEADERS:
        print("FAV MAROON2 SKIP | header_mismatch")
        return {"ok": False, "reason": "header_mismatch"}
    config = levels.get("A2:E100", value_render_option="UNFORMATTED_VALUE")
    status = next((str(row[4]).strip().upper() for row in config
                   if len(row) > 4 and str(row[0]).strip() == ALERT_NAME), "")
    enabled = status in ("RESEARCH_ONLY", "ACTIVE")
    source_rows = [list(row) for row in pinnacle_rows]
    fresh = set(fresh_rows)
    relevant = []
    if enabled:
        for index in sorted(fresh):
            if first_row <= index < first_row + len(source_rows):
                item = fixture(source_rows[index - first_row], index)
                if item and 5 <= (item["kickoff"] - now).total_seconds() / 60 <= 90:
                    relevant.append(index)
    ranks = {}
    if relevant:
        if quote_sheet is None:
            raise ValueError("Fresh observations require exact source quotes and turnover")
        last_row = first_row + len(source_rows) - 1
        ranges = [f"A3:A{last_row}", f"K3:K{last_row}"] + [f"F{i}:G{i}" for i in relevant]
        raw = quote_sheet.batch_get(ranges, value_render_option="UNFORMATTED_VALUE")
        if len(raw) != len(ranges):
            raise ValueError("Incomplete unformatted quote/turnover response")
        # Google omits trailing blank values; preserve row positions in each column.
        width = max(0, last_row - 2)
        leagues = list(raw[0]) + [[]] * max(0, width - len(raw[0]))
        turnovers = list(raw[1]) + [[]] * max(0, width - len(raw[1]))
        ranks = turnover_ranks(leagues, turnovers)
        for index, result in zip(relevant, raw[2:]):
            quote_values = result[0] if result else []
            source = source_rows[index - first_row]
            source += [""] * max(0, 11 - len(source))
            source[5] = quote_values[0] if quote_values else ""
            source[6] = quote_values[1] if len(quote_values) > 1 else ""
            source[10] = ranks.get(index, {}).get("K", "")
            live_league = leagues[index - 3][0] if leagues[index - 3] else ""
            if str(live_league).strip() != str(source[0]).strip():
                raise ValueError("Source league changed during research snapshot")
    existing = {}
    for index, record in enumerate(ledger_values[6:], start=FIRST_DATA_ROW):
        if record and str(record[0]).startswith("maroon2:"):
            if record[0] in existing:
                raise ValueError("Duplicate Maroon Favorite ledger identity")
            existing[record[0]] = (index, (list(record) + [""] * 20)[:20])
    changes = []
    new_index = max([6] + [index for index, _ in existing.values()]) + 1
    for index, row in enumerate(source_rows, start=first_row):
        item = fixture(row, index)
        if item is None:
            continue
        item.update(ranks.get(index, {}))
        previous = existing.get(item["key"])
        old = previous[1] if previous else None
        updated = advance_record(old, item, now, fresh=index in relevant, enabled=enabled)
        if updated is None or old == updated:
            continue
        target = previous[0] if previous else new_index
        if previous is None:
            new_index += 1
        changes.append({"range": f"A{target}:T{target}", "values": [updated]})
        existing[item["key"]] = (target, updated)
    if changes:
        needed = max(int(re.search(r"A(\d+)", change["range"])[1]) for change in changes)
        if needed > sheet.row_count:
            sheet.add_rows(needed - sheet.row_count)
        sheet.batch_update(changes, value_input_option="RAW")
    counted = sum(bool(record[6]) for _, record in existing.values())
    print(f"FAV MAROON2 OK | status={status} | changed={len(changes)} | counted={counted}")
    return {"ok": True, "changed": len(changes), "counted": counted}


def settle_results(spreadsheet, pinnacle_sheet, history_rows, now):
    """After Sofa results, settle existing entries without creating historical ones."""
    if now < START_AT or not history_rows:
        return {"ok": True, "changed": 0, "counted": 0}
    try:
        ledger = spreadsheet.worksheet(SHEET_NAME).get_all_values(value_render_option="UNFORMATTED_VALUE")
    except Exception:
        return {"ok": False, "reason": "setup_missing"}
    pending = [row for row in ledger[6:] if len(row) > 6 and row[6] and (len(row) <= 15 or not row[15])]
    if not pending:
        print("FAV MAROON2 SETTLEMENT | pending=0")
        return {"ok": True, "changed": 0, "reason": "no_pending_results"}
    kickoffs = pinnacle_sheet.get(f"BY3:BY{len(history_rows) + 2}", value_render_option="UNFORMATTED_VALUE")
    rows = [list(row) + [""] * max(0, 77 - len(row)) for row in history_rows]
    for index, values in enumerate(kickoffs[:len(rows)]):
        rows[index][76] = values[0] if values else ""
    return update_research(spreadsheet, rows, now, first_row=3)
