"""Five independent first-morning favorite signals; existing Sheet inputs only."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contra_rise_research import ATHENS, BIG_LEAGUES, OTHER_LEAGUES, number, parse_time
from favorite_maroon_research import evidence, fixture as base_fixture, ledger_sheet, money_percentage, result_for
from morning_turnover import VERSION as LOCK_VERSION, identity, lock_matches

START_AT = datetime.fromisoformat("2026-10-29T01:05:00+02:00")
HEADERS = [
    "ΚΛΕΙΔΙ", "ΓΡΑΜΜΗ", "ΔΙΟΡΓΑΝΩΣΗ", "ΑΓΩΝΑΣ", "ΑΡΧΙΚΟ ΦΑΒΟΡΙ",
    "ΣΕΝΤΡΑ", "ΚΑΤΑΜΕΤΡΗΣΗ", "ΤΕΛΕΥΤΑΙΑ ΠΑΡΑΤΗΡΗΣΗ", "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ",
    "ΤΕΛΕΥΤΑΙΑ ΑΠΟΔΟΣΗ", "ΠΡΩΙΝΑ ΧΡΗΜΑΤΑ ΦΑΒΟΡΙ", "ΤΖΙΡΟΣ ΣΤΗΝ ΕΙΣΟΔΟ",
    "ΠΡΩΙΝΟ ΧΡΩΜΑ", "ΤΙΜΗ ΦΑΒΟΡΙ ΣΤΗΝ ΕΙΣΟΔΟ", "ΣΚΟΡ", "ΑΠΟΤΕΛΕΣΜΑ",
    "ΚΑΤΑΣΤΑΣΗ", "ΜΟΝΑΔΕΣ", "ΣΤΟΙΧΕΙΑ ΚΑΤΑΓΡΑΦΗΣ", "ΕΚΔΟΣΗ",
    "ΠΡΩΙΝΗ ΚΑΤΑΤΑΞΗ", "ΚΑΤΗΓΟΡΙΑ",
]


@dataclass(frozen=True)
class MorningProfile:
    name: str
    category: str
    color: str
    color_name: str
    threshold: int
    key_prefix: str
    version: str
    start_at: datetime = START_AT

    @property
    def sheet_name(self):
        return self.name

    @property
    def leagues(self):
        return BIG_LEAGUES if self.category == "ΜΕΓΑΛΑ" else OTHER_LEAGUES

    @property
    def headers(self):
        return HEADERS[:]


PROFILES = (
    MorningProfile("ΠΡΩΙΝΟ ΦΑΒΟΡΙ ΠΟΡΤΟΚΑΛΙ 80%", "ΜΕΓΑΛΑ", "#f6b16b", "Πορτοκαλί", 80,
                   "morning-orange80:", "morning-orange-big80-v1"),
    MorningProfile("ΠΡΩΙΝΟ ΦΑΒΟΡΙ ΚΟΚΚΙΝΟ 80%", "ΛΟΙΠΑ ΕΥΡΩΠΗΣ", "#e43935", "Κόκκινο", 80,
                   "morning-red80:", "morning-red-other80-v1"),
    MorningProfile("ΠΡΩΙΝΟ ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ 80%", "ΜΕΓΑΛΑ", "#800000", "Μπορντό", 80,
                   "morning-maroon80:", "morning-maroon-big80-v1"),
    MorningProfile("ΠΡΩΙΝΟ ΦΑΒΟΡΙ ΠΟΡΤΟΚΑΛΙ 90%", "ΜΕΓΑΛΑ", "#f6b16b", "Πορτοκαλί", 90,
                   "morning-orange90:", "morning-orange-big90-v1"),
    MorningProfile("ΠΡΩΙΝΟ ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ 90%", "ΜΕΓΑΛΑ", "#800000", "Μπορντό", 90,
                   "morning-maroon90:", "morning-maroon-big90-v1"),
)
LABELS = frozenset("🔔 " + profile.name for profile in PROFILES)


def load_profiles(spreadsheet, profiles, include_config=True):
    """Read all ledgers in one request and resolve worksheet metadata once."""
    if hasattr(spreadsheet, "worksheets") and hasattr(spreadsheet, "values_batch_get"):
        sheets = {profile.sheet_name: ledger_sheet(spreadsheet, profile.sheet_name) for profile in profiles}
        ranges = ["'ALERT LEVELS'!A2:E100"] if include_config else []
        for profile in profiles:
            sheet = sheets[profile.sheet_name]
            quoted = "'" + profile.sheet_name.replace("'", "''") + "'"
            ranges.append(f"{quoted}!A1:{chr(64 + len(profile.headers))}{sheet.row_count}")
        response = spreadsheet.values_batch_get(ranges, params={"valueRenderOption": "UNFORMATTED_VALUE"})
        blocks = response.get("valueRanges", [])
        if len(blocks) != len(ranges):
            raise ValueError("Incomplete batched color-alert ledger response")
        config = blocks[0].get("values", []) if include_config else []
        ledger_blocks = blocks[1:] if include_config else blocks
        ledgers = {profile.name: block.get("values", []) for profile, block in zip(profiles, ledger_blocks)}
    else:
        sheets = {profile.sheet_name: ledger_sheet(spreadsheet, profile.sheet_name) for profile in profiles}
        ledgers = {profile.name: sheets[profile.sheet_name].get_all_values(value_render_option="UNFORMATTED_VALUE")
                   for profile in profiles}
        config = ledger_sheet(spreadsheet, "ALERT LEVELS").get("A2:E100", value_render_option="UNFORMATTED_VALUE") if include_config else []
    statuses = {str(row[0]).strip(): str(row[4]).strip().upper() for row in config if len(row) > 4}
    return statuses, sheets, ledgers


def cell(row, index):
    return row[index] if len(row) > index else ""


def morning_snapshot(row):
    """Use the immutable T color, never current K or a reconstructed old rank."""
    try:
        raw = json.loads(str(cell(row, 94) or "{}"))
        stamp = parse_time(cell(row, 88))
        if (not lock_matches(row) or not isinstance(raw, dict) or stamp is None
                or raw.get("version") != LOCK_VERSION
                or raw.get("fixture_identity") != identity(row)
                or raw.get("T") != cell(row, 19)
                or raw.get("rank") != cell(row, 86)
                or raw.get("color") != cell(row, 87)):
            return None
        share = number(cell(row, 20))
        if share is None or not math.isfinite(share) or not 0 <= share <= 100:
            return None
        return {"T": cell(row, 19), "U": share, "rank": cell(row, 86),
                "color": cell(row, 87), "classified_at": stamp.isoformat(),
                "fixture_identity": identity(row), "lock": raw}
    except (ValueError, TypeError, IndexError):
        return None


def fixture(row, sheet_row, profile):
    item = base_fixture(row, sheet_row, profile=profile)
    if item is not None:
        item["morning"] = morning_snapshot(row)
    return item


def qualifies(item, profile, now):
    snap, price = item.get("morning"), item.get("G")
    return bool(snap and price is not None and math.isfinite(price) and price > 1
                and snap["color"] == profile.color
                and Decimal(str(snap["U"])) >= Decimal(profile.threshold)
                and parse_time(snap["classified_at"]) <= now)


def advance_record(old, item, now, fresh=False, enabled=True, profile=PROFILES[0]):
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(ATHENS)
    minutes = (item["kickoff"] - now).total_seconds() / 60
    observable = (fresh and enabled and now >= profile.start_at
                  and item["kickoff"] >= profile.start_at and minutes >= 5
                  and not item["score"])
    active = qualifies(item, profile, now)
    if old is None and not (observable and active):
        return None
    record = (list(old) + [""] * len(HEADERS))[:len(HEADERS)] if old else [""] * len(HEADERS)
    if old is None:
        snap = item["morning"]
        record[:14] = [item["key"], item["row"], item["league"],
                       item["home"] + " – " + item["away"],
                       item["home"] if item["side"] == "H" else item["away"],
                       item["kickoff"].isoformat(), now.isoformat(), now.isoformat(),
                       snap["T"], item["G"], snap["U"], item["K"] if item["K"] is not None else "",
                       profile.color_name, item["G"]]
        record[18] = json.dumps({
            "rule": profile.version, "favorite_side": item["side"], "observed_at": now.isoformat(),
            "minutes_before": minutes, "G": item["G"], "K": item["K"],
            "source_row": item["row"], "provider_id": item["provider_id"],
            "market": "original_favorite_win", "category": profile.category,
            "money_basis": "first_stored_morning_favorite_share", "threshold": profile.threshold,
            "window": "first_fresh_after_morning_snapshot_until_minus5", "morning": snap,
        }, ensure_ascii=False, sort_keys=True)
        record[19:22] = [profile.version, snap["rank"], profile.category]
    frozen = evidence(record)
    if observable:
        if frozen.get("favorite_side") != item["side"]:
            record[16] = "ΕΛΕΓΧΟΣ ΑΡΧΙΚΗΣ ΠΛΕΥΡΑΣ"
            return record
        original, current = frozen.get("morning", {}), item.get("morning") or {}
        if any(original.get(k) != current.get(k) for k in ("T", "U", "rank", "color", "fixture_identity")):
            record[16] = "ΕΛΕΓΧΟΣ ΠΡΩΙΝΟΥ ΣΤΙΓΜΙΟΤΥΠΟΥ"
            return record
        record[1], record[7], record[9] = item["row"], now.isoformat(), item["G"]
        record[16] = "ΕΝΕΡΓΟ" if active else "ΚΑΤΑΓΕΓΡΑΜΜΕΝΟ"
    if minutes <= 0:
        won = result_for(item["score"], frozen.get("favorite_side"))
        if won is None:
            record[16] = "ΑΝΑΜΟΝΗ ΣΚΟΡ"
        else:
            record[14:16] = [item["score"], "ΕΠΙΤΥΧΙΑ" if won else "ΑΠΟΤΥΧΙΑ"]
            price = number(record[13])
            record[17] = round(price - 1, 6) if won and price and price > 1 else -1 if price and price > 1 else ""
            record[16] = "ΟΛΟΚΛΗΡΩΘΗΚΕ"
    return record


def raw_sources(quote_sheet, source_rows, first_row):
    """One bounded raw read shared by all five rules; retain displayed score text."""
    last = first_row + len(source_rows) - 1
    first = max(3, first_row)
    columns = (("A", "D", 0, 4), ("G", "G", 6, 1), ("K", "K", 10, 1),
               ("T", "U", 19, 2), ("BY", "BY", 76, 1), ("CI", "CQ", 86, 9))
    ranges = [f"{a}{first}:{b}{last}" for a, b, _, _ in columns]
    blocks = quote_sheet.batch_get(ranges, value_render_option="UNFORMATTED_VALUE")
    if len(blocks) != len(columns):
        raise ValueError("Incomplete raw morning favorite response")
    rows = [list(row) + [""] * max(0, 95 - len(row)) for row in source_rows]
    originals = {i: [str(cell(row, j) or "") for j in (0, 1, 2, 3, 76)]
                 for i, row in enumerate(source_rows, first_row) if i >= 3}
    formatted_shares = {i: cell(row, 20) for i, row in enumerate(source_rows, first_row)}
    for block, (_, _, col, width) in zip(blocks, columns):
        for number_ in range(first, last + 1):
            vals = list(block[number_ - first]) if number_ - first < len(block) else []
            rows[number_ - first_row][col:col + width] = (vals + [""] * width)[:width]
    for i, row in enumerate(rows, first_row):
        if i < 3:
            continue
        if [str(cell(row, j) or "") for j in (0, 1, 2, 3, 76)] != originals[i]:
            raise ValueError("Source identity changed during morning favorite snapshot")
        row[20] = money_percentage(row[20], formatted_shares[i])
    return rows


def update_live(spreadsheet, pinnacle_rows, now, fresh_rows=(), first_row=1, quote_sheet=None, loaded=None):
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    if now < START_AT or not pinnacle_rows:
        return {"ok": True, "counted": 0, "changed": 0, "reason": "before_start_or_empty"}
    statuses, sheets, ledgers = loaded if loaded is not None else load_profiles(spreadsheet, PROFILES)
    source_rows = [list(row) for row in pinnacle_rows]
    fresh = set(fresh_rows)
    relevant = set()
    for index in fresh:
        if not first_row <= index < first_row + len(source_rows):
            continue
        source = source_rows[index - first_row]
        kickoff = parse_time(cell(source, 76))
        if (kickoff and kickoff >= START_AT and (kickoff - now).total_seconds() >= 300
                and not str(cell(source, 15) or "").strip()
                and any(statuses.get(p.name) == "ACTIVE" and cell(source, 0) in p.leagues for p in PROFILES)):
            relevant.add(index)
    if relevant:
        if quote_sheet is None:
            raise ValueError("Fresh morning favorites require exact source observations")
        source_rows = raw_sources(quote_sheet, source_rows, first_row)
    counts, total_changed = {}, 0
    for profile in PROFILES:
        sheet = sheets[profile.sheet_name]
        ledger = ledgers[profile.name]
        if len(ledger) < 6 or ledger[5][:len(HEADERS)] != HEADERS:
            raise ValueError("Morning favorite ledger header mismatch: " + profile.name)
        existing = {}
        for index, record in enumerate(ledger[6:], 7):
            if record and str(record[0]).startswith(profile.key_prefix):
                if record[0] in existing:
                    raise ValueError("Duplicate morning favorite ledger identity")
                existing[record[0]] = (index, (list(record) + [""] * len(HEADERS))[:len(HEADERS)])
        next_row = max([6] + [index for index, _ in existing.values()]) + 1
        changes = []
        for index, source in enumerate(source_rows, first_row):
            item = fixture(source, index, profile)
            if item is None:
                continue
            previous = existing.get(item["key"])
            old = previous[1] if previous else None
            updated = advance_record(old, item, now, index in relevant,
                                     statuses.get(profile.name) == "ACTIVE", profile)
            if updated is None or updated == old:
                continue
            target = previous[0] if previous else next_row
            if previous is None:
                next_row += 1
            changes.append({"range": f"A{target}:V{target}", "values": [updated]})
            existing[item["key"]] = (target, updated)
        if changes:
            if next_row - 1 > sheet.row_count:
                sheet.add_rows(next_row - 1 - sheet.row_count)
            sheet.batch_update(changes, value_input_option="RAW")
        counts[profile.name] = sum(bool(record[6]) for _, record in existing.values())
        total_changed += len(changes)
    print("MORNING FAVORITE LIVE OK | active=" + str(sum(statuses.get(p.name) == "ACTIVE" for p in PROFILES))
          + " | counted=" + json.dumps(counts, ensure_ascii=False, sort_keys=True)
          + " | changed=" + str(total_changed))
    return {"ok": True, "counted": counts, "changed": total_changed}


def settle_results(spreadsheet, pinnacle_sheet, history_rows, now):
    if now < START_AT or not history_rows:
        return {"ok": True, "changed": 0}
    try:
        loaded = load_profiles(spreadsheet, PROFILES)
        _, _, ledgers = loaded
    except (KeyError, AttributeError):
        return {"ok": False, "changed": 0, "reason": "setup_missing"}
    pending = False
    for profile in PROFILES:
        ledger = ledgers[profile.name]
        if len(ledger) < 6 or ledger[5][:len(HEADERS)] != HEADERS:
            return {"ok": False, "changed": 0, "reason": "header_mismatch"}
        pending = pending or any(len(record) > 6 and record[6] and (len(record) <= 15 or not record[15])
                                 for record in ledger[6:])
    if not pending:
        print("MORNING FAVORITE SETTLEMENT OK | pending=0")
        return {"ok": True, "changed": 0, "reason": "no_pending_results"}
    rows = [list(row) + [""] * max(0, 77 - len(row)) for row in history_rows]
    kickoffs = pinnacle_sheet.get(f"BY3:BY{len(rows) + 2}", value_render_option="UNFORMATTED_VALUE")
    for i, row in enumerate(rows):
        row[76] = kickoffs[i][0] if i < len(kickoffs) and kickoffs[i] else ""
    return update_live(spreadsheet, rows, now, first_row=3, loaded=loaded)
