"""Offline publication regressions, including the real entry engine and O formula."""

import copy
from datetime import timedelta
import unittest

import favorite_maroon_research as core
from favorite_maroon_live import (
    PROFILES, LABELS, PREFIX, base_formula, live_formula,
    refresh_live_alerts, retain_maroon_below_legacy_floor,
)
from side_goal_alerts import active_expr
from test_favorite_maroon_research import FakeLedger
from test_favorite_maroon80_research import Quotes, source_row
from test_parallel_alerts import ParallelFormula

NOW = PROFILES[2].start_at + timedelta(days=1)


def sources():
    row = source_row(f=1.60, g=1.55, money=85)
    row[76] = (NOW + timedelta(minutes=40)).isoformat()
    old = copy.deepcopy(row)
    old[1], old[10], old[76] = "Older Home", 100, (NOW - timedelta(days=1)).isoformat()
    row[14] = '=IF(AND(ISNUMBER($E3);$E3>=1,39);"🔔 ΦΑΒ 75+";"")'
    return [row, old]


class Ledger(FakeLedger):
    def __init__(self, profile):
        self.values = [[""] for _ in range(5)] + [profile.headers[:]]


class Book:
    def __init__(self):
        self.ledgers = {p.sheet_name: Ledger(p) for p in PROFILES}
        self.status = {p.name: "ACTIVE" for p in PROFILES}

    def worksheet(self, name):
        return self if name == "ALERT LEVELS" else self.ledgers[name]

    def get(self, *args, **kwargs):
        return [[p.name, "FAVORITE", 0, "🔔", self.status[p.name]] for p in PROFILES]


class Sheet(Quotes):
    def __init__(self, rows):
        super().__init__(rows)
        self.writes = []

    def batch_get(self, ranges, value_render_option):
        if value_render_option == "FORMULA":
            return [[[self.rows[int(address[1:])-3][14]]] for address in ranges]
        return super().batch_get(ranges, value_render_option)

    def batch_update(self, updates, value_input_option):
        assert value_input_option == "USER_ENTERED"
        self.writes.extend(copy.deepcopy(updates))
        for update in updates:
            self.rows[int(update["range"][1:])-3][14] = update["values"][0][0]


def evaluate(formula, row, active=None):
    active = {p.name for p in PROFILES} if active is None else active
    for profile in PROFILES:
        formula = formula.replace(active_expr(profile.name), "TRUE" if profile.name in active else "FALSE")
    return ParallelFormula(formula, {"A": row[0], "B": row[1], "C": row[2], "D": row[3],
                                    "E": row[4], "BY": row[76]}).result()


class LiveTests(unittest.TestCase):
    def publish(self, book, rows, sheet, fresh=(3,), now=NOW):
        for profile in PROFILES:
            core.update_research(book, rows, now, fresh_rows=fresh, first_row=3,
                                 quote_sheet=sheet, profile=profile)
        return refresh_live_alerts(book, sheet, rows, now, first_row=3)

    def test_real_fresh_observation_publishes_all_three_without_opening_floor(self):
        rows = sources(); book = Book(); sheet = Sheet(rows)
        result = self.publish(book, rows, sheet)
        self.assertEqual(result["active"], 3)
        self.assertEqual(result["visible"], 1)
        self.assertEqual(set(evaluate(rows[0][14], rows[0]).split(" | ")), LABELS)
        self.assertEqual(len(sheet.writes), 1)
        self.assertEqual(sheet.writes[0]["range"], "O3")
        for ledger in book.ledgers.values():
            self.assertEqual(len(ledger.values), 7)

    def test_existing_head_is_retained_and_each_new_pick_occurs_once(self):
        rows = sources(); rows[0][4] = 1.6
        formula = live_formula(rows[0][14], rows[0], 3, PROFILES)
        parts = evaluate(formula, rows[0]).split(" | ")
        self.assertEqual(parts[0], "🔔 ΦΑΒ 75+")
        self.assertEqual(set(parts[1:]), LABELS)
        self.assertEqual(len(parts), 4)

    def test_no_fresh_entry_means_no_public_backfill_even_if_final_values_qualify(self):
        rows = sources(); book = Book(); sheet = Sheet(rows)
        before = rows[0][14]
        result = self.publish(book, rows, sheet, fresh=())
        self.assertEqual(result["visible"], 0)
        self.assertEqual(rows[0][14], before)
        self.assertFalse(sheet.writes)

    def test_gamma_alone_publishes_with_missing_f_or_rising_odds(self):
        for f in (None, 1.30):
            rows = sources(); rows[0][5] = f
            book = Book(); sheet = Sheet(rows)
            self.publish(book, rows, sheet)
            self.assertEqual(evaluate(rows[0][14], rows[0]), "🔔 " + PROFILES[2].name)
            self.assertEqual(len(book.ledgers[PROFILES[0].sheet_name].values), 6)
            self.assertEqual(len(book.ledgers[PROFILES[1].sheet_name].values), 6)

    def test_repeat_or_withdrawal_does_not_duplicate_or_erase_issued_picks(self):
        rows = sources(); book = Book(); sheet = Sheet(rows)
        self.publish(book, rows, sheet)
        first = rows[0][14]
        frozen = {name: copy.deepcopy(ledger.values[6]) for name, ledger in book.ledgers.items()}
        self.publish(book, rows, sheet, now=NOW+timedelta(minutes=1))
        self.assertEqual(rows[0][14], first)
        self.assertEqual(len(sheet.writes), 1)
        rows[0][6], rows[0][10], rows[0][11] = 2.1, 0, 60
        self.publish(book, rows, sheet, now=NOW+timedelta(minutes=2))
        self.assertEqual(set(evaluate(rows[0][14], rows[0]).split(" | ")), LABELS)
        for name, ledger in book.ledgers.items():
            self.assertEqual(ledger.values[6][16], "ΕΦΥΓΕ")
            self.assertEqual(ledger.values[6][13], frozen[name][13])
            self.assertEqual(ledger.values[6][18:], frozen[name][18:])

    def test_config_disable_and_research_only_hide_the_named_pick(self):
        rows = sources(); formula = live_formula(rows[0][14], rows[0], 3, PROFILES)
        active = {PROFILES[0].name, PROFILES[2].name}
        self.assertEqual(set(evaluate(formula, rows[0], active).split(" | ")),
                         {"🔔 " + name for name in active})
        book = Book(); book.status = {p.name: "RESEARCH_ONLY" for p in PROFILES}
        sheet = Sheet(rows)
        self.assertEqual(self.publish(book, rows, sheet)["active"], 0)
        self.assertFalse(sheet.writes)

    def test_source_identity_guard_prevents_row_reuse_or_changed_original_side(self):
        rows = sources(); formula = live_formula('=""', rows[0], 3, PROFILES)
        for index, value in [(0,"Other league"), (1,"Another home"), (2,"Another away"),
                             (3,"A"), (76,(NOW+timedelta(days=1)).isoformat())]:
            changed = rows[0][:]; changed[index] = value
            self.assertEqual(evaluate(formula, changed), "")

    def test_completed_match_is_not_rewritten_as_a_historical_public_alert(self):
        rows = sources(); book = Book(); sheet = Sheet(rows)
        self.publish(book, rows, sheet)
        count = len(sheet.writes)
        refresh_live_alerts(book, sheet, rows, NOW+timedelta(minutes=50), first_row=3)
        self.assertEqual(len(sheet.writes), count)

    def test_below_floor_history_retains_only_three_approved_exact_identities(self):
        text = "🔔 ΦΑΒ 75+ | " + " | ".join(sorted(LABELS)) + " | 🔔 Over1.5"
        self.assertEqual(set(retain_maroon_below_legacy_floor(text, False).split(" | ")), LABELS)
        self.assertEqual(retain_maroon_below_legacy_floor(text, True), text)
        self.assertEqual(retain_maroon_below_legacy_floor("🔔 ΦΑΒΟΡΙ | 🔔 ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ fake", False), "")

    def test_unwrap_preserves_nested_formulas_and_escaped_literal_semicolons(self):
        row = sources()[0]
        for original in ['=IF(TRUE;"a;""b";"c")', '=LET(x;IF(TRUE;"a";"b");x)', 'literal "hello";']:
            first = live_formula(original, row, 3, PROFILES)
            second = live_formula(first, row, 3, PROFILES)
            self.assertEqual(first, second)
            self.assertEqual(first.count(PREFIX), 1)
            self.assertEqual(base_formula(first), base_formula(original))


if __name__ == "__main__":
    unittest.main()
