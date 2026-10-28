"""Freeze completed prematch K snapshots without changing live alert inputs."""

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
import json
import re
from statistics import fmean

from morning_turnover import ATHENS, COLORS, cell, numeric, color_for, coordinates

VERSION = "final-turnover-frozen-v1"
ACTIVATION = "FINAL_TURNOVER_LOCKS_V1"
START_COLUMN, END_COLUMN = 95, 104  # CR:CZ, separate from morning CI:CQ.
HISTORICAL = "HISTORICAL_FINAL_REFERENCE"
FINAL_OBSERVATION = "FINAL_OBSERVATION"
HEADERS = ["ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΚΑΤΑΤΑΞΗ", "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΧΡΩΜΑ",
           "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΚΛΕΙΔΩΜΑ", "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΔΕΙΓΜΑ",
           "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΜΕΣΟΣ ΟΡΟΣ", "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΠΡΟΕΛΕΥΣΗ",
           "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΑΡΧΙΚΟ K", "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΤΑΥΤΟΤΗΤΑ",
           "ΤΕΛΙΚΟΣ ΤΖΙΡΟΣ ΣΤΟΙΧΕΙΑ"]


def identity(row):
    return "¦".join(str(cell(row, i)) for i in (0, 1, 2, 76))


def eligible(row):
    return (all(str(cell(row, i)).strip() for i in (0, 1, 2))
            and numeric(cell(row, 10)) and cell(row, 10) >= 0)


def has_lock(row):
    return any(cell(row, i) != "" for i in range(START_COLUMN, END_COLUMN))


def locked_identity(row):
    return (numeric(cell(row, 95)) and 0 <= cell(row, 95) <= 100
            and cell(row, 96) == color_for(cell(row, 95))
            and numeric(cell(row, 101)) and cell(row, 101) >= 0
            and cell(row, 102) == identity(row))


def final_reason(row, now):
    value = str(cell(row, 76)).strip()
    kickoff = None
    if value:
        try:
            kickoff = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = None
        except ValueError:
            pass
    if kickoff is not None:
        return "KICKOFF_PASSED" if now >= kickoff else None
    if re.fullmatch(r"\s*\d+\s*[-–:]\s*\d+\s*", str(cell(row, 15))):
        return "SCORE_PRESENT"
    return None


def build_lock_updates(rows, now, mode=FINAL_OBSERVATION, historical_evidence=None):
    if now.tzinfo is None or mode not in (HISTORICAL, FINAL_OBSERVATION):
        raise ValueError("A timezone and a valid finalization mode are required")
    if historical_evidence and mode != HISTORICAL:
        raise ValueError("Archive evidence is permitted only in a historical rebuild")
    proof = historical_evidence or {}
    populations = defaultdict(list)
    candidates = []
    for number, row in enumerate(rows, start=1):
        if number < 3 or not all(str(cell(row, i)).strip() for i in (0, 1, 2)):
            continue
        if has_lock(row):
            if locked_identity(row):
                # Immutable snapshots, not later manual K edits, train new locks.
                populations[str(row[0])].append(row[101])
            continue
        if not eligible(row):
            continue
        reason = final_reason(row, now)
        archive = proof.get(identity(row))
        if (reason is None and archive and archive.get("K") == row[10]
                and archive.get("source")):
            reason = "ARCHIVED_K_SNAPSHOT"
        if reason is None:
            continue
        populations[str(row[0])].append(row[10])
        candidates.append((number, row, reason, archive))
    for values in populations.values():
        values.sort()
    stamp = now.astimezone(ATHENS).isoformat()
    updates = []
    for number, row, reason, archive in candidates:
        values, amount = populations[str(row[0])], row[10]
        rank = 100 * (bisect_right(values, amount) - 1) / max(1, len(values) - 1)
        color, mean = color_for(rank), fmean(values)
        evidence = {"version": VERSION, "classified_at": stamp, "mode": mode,
                    "first_finalized_at": stamp if mode == FINAL_OBSERVATION else None,
                    "quote_timestamp_known": False, "finalization_reason": reason,
                    "league": str(row[0]), "fixture_identity": identity(row),
                    "source_column": "K", "source_row": number, "K": amount,
                    "rank": rank, "color": color, "population": len(values),
                    "population_mean": mean, "population_min": values[0],
                    "population_max": values[-1], "reference_as_of": stamp,
                    "reference_order": "COMMON_FINAL_K_REFERENCE",
                    "scope": "available_final_prematch_K_same_exact_league",
                    "boundaries": [35, 75, 87], "immutable": True}
        if reason == "ARCHIVED_K_SNAPSHOT":
            evidence["historical_archival_evidence"] = archive
        record = [rank, color, stamp, len(values), mean, mode, amount,
                  identity(row), json.dumps(evidence, ensure_ascii=False, sort_keys=True)]
        updates.append({"range": f"CR{number}:CZ{number}", "values": [record]})
    return updates


def column_name(index):
    result = ""
    while index >= 0:
        index, remainder = divmod(index, 26)
        result = chr(65 + remainder) + result
        index -= 1
    return result


def overlay(rows, pending, include_k=True):
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
                relevant = col < 4 or col in (15, 76) or START_COLUMN <= col < END_COLUMN
                if include_k and 10 <= col <= 12:
                    relevant = True
                if col <= last_col and relevant:
                    rows[number-1][col] = value


def suppress_locked_k_writes(rows, pending):
    blocked = {i for i, row in enumerate(rows, start=1) if i >= 3 and locked_identity(row)}
    result = []
    for update in pending:
        area = coordinates(update)
        if area is None or area[0] > 12 or area[2] < 10 or not any(area[1] <= i <= area[3] for i in blocked):
            result.append(update)
            continue
        first_col, first_row, last_col, last_row = area
        for offset, values in enumerate(update.get("values", [])):
            number = first_row + offset
            if number > last_row:
                break
            segments, current = [], []
            for j, value in enumerate(values[:last_col-first_col+1]):
                col = first_col+j
                if number in blocked and 10 <= col <= 12:
                    if current:
                        segments.append(current)
                        current = []
                else:
                    current.append((col, value))
            if current:
                segments.append(current)
            for segment in segments:
                address = f"{column_name(segment[0][0])}{number}:{column_name(segment[-1][0])}{number}"
                result.append({**update, "range": address, "values": [[v for _,v in segment]]})
    return result


def attach_final_locks(sheet, source_rows, pending, now):
    # The marker is installed atomically with the native historical migration.
    if not source_rows or cell(source_rows[0], START_COLUMN) != ACTIVATION:
        print("FINAL TURNOVER LOCK SKIP | configuration_not_ready")
        return list(pending)
    try:
        last = max([len(source_rows), 3] + [a[3] for u in pending if (a := coordinates(u))])
        ranges = [f"A3:D{last}", f"K3:M{last}", f"BY3:BY{last}", f"CR3:CZ{last}"]
        blocks = sheet.batch_get(ranges, value_render_option="UNFORMATTED_VALUE")
        if len(blocks) != len(ranges):
            raise ValueError("Incomplete raw final-turnover response")
        rows = [[""] * END_COLUMN for _ in range(last)]
        for block, first_col, width in zip(blocks, (0, 10, 76, 95), (4, 3, 1, 9)):
            for index, values in enumerate(block[:last-2], start=2):
                rows[index][first_col:first_col+width] = (list(values)+[""]*width)[:width]
        # Scores must be displayed strings, never raw date serials from Sheets.
        for i, source in enumerate(source_rows[2:], start=2):
            rows[i][15] = cell(source, 15)
        overlay(rows, pending, include_k=False)
        filtered = suppress_locked_k_writes(rows, pending)
        overlay(rows, filtered)
        locks = build_lock_updates(rows, now)
        stale = [i for i,r in enumerate(rows,start=1) if i>=3 and has_lock(r) and not locked_identity(r)]
        if stale:
            print("FINAL TURNOVER LOCK REVIEW | stale_identity_rows=" + ",".join(map(str,stale)))
        print(f"FINAL TURNOVER LOCK OK | new={len(locks)} | version={VERSION}")
        return filtered + locks
    except Exception as exc:
        print("FINAL TURNOVER LOCK ERROR | finalization_deferred |", repr(exc))
        return list(pending)


def valid_lock_formula(row=3):
    key = f'TO_TEXT($A{row})&"¦"&TO_TEXT($B{row})&"¦"&TO_TEXT($C{row})&"¦"&TO_TEXT($BY{row})'
    colors = ";".join(f'$CS{row}="{c}"' for c in COLORS)
    return (f'AND(ISNUMBER($K{row});ISNUMBER($CR{row});$CX{row}=$K{row};'
            f'$CY{row}={key};OR({colors}))')


def color_formula(hex_color, row=3):
    return f'=AND({valid_lock_formula(row)};$CS{row}="{hex_color}")'
