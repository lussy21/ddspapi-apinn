"""Offline regressions for capture, immutable evidence and public coexistence."""

import copy
import json
import re
import unittest
from datetime import timedelta

import morning_favorite_live as morning
from favorite_maroon_live import (PROFILES as MAROON_PROFILES, base_formula, live_formula,
                                  refresh_live_alerts, retain_maroon_below_legacy_floor)
from morning_turnover import FIRST_OBSERVATION, build_lock_updates
from side_goal_alerts import active_expr
from test_parallel_alerts import ParallelFormula

NOW = morning.START_AT + timedelta(hours=12)


def source(profile=morning.PROFILES[0], share=85, price=1.15, minutes=360, side="H", home="Home"):
    row = [""] * 104
    row[:4] = [sorted(profile.leagues)[0], home, "Away", side]
    row[4], row[6], row[10], row[11] = 1.10, price, 3000, 25
    row[17], row[19], row[20] = "provider-1", 1000, share
    row[76] = (NOW + timedelta(minutes=minutes)).isoformat()
    ref = [""] * 104
    ref[:4] = [row[0], "Old", "Other", "H"]
    ref[19], ref[76] = 100, (NOW - timedelta(days=1)).isoformat()
    rows = [[], [], ref, row]
    update = build_lock_updates(rows, NOW - timedelta(minutes=10), {4}, FIRST_OBSERVATION)[0]
    values = update["values"][0]
    rank = {"#f6b16b": 50.0, "#e43935": 80.0, "#800000": 100.0}[profile.color]
    values[0], values[1] = rank, profile.color
    evidence = json.loads(values[8]); evidence.update(rank=rank, color=profile.color)
    values[8] = json.dumps(evidence)
    row[86:95] = values
    return row


class Ledger:
    row_count = 1006

    def __init__(self, headers):
        self.values = [[""] for _ in range(5)] + [headers[:]]
        self.writes = []

    def get_all_values(self, **kwargs):
        return copy.deepcopy(self.values)

    def batch_update(self, changes, value_input_option):
        assert value_input_option == "RAW"
        self.writes.extend(copy.deepcopy(changes))
        for change in changes:
            i = int(re.search(r"A(\d+)", change["range"])[1])
            while len(self.values) < i:
                self.values.append([])
            self.values[i - 1] = copy.deepcopy(change["values"][0])


class Book:
    def __init__(self):
        self.status = {p.name: "ACTIVE" for p in MAROON_PROFILES + morning.PROFILES}
        self.ledgers = {p.sheet_name: Ledger(p.headers) for p in MAROON_PROFILES + morning.PROFILES}

    def worksheet(self, name):
        return self if name == "ALERT LEVELS" else self.ledgers[name]

    def get(self, *args, **kwargs):
        return [[name, "FAVORITE", 0, "🔔", status] for name, status in self.status.items()]


def column(name):
    out = 0
    for ch in name:
        out = out * 26 + ord(ch) - 64
    return out - 1


class Sheet:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []
        self.reads = []

    def batch_get(self, ranges, value_render_option):
        self.reads.append((ranges[:], value_render_option))
        result = []
        for address in ranges:
            m = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", address)
            a, b = column(m[1]), column(m[3] or m[1])
            first, last = int(m[2]), int(m[4] or m[2])
            result.append([self.rows[i - 3][a:b + 1] for i in range(first, last + 1)])
        return copy.deepcopy(result)

    def get(self, address, **kwargs):
        return self.batch_get([address], kwargs["value_render_option"])[0]

    def batch_update(self, changes, value_input_option):
        assert value_input_option == "USER_ENTERED"
        self.writes.extend(copy.deepcopy(changes))
        for change in changes:
            self.rows[int(change["range"][1:]) - 3][14] = change["values"][0][0]


class BatchBook(Book):
    def __init__(self):
        super().__init__()
        self.metadata_reads = 0
        self.batch_reads = []
        for name, sheet in self.ledgers.items():
            sheet.title = name

    def worksheets(self):
        self.metadata_reads += 1
        return list(self.ledgers.values())

    def worksheet(self, name):
        raise AssertionError("Individual worksheet metadata lookup: " + name)

    def values_batch_get(self, ranges, params):
        assert params == {"valueRenderOption": "UNFORMATTED_VALUE"}
        self.batch_reads.append(ranges[:])
        out = []
        for address in ranges:
            if address == "'ALERT LEVELS'!A2:E100":
                vals = [[name, "FAVORITE", 0, "🔔", status] for name, status in self.status.items()]
            else:
                name = address.split("!", 1)[0][1:-1].replace("''", "'")
                vals = self.ledgers[name].values
            out.append({"range": address, "values": copy.deepcopy(vals)})
        return {"valueRanges": out}


def text(formula, row, active=None):
    active = set(p.name for p in MAROON_PROFILES + morning.PROFILES) if active is None else active
    for p in MAROON_PROFILES + morning.PROFILES:
        formula = formula.replace(active_expr(p.name), "TRUE" if p.name in active else "FALSE")
    return ParallelFormula(formula, {"A": row[0], "B": row[1], "C": row[2], "D": row[3],
                                    "E": row[4], "BY": row[76]}).result()


class MorningTests(unittest.TestCase):
    def test_production_batch_path_limits_reads_and_preserves_independent_openings(self):
        row = source(share=90); row[14] = '=""'
        book = BatchBook(); sheet = Sheet([row])
        morning.update_live(book, [row], NOW, {3}, first_row=3, quote_sheet=sheet)
        self.assertEqual((book.metadata_reads, len(book.batch_reads)), (1, 1))
        self.assertEqual(len(book.batch_reads[0]), 6)
        for p in (morning.PROFILES[0], morning.PROFILES[3]):
            self.assertEqual(len(book.ledgers[p.name].values), 7)
        refresh_live_alerts(book, sheet, [row], NOW, first_row=3, profiles=MAROON_PROFILES + morning.PROFILES)
        self.assertEqual((book.metadata_reads, len(book.batch_reads)), (2, 2))
        self.assertEqual(len(book.batch_reads[1]), 9)
        self.assertEqual(len(text(row[14], row).split(" | ")), 2)
        empty = BatchBook()
        result = morning.settle_results(empty, sheet, [row], NOW + timedelta(days=1))
        self.assertEqual(result["reason"], "no_pending_results")
        self.assertEqual((empty.metadata_reads, len(empty.batch_reads)), (1, 1))
        self.assertEqual(len(empty.batch_reads[0]), 5)

    def test_each_exact_color_and_league_scope_and_inclusive_money_threshold(self):
        for profile in morning.PROFILES:
            row = source(profile, share=profile.threshold)
            item = morning.fixture(row, 3, profile)
            self.assertTrue(morning.qualifies(item, profile, NOW))
            row[20] = profile.threshold - .00001
            self.assertFalse(morning.qualifies(morning.fixture(row, 3, profile), profile, NOW))
            row[0] = "USA - Major League Soccer"
            self.assertIsNone(morning.fixture(row, 3, profile))
        row = source(morning.PROFILES[2])
        self.assertFalse(morning.qualifies(morning.fixture(row, 3, morning.PROFILES[0]), morning.PROFILES[0], NOW))

    def test_only_first_morning_inputs_no_current_money_sofa_f90_or_odds_filter(self):
        row = source(share=80, price=3.5)
        row[4], row[5], row[10], row[11], row[13] = "", "", 1, 1, ""
        record = morning.advance_record(None, morning.fixture(row, 3, morning.PROFILES[0]), NOW, True)
        self.assertEqual(record[13], 3.5)
        self.assertEqual(record[10], 80)

    def test_fresh_first_capture_opens_before90_and_through5_but_never_after(self):
        for minutes, expected in [(360, True), (91, True), (90, True), (5, True), (4.99, False), (-1, False)]:
            row = source(minutes=minutes)
            record = morning.advance_record(None, morning.fixture(row, 3, morning.PROFILES[0]), NOW, True)
            self.assertEqual(record is not None, expected)
        item = morning.fixture(source(), 3, morning.PROFILES[0])
        self.assertIsNone(morning.advance_record(None, item, NOW, False))
        self.assertIsNone(morning.advance_record(None, item, morning.START_AT - timedelta(seconds=1), True))

    def test_no_retroactive_opening_for_old_kickoff_or_existing_score(self):
        for change in ["old", "score"]:
            row = source()
            if change == "old": row[76] = (morning.START_AT - timedelta(days=1)).isoformat()
            else: row[15] = "2-0"
            self.assertIsNone(morning.advance_record(None, morning.fixture(row, 3, morning.PROFILES[0]), NOW, True))

    def test_snapshot_validation_blocks_reuse_unfrozen_or_inconsistent_lock(self):
        original = source()
        for index, value in [(1, "Reused Home"), (19, 1001), (86, 90), (87, "#800000"), (94, "{}")]:
            row = original[:]; row[index] = value
            self.assertIsNone(morning.morning_snapshot(row))
        row = original[:]; row[20] = 101
        self.assertIsNone(morning.morning_snapshot(row))

    def test_90_also_records_80_independently_and_repeat_freezes_actual_entry(self):
        rows = [source(share=90)]; sheet = Sheet(rows); book = Book()
        result = morning.update_live(book, rows, NOW, {3}, first_row=3, quote_sheet=sheet)
        a, b = morning.PROFILES[0], morning.PROFILES[3]
        self.assertEqual(result["counted"][a.name], 1)
        self.assertEqual(result["counted"][b.name], 1)
        before = {p.name: copy.deepcopy(book.ledgers[p.name].values) for p in morning.PROFILES}
        rows[0][6], rows[0][10], rows[0][11] = 1.9, 100, 10
        morning.update_live(book, rows, NOW + timedelta(minutes=10), {3}, first_row=3, quote_sheet=sheet)
        for p in (a, b):
            old, new = before[p.name][6], book.ledgers[p.name].values[6]
            for index in (0, 6, 8, 10, 11, 12, 13, 18, 19, 20, 21):
                self.assertEqual(old[index], new[index])
            self.assertEqual(new[9], 1.9)

    def test_raw_values_prevent_rounded_90_false_positive_and_support_native_percent(self):
        row = source(share=89.99999); displayed = copy.deepcopy(row); displayed[20] = "90,0%"
        book = Book(); morning.update_live(book, [displayed], NOW, {3}, first_row=3, quote_sheet=Sheet([row]))
        self.assertEqual(len(book.ledgers[morning.PROFILES[0].name].values), 7)
        self.assertEqual(len(book.ledgers[morning.PROFILES[3].name].values), 6)
        row = source(share=.9); displayed = copy.deepcopy(row); displayed[20] = "90,0%"
        book = Book(); morning.update_live(book, [displayed], NOW, {3}, first_row=3, quote_sheet=Sheet([row]))
        self.assertEqual(book.ledgers[morning.PROFILES[3].name].values[6][10], 90)

    def test_missing_raw_data_or_concurrent_identity_change_has_no_partial_entries(self):
        row = source(); book = Book()
        class Incomplete(Sheet):
            def batch_get(self, *args, **kwargs): return []
        with self.assertRaises(ValueError):
            morning.update_live(book, [row], NOW, {3}, first_row=3, quote_sheet=Incomplete([row]))
        changed = copy.deepcopy(row); changed[1] = "Concurrent new home"
        with self.assertRaises(ValueError):
            morning.update_live(book, [row], NOW, {3}, first_row=3, quote_sheet=Sheet([changed]))
        self.assertTrue(all(len(x.values) == 6 for x in book.ledgers.values()))

    def test_settlement_frozen_favorite_entry_odds_and_draw_failure(self):
        for side, score, result, units in [("H", "2-0", "ΕΠΙΤΥΧΙΑ", .15),
                                            ("A", "0-1", "ΕΠΙΤΥΧΙΑ", .15),
                                            ("H", "1-1", "ΑΠΟΤΥΧΙΑ", -1)]:
            row = source(side=side, minutes=10)
            record = morning.advance_record(None, morning.fixture(row, 3, morning.PROFILES[0]), NOW, True)
            row[15], row[3], row[6] = score, "A" if side == "H" else "H", 9
            done = morning.advance_record(record, morning.fixture(row, 3, morning.PROFILES[0]), NOW + timedelta(minutes=11))
            self.assertEqual((done[15], done[17]), (result, units))

    def test_missing_score_stays_pending_and_settlement_cannot_create_old_entries(self):
        row = source(minutes=10); book = Book(); sheet = Sheet([row])
        morning.update_live(book, [row], NOW, {3}, first_row=3, quote_sheet=sheet)
        result = morning.settle_results(book, sheet, [row], NOW + timedelta(minutes=11))
        record = book.ledgers[morning.PROFILES[0].name].values[6]
        self.assertEqual(record[16], "ΑΝΑΜΟΝΗ ΣΚΟΡ")
        self.assertEqual(record[17], "")
        row[15] = "2-0"; empty = Book()
        morning.settle_results(empty, sheet, [row], NOW + timedelta(minutes=11))
        self.assertTrue(all(len(x.values) == 6 for x in empty.ledgers.values()))

    def test_disabled_profiles_fail_closed_and_no_raw_read_without_freshness(self):
        row = source(); book = Book()
        for p in morning.PROFILES: book.status[p.name] = "RESEARCH_ONLY"
        result = morning.update_live(book, [row], NOW, {3}, first_row=3)
        self.assertEqual(sum(result["counted"].values()), 0)
        book = Book(); result = morning.update_live(book, [row], NOW, first_row=3)
        self.assertEqual(sum(result["counted"].values()), 0)

    def test_public_join_includes_both_80_and90_and_retains_legacy_and_maroon(self):
        row = source(share=90); row[14] = '="🔔 ΦΑΒ 75+"'
        book = Book(); sheet = Sheet([row])
        morning.update_live(book, [row], NOW, {3}, first_row=3, quote_sheet=sheet)
        # Seed one real earlier-Maroon-style entry independently of the morning family.
        maroon = MAROON_PROFILES[2]
        from favorite_maroon_research import fixture as old_fixture
        old_item = old_fixture(row, 3, maroon)
        rec = [""] * len(maroon.headers); rec[0], rec[6], rec[18] = old_item["key"], NOW.isoformat(), json.dumps({"favorite_side": "H"})
        book.ledgers[maroon.name].values.append(rec)
        profiles = MAROON_PROFILES + morning.PROFILES
        result = refresh_live_alerts(book, sheet, [row], NOW, first_row=3, profiles=profiles)
        self.assertEqual(result["active"], 8)
        parts = text(row[14], row).split(" | ")
        self.assertEqual(parts, ["🔔 ΦΑΒ 75+", "🔔 " + maroon.name,
                                 "🔔 " + morning.PROFILES[0].name, "🔔 " + morning.PROFILES[3].name])
        first_formula = row[14]
        refresh_live_alerts(book, sheet, [row], NOW, first_row=3, profiles=profiles)
        self.assertEqual(row[14], first_formula)
        self.assertEqual(base_formula(row[14]), '="🔔 ΦΑΒ 75+"')

    def test_public_status_gate_identity_guard_and_legacy_floor_exemption(self):
        row = source(); profile = morning.PROFILES[0]
        formula = live_formula('=""', row, 3, (profile,))
        self.assertEqual(text(formula, row), "🔔 " + profile.name)
        self.assertEqual(text(formula, row, set()), "")
        changed = row[:]; changed[1] = "Reused row"
        self.assertEqual(text(formula, changed), "")
        label = "🔔 " + profile.name
        self.assertEqual(retain_maroon_below_legacy_floor("🔔 ΦΑΒ 75+ | " + label, False), label)

    def test_review_preserves_prospective_counters(self):
        from alert_level_review import run_level_review_if_due
        class Levels:
            def get(self, *args, **kwargs):
                return [["ALERT"] * 20] + [[p.name, "FAVORITE", 0, "🔔", "ACTIVE"] + [""] * 15
                                          for p in morning.PROFILES]
            def update(self, *args, **kwargs):
                raise AssertionError("Prospective counters overwritten")
        class Pinnacle:
            def get(self, *args, **kwargs): return []
        class ReviewBook:
            def worksheet(self, name): return Levels() if name == "ALERT LEVELS" else Pinnacle()
        self.assertTrue(run_level_review_if_due(ReviewBook(), force=True)["ok"])


if __name__ == "__main__":
    unittest.main()
