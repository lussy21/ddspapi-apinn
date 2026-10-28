"""Prospective, independent Contra +0.5 research ledger; no provider requests."""

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

ATHENS = ZoneInfo("Europe/Athens")
ALERT_NAME = "ΚΟΝΤΡΑ ΑΝΟΔΟΥ 90′"
SHEET_NAME = "ΚΟΝΤΡΑ ΑΝΟΔΟΥ 90"
RULE_VERSION = "contra-rise90-v1"
START_AT = datetime.fromisoformat("2026-10-27T22:37:00+02:00")
FIRST_DATA_ROW = 7
HEADERS = [
    "ΚΛΕΙΔΙ", "ΓΡΑΜΜΗ", "ΚΑΤΗΓΟΡΙΑ", "ΔΙΟΡΓΑΝΩΣΗ", "ΑΓΩΝΑΣ",
    "ΑΡΧΙΚΟ ΦΑΒΟΡΙ", "ΣΕΝΤΡΑ", "ΠΡΩΤΗ ΕΝΔΕΙΞΗ", "ΤΕΛΕΥΤΑΙΑ ΤΙΜΗ",
    "ΑΠΟΔΟΣΗ −90′", "ΤΡΕΧΟΥΣΑ ΑΠΟΔΟΣΗ", "ΑΝΟΔΟΣ", "ΚΑΤΑΜΕΤΡΗΣΗ",
    "ΤΙΜΗ ΚΟΝΤΡΑΣ +0,5", "ΣΚΟΡ", "ΑΠΟΤΕΛΕΣΜΑ", "ΚΑΤΑΣΤΑΣΗ",
    "ΜΟΝΑΔΕΣ", "ΣΤΟΙΧΕΙΑ ΚΑΤΑΓΡΑΦΗΣ", "ΕΚΔΟΣΗ",
]
BIG_LEAGUES = frozenset({
    "England - Premier League", "Italy - Serie A", "Spain - La Liga",
    "Germany - Bundesliga", "France - Ligue 1", "UEFA - Champions League",
    "UEFA - Europa League",
})
OTHER_LEAGUES = frozenset({
    "Netherlands - Eredivisie", "Belgium - Pro League", "Turkey - Super League",
    "Greece - Super League", "Scotland - Premiership", "Norway - Eliteserien",
    "Denmark - Superliga", "Sweden - Allsvenskan", "Finland - Veikkausliiga",
    "UEFA - Conference League",
})


def number(value):
    text = str(value if value is not None else "").strip().replace("%", "")
    if not text:
        return None
    try:
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        value = float(text)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def parse_time(value):
    try:
        stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ATHENS)
        return stamp.astimezone(ATHENS)
    except (ValueError, TypeError):
        return None


def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)).casefold()
                   if c.isalnum())


def category(league):
    if league in BIG_LEAGUES:
        return "ΜΕΓΑΛΑ"
    if league in OTHER_LEAGUES:
        return "ΛΟΙΠΑ ΕΥΡΩΠΗΣ"
    return ""


def fixture(row, sheet_row):
    def cell(i):
        return row[i] if len(row) > i else ""
    league, home, away, side = [str(cell(i) or "").strip() for i in range(4)]
    ko = parse_time(cell(76))
    if not category(league) or not home or not away or side not in ("H", "A") or ko is None:
        return None
    # Stable across row moves and APINN/Pinnodds provider-id changes.
    identity = "|".join([normalize(league), normalize(home), normalize(away),
                         str(int(ko.timestamp() // 60))])
    key = "rise90:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return {"key": key, "row": sheet_row, "league": league, "home": home,
            "away": away, "side": side, "kickoff": ko, "category": category(league),
            "F": number(cell(5)), "G": number(cell(6)), "J": number(cell(9)),
            "score": str(cell(15) or "").strip(), "provider_id": str(cell(17) or "")}


def qualifies(f90, current):
    if f90 is None or current is None or not math.isfinite(f90) or not math.isfinite(current):
        return False
    return f90 > 1 and current > 1 and Decimal(str(current)) >= Decimal(str(f90)) * Decimal("1.10")


def fresh_quote_rows(updates):
    """Only actual G value writes, never turnover-only or formula refreshes."""
    rows = set()
    for update in updates:
        address = str(update.get("range", "")).split("!")[-1].replace("$", "")
        match = re.fullmatch(r"G(\d+)(?::G(\d+))?", address)
        if not match:
            continue
        first, last = int(match[1]), int(match[2] or match[1])
        values = update.get("values") or []
        for i in range(min(last - first + 1, len(values))):
            if values[i] and number(values[i][0]) is not None:
                rows.add(first + i)
    return rows


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
    favorite_won = home > away if side == "H" else away > home
    return not favorite_won


def advance_record(old, item, now, fresh=False, enabled=True):
    """Capture first usable -30..-5 observation once; never erase that pick."""
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(ATHENS)
    if now < START_AT or item["kickoff"] < START_AT:
        return old
    mins = (item["kickoff"] - now).total_seconds() / 60
    active = qualifies(item["F"], item["G"])
    observable = fresh and enabled and 5 <= mins <= 95
    if old is None and not (observable and active):
        return None
    record = (list(old) + [""] * 20)[:20] if old is not None else [""] * 20
    if old is None:
        record[:8] = [item["key"], item["row"], item["category"], item["league"],
                      item["home"] + " – " + item["away"],
                      item["home"] if item["side"] == "H" else item["away"],
                      item["kickoff"].isoformat(), now.isoformat()]
        record[18] = json.dumps({"favorite_side": item["side"], "first_F": item["F"],
                                 "rule": RULE_VERSION}, ensure_ascii=False, sort_keys=True)
        record[19] = RULE_VERSION
    frozen = evidence(record)
    side = frozen.get("favorite_side")
    # Original favorite remains fixed even if a later source side is different.
    if observable and side != item["side"]:
        record[16] = "ΕΛΕΓΧΟΣ ΑΡΧΙΚΗΣ ΠΛΕΥΡΑΣ"
        return record
    original_f = number(frozen.get("F", frozen.get("first_F")))
    if observable and original_f is not None and item["F"] != original_f:
        record[16] = "ΕΛΕΓΧΟΣ ΣΤΙΓΜΙΟΤΥΠΟΥ −90′"
        return record
    if observable:
        record[1] = item["row"]
        record[8] = now.isoformat()
        record[9:12] = [item["F"] if item["F"] is not None else "",
                         item["G"] if item["G"] is not None else "",
                         item["G"] / item["F"] - 1 if item["F"] and item["G"] else ""]
        record[16] = "ΕΝΕΡΓΟ" if active else "ΕΦΥΓΕ"
        if active and not record[12] and mins <= 30:
            record[12] = now.isoformat()
            record[13] = item["J"] if item["J"] is not None and item["J"] > 1 else ""
            record[18] = json.dumps({"rule": RULE_VERSION, "favorite_side": side,
                                     "observed_at": now.isoformat(), "minutes_before": mins,
                                     "F": item["F"], "G": item["G"], "J": item["J"],
                                     "source_row": item["row"], "provider_id": item["provider_id"],
                                     "market": "contra+0.5", "window": "-30..-5"},
                                    ensure_ascii=False, sort_keys=True)
    if mins <= 0:
        if not record[12]:
            record[16] = "ΕΚΤΟΣ ΠΑΡΑΘΥΡΟΥ ΜΕΤΡΗΣΗΣ"
        else:
            win = result_for(item["score"], side)
            if win is None:
                record[16] = "ΑΝΑΜΟΝΗ ΣΚΟΡ"
            else:
                record[14] = item["score"]
                record[15] = "ΕΠΙΤΥΧΙΑ" if win else "ΑΠΟΤΥΧΙΑ"
                price = number(record[13])
                record[17] = round(price - 1, 6) if win and price and price > 1 else -1 if price and price > 1 else ""
                record[16] = "ΟΛΟΚΛΗΡΩΘΗΚΕ"
    return record


def settle_results(spreadsheet, pinnacle_sheet, history_rows, now):
    """Enrich the legacy A:BE history input with BY; never create an entry."""
    if now < START_AT or not history_rows:
        return {"ok": True, "changed": 0, "counted": 0}
    try:
        ledger = spreadsheet.worksheet(SHEET_NAME).get_all_values()
    except Exception:
        return {"ok": False, "reason": "setup_missing"}
    pending = [r for r in ledger[6:] if len(r) > 12 and r[12] and (len(r) <= 15 or not r[15])]
    if not pending:
        print("CONTRA RISE90 SETTLEMENT | pending=0")
        return {"ok": True, "changed": 0, "reason": "no_pending_results"}
    kickoffs = pinnacle_sheet.get(f"BY3:BY{len(history_rows) + 2}",
                                 value_render_option="UNFORMATTED_VALUE")
    rows = [list(row) + [""] * max(0, 77 - len(row)) for row in history_rows]
    for i, values in enumerate(kickoffs[:len(rows)]):
        rows[i][76] = values[0] if values else ""
    return update_research(spreadsheet, rows, now, first_row=3)


def update_research(spreadsheet, pinnacle_rows, now, fresh_rows=(), first_row=1, quote_sheet=None):
    """Read/write only the dedicated research tab; do not change PINNACLE/O."""
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    if now < START_AT:
        return {"ok": True, "reason": "before_start", "changed": 0, "counted": 0}
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
        levels = spreadsheet.worksheet("ALERT LEVELS")
    except Exception as exc:
        print("CONTRA RISE90 SKIP | setup_missing |", type(exc).__name__)
        return {"ok": False, "reason": "setup_missing"}
    values = sheet.get_all_values()
    if len(values) < 6 or values[5][:20] != HEADERS:
        print("CONTRA RISE90 SKIP | header_mismatch")
        return {"ok": False, "reason": "header_mismatch"}
    config = levels.get("A2:E100", value_render_option="UNFORMATTED_VALUE")
    status = next((str(r[4]).strip().upper() for r in config
                   if len(r) > 4 and str(r[0]).strip() == ALERT_NAME), "")
    enabled = status in ("RESEARCH_ONLY", "ACTIVE")
    fresh = set(fresh_rows)
    source_rows = [list(row) for row in pinnacle_rows]
    relevant = sorted(i for i in fresh if first_row <= i < first_row + len(source_rows))
    if relevant and enabled:
        if quote_sheet is None:
            raise ValueError("Fresh research observations require unformatted source quotes")
        # get_all_values() rounds displayed prices. Preserve the exact numeric
        # F/G/J at the 10% boundary while retaining formatted football scores.
        raw = quote_sheet.batch_get([f"F{i}:J{i}" for i in relevant],
                                    value_render_option="UNFORMATTED_VALUE")
        if len(raw) != len(relevant):
            raise ValueError("Incomplete unformatted quote response")
        for index, result in zip(relevant, raw):
            quote_values = result[0] if result else []
            r = source_rows[index - first_row]
            r += [""] * max(0, 10 - len(r))
            for target, offset in [(5, 0), (6, 1), (9, 4)]:
                r[target] = quote_values[offset] if len(quote_values) > offset else ""
    existing = {}
    for index, record in enumerate(values[6:], start=FIRST_DATA_ROW):
        if record and str(record[0]).startswith("rise90:"):
            key = record[0]
            if key in existing:
                raise ValueError("Duplicate Contra Rise90 ledger identity")
            existing[key] = (index, (record + [""] * 20)[:20])
    changes = []
    new_index = max([6] + [index for index, _ in existing.values()]) + 1
    for index, row in enumerate(source_rows, start=first_row):
        item = fixture(row, index)
        if item is None:
            continue
        previous = existing.get(item["key"])
        old = previous[1] if previous else None
        updated = advance_record(old, item, now, fresh=index in fresh, enabled=enabled)
        if updated is None:
            continue
        # Formatted Sheet reads stringify numerics; avoid rewriting unchanged rows.
        equivalent = old is not None and all(str(a) == str(b) for a, b in zip(old, updated))
        if equivalent:
            continue
        target = previous[0] if previous else new_index
        if previous is None:
            new_index += 1
        changes.append({"range": f"A{target}:T{target}", "values": [updated]})
        existing[item["key"]] = (target, updated)
    if changes:
        needed = max(int(re.search(r"A(\d+)", c["range"])[1]) for c in changes)
        if needed > sheet.row_count:
            sheet.add_rows(needed - sheet.row_count)
        sheet.batch_update(changes, value_input_option="RAW")
    counted = sum(bool(record[12]) for _,record in existing.values())
    print(f"CONTRA RISE90 OK | status={status} | changed={len(changes)} | counted={counted}")
    return {"ok": True, "changed": len(changes), "counted": counted}
