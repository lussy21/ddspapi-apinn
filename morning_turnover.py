"""Freeze the first T turnover's same-league classification; no provider I/O."""

from bisect import bisect_right, insort
from collections import defaultdict
from datetime import datetime
import json
import math
import re
from statistics import fmean
from zoneinfo import ZoneInfo

ATHENS = ZoneInfo("Europe/Athens")
VERSION = "morning-turnover-frozen-v2"
LEGACY_VERSION = "morning-turnover-frozen-v1"
START_COLUMN = 86  # CI, after the existing CH analyst notes.
END_COLUMN = 95    # CQ inclusive.
HISTORICAL = "HISTORICAL_BASELINE"
HISTORICAL_ROW_ORDER = "HISTORICAL_ROW_ORDER"
FIRST_OBSERVATION = "FIRST_OBSERVATION"
HEADERS = ["ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΚΑΤΑΤΑΞΗ", "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΧΡΩΜΑ",
           "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΚΛΕΙΔΩΜΑ", "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΔΕΙΓΜΑ",
           "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΜΕΣΟΣ ΟΡΟΣ", "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΠΡΟΕΛΕΥΣΗ",
           "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΠΟΣΟ ΕΙΣΟΔΟΥ", "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΤΑΥΤΟΤΗΤΑ",
           "ΠΡΩΙΝΟΣ ΤΖΙΡΟΣ ΣΤΟΙΧΕΙΑ"]
COLORS = ("#cfe1f3", "#f6b16b", "#e43935", "#800000")


def cell(row, index):
    return row[index] if index < len(row) else ""


def numeric(value):
    # Match Sheets ISNUMBER: numeric-looking text and booleans are not turnover.
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def eligible(row):
    return (all(str(cell(row, i)).strip() for i in (0, 1, 2))
            and numeric(cell(row, 19)) and cell(row, 19) >= 0)


def identity(row):
    return "¦".join(str(cell(row, index)) for index in (0, 1, 2, 76))


def color_for(rank):
    if rank <= 35:
        return COLORS[0]
    if rank <= 75:
        return COLORS[1]
    if rank <= 87:
        return COLORS[2]
    return COLORS[3]


def has_lock(row):
    return any(cell(row, index) != "" for index in range(START_COLUMN, END_COLUMN))


def lock_matches(row):
    return (numeric(cell(row, 86)) and cell(row, 87) == color_for(cell(row, 86))
            and cell(row, 92) == cell(row, 19) and cell(row, 93) == identity(row))


def build_lock_updates(rows, now, targets=None, mode=HISTORICAL_ROW_ORDER):
    """Use only same-league T values through this physical row; freeze once.

    HISTORICAL is retained solely to reproduce the archived v1 full-sample
    baseline. The default historical rebuild and new first observations use
    row prefixes. Historical row order does not claim original capture times.
    """
    if now.tzinfo is None or mode not in (HISTORICAL, HISTORICAL_ROW_ORDER, FIRST_OBSERVATION):
        raise ValueError("Classification requires a timezone and a known capture mode")
    populations = defaultdict(list)
    prefix = mode != HISTORICAL
    if not prefix:
        for number, row in enumerate(rows, start=1):
            if number >= 3 and eligible(row):
                populations[str(row[0])].append(row[19])
        for values in populations.values():
            values.sort()
    selected = set(targets) if targets is not None else set(range(3, len(rows) + 1))
    stamp = now.astimezone(ATHENS).isoformat()
    updates = []
    for number, row in enumerate(rows, start=1):
        if number < 3 or not eligible(row):
            continue
        league, amount = str(row[0]), row[19]
        if prefix:
            insort(populations[league], amount)
        if number not in selected or has_lock(row):
            continue
        values = populations[league]
        n = len(values)
        # Exactly the current K empirical-rank convention, including tied values
        # and the N=1 boundary. Reference only morning T, never closing K/W.
        rank = 100 * (bisect_right(values, amount) - 1) / max(1, n - 1)
        color = color_for(rank)
        mean = fmean(values)
        evidence = {"version": VERSION if prefix else LEGACY_VERSION, "classified_at": stamp, "mode": mode,
                    "first_observed_at": stamp if mode == FIRST_OBSERVATION else None,
                    "league": league, "fixture_identity": identity(row), "source_column": "T",
                    "source_row": number, "T": amount, "rank": rank, "color": color,
                    "population": n, "population_mean": mean,
                    "population_min": values[0], "population_max": values[-1],
                    "scope": "PINNACLE_morning_T_same_league_rows_3_through_current" if prefix else "all_PINNACLE_morning_T_within_same_league",
                    "reference_last_row": number if prefix else len(rows),
                    "capture_time_known": mode == FIRST_OBSERVATION,
                    "reference_order": "PINNACLE_PHYSICAL_ROWS" if prefix else "FULL_SAVED_SAMPLE",
                    "boundaries": [35, 75, 87], "immutable": True}
        record = [rank, color, stamp, n, mean, mode, amount, identity(row),
                  json.dumps(evidence, ensure_ascii=False, sort_keys=True)]
        updates.append({"range": f"CI{number}:CQ{number}", "values": [record]})
    return updates


def coordinates(update):
    address = str(update.get("range", "")).split("!")[-1].replace("$", "")
    match = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", address)
    if not match:
        return None
    def column(text):
        result = 0
        for char in text:
            result = result * 26 + ord(char) - 64
        return result - 1
    return column(match[1]), int(match[2]), column(match[3] or match[1]), int(match[4] or match[2])


def t_rows(pending):
    found = set()
    for update in pending:
        area = coordinates(update)
        if area is None or not area[0] <= 19 <= area[2]:
            continue
        first_col, first_row, _, last_row = area
        for offset, values in enumerate(update.get("values", [])):
            if first_row + offset <= last_row and len(values) > 19-first_col:
                found.add(first_row + offset)
    return found


def overlay(rows, pending):
    for update in pending:
        area = coordinates(update)
        if area is None:
            continue
        first_col, first_row, last_col, last_row = area
        for offset, values in enumerate(update.get("values", [])):
            number = first_row + offset
            if number > last_row:
                break
            while len(rows) < number:
                rows.append([""] * END_COLUMN)
            for j, value in enumerate(values):
                col = first_col + j
                if col <= last_col and (col < 4 or col in (19, 76) or START_COLUMN <= col < END_COLUMN):
                    rows[number-1][col] = value


def attach_morning_locks(sheet, source_rows, pending, now):
    """Put first T:V and frozen CI:CQ into the SAME existing collector batch.

    On a Sheets-read/validation failure withhold only the new morning snapshot;
    live odds and current turnover still proceed, and the next run can retry.
    """
    targets = t_rows(pending)
    if not targets:
        print(f"MORNING TURNOVER LOCK OK | new=0 | version={VERSION}")
        return list(pending)
    try:
        last = max(len(source_rows), max(targets))
        ranges = [f"A3:D{last}", f"T3:T{last}", f"BY3:BY{last}", f"CI3:CQ{last}"]
        blocks = sheet.batch_get(ranges, value_render_option="UNFORMATTED_VALUE")
        if len(blocks) != len(ranges):
            raise ValueError("Incomplete raw morning-turnover response")
        rows = [[""] * END_COLUMN for _ in range(last)]
        for block, first_col, width in zip(blocks, (0, 19, 76, START_COLUMN), (4, 1, 1, 9)):
            for index, values in enumerate(block[:last-2], start=2):
                rows[index][first_col:first_col+width] = (list(values)+[""]*width)[:width]
        overlay(rows, pending)
        for number in targets:
            row = rows[number-1]
            if number < 3 or not eligible(row) or (has_lock(row) and not lock_matches(row)):
                raise ValueError("Invalid or changed first morning snapshot at row " + str(number))
        locks = build_lock_updates(rows, now, targets, FIRST_OBSERVATION)
        if len(locks) != sum(not has_lock(rows[number-1]) for number in targets):
            raise ValueError("Missing first-observation lock")
        print(f"MORNING TURNOVER LOCK OK | new={len(locks)} | atomic=True | version={VERSION}")
        return list(pending) + locks
    except Exception as exc:
        print("MORNING TURNOVER LOCK ERROR | morning_snapshot_withheld |", repr(exc))
        # Collector morning snapshots are explicit T:V writes. Refuse to write
        # a naked first T if its immutable classification could not be prepared.
        return [update for update in pending if not t_rows([update])]


def color_formula(hex_color, row=3):
    key = f'TO_TEXT($A{row})&"¦"&TO_TEXT($B{row})&"¦"&TO_TEXT($C{row})&"¦"&TO_TEXT($BY{row})'
    return (f'=AND(ISNUMBER($T{row});ISNUMBER($CI{row});$CO{row}=$T{row};'
            f'$CP{row}={key};$CJ{row}="{hex_color}")')
