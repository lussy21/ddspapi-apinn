import copy
import json
import unittest
from datetime import timedelta

from contra_rise_research import (
    ALERT_NAME, HEADERS, SHEET_NAME, START_AT, advance_record, category,
    fixture, fresh_quote_rows, qualifies, result_for, settle_results, update_research,
)


NOW = START_AT + timedelta(days=1)


def source_row(minutes=20, side="H", f=1.5, g=1.65, price=2.2, league="England - Premier League"):
    row = [""] * 86
    row[:4] = [league, "Home", "Away", side]
    row[4], row[5], row[6], row[9], row[17] = 1.1, f, g, price, "provider-1"
    row[76] = (NOW + timedelta(minutes=minutes)).isoformat()
    return row


class RuleTests(unittest.TestCase):
    def observe(self, row=None, now=NOW, old=None, fresh=True, index=1203):
        return advance_record(old, fixture(row or source_row(), index), now, fresh=fresh)

    def test_exact_relative_boundary_and_no_extra_money_sofa_or_opening_floor(self):
        self.assertTrue(qualifies(1.5, 1.65))
        self.assertFalse(qualifies(1.5, 1.6499))
        self.assertFalse(qualifies(2.0, 2.10))
        self.assertTrue(self.observe()[12])  # E=1.10; no turnover/Sofa values.
        for f, g in [(None, 2), (1, 2), (0, 2), (2, None), (float("nan"), 3), (2, float("inf"))]:
            self.assertFalse(qualifies(f, g))

    def test_exact_scopes_and_no_clock_hour_filter(self):
        for league in ["USA - Major League Soccer", "ΕΘΝΙΚΕΣ - UEFA - Nations League A", "Germany - Bundesliga 2", "Unknown"]:
            self.assertEqual(category(league), "")
            self.assertIsNone(fixture(source_row(league=league), 1203))
        for hour in [12, 22]:
            stamp = NOW.replace(hour=hour)
            row = source_row(); row[76] = (stamp + timedelta(minutes=20)).isoformat()
            self.assertTrue(self.observe(row, now=stamp)[12])

    def test_early_observation_counts_only_when_still_qualifying_in_window(self):
        row = source_row(minutes=80)
        early = self.observe(row)
        self.assertFalse(early[12])
        counted = self.observe(row, now=NOW + timedelta(minutes=55), old=early)
        self.assertTrue(counted[12])
        self.assertEqual(json.loads(counted[18])["minutes_before"], 25)

    def test_early_signal_that_disappears_before_window_is_not_a_pick(self):
        row = source_row(minutes=80); early = self.observe(row)
        row[6] = 1.6
        off = self.observe(row, now=NOW + timedelta(minutes=55), old=early)
        self.assertFalse(off[12])

    def test_entry_never_disappears_or_changes_price_when_signal_leaves(self):
        row = source_row(); counted = self.observe(row)
        row[6], row[9] = 1.4, 3.0
        off = self.observe(row, now=NOW + timedelta(minutes=5), old=counted)
        self.assertEqual(off[12:14], counted[12:14])
        self.assertEqual(off[18], counted[18])
        self.assertEqual(off[16], "ΕΦΥΓΕ")

    def test_inclusive_five_and_thirty_minute_boundaries(self):
        self.assertTrue(self.observe(source_row(minutes=5))[12])
        self.assertTrue(self.observe(source_row(minutes=30))[12])
        self.assertFalse(self.observe(source_row(minutes=30.01))[12])
        self.assertIsNone(self.observe(source_row(minutes=4.99)))

    def test_no_stale_or_postmatch_backfill_and_launch_cutoff(self):
        self.assertIsNone(self.observe(fresh=False))
        self.assertIsNone(self.observe(source_row(minutes=-1)))
        old_row = source_row(); old_row[76] = (START_AT - timedelta(days=1)).isoformat()
        self.assertIsNone(self.observe(old_row))

    def test_provider_change_and_row_move_keep_one_fixture(self):
        row = source_row(); first = fixture(row, 1203)
        row[17] = "provider-2"; moved = fixture(row, 1210)
        self.assertEqual(first["key"], moved["key"])
        row[1] = "Another Home"
        self.assertNotEqual(first["key"], fixture(row, 1203)["key"])

    def test_changed_90_baseline_cannot_create_a_new_pick(self):
        row=source_row(minutes=80);early=self.observe(row)
        row[5]=1.4
        checked=self.observe(row,now=NOW+timedelta(minutes=55),old=early)
        self.assertFalse(checked[12])
        self.assertEqual(checked[16],"ΕΛΕΓΧΟΣ ΣΤΙΓΜΙΟΤΥΠΟΥ −90′")

    def test_draw_and_both_favorite_sides_settle_correctly(self):
        for side, score, expected in [("H", "0-0", True), ("A", "0-0", True), ("H", "3-0", False), ("A", "3-0", True)]:
            row = source_row(side=side); counted = self.observe(row)
            row[15] = score
            done = self.observe(row, now=NOW + timedelta(minutes=25), old=counted, fresh=False)
            self.assertEqual(done[15], "ΕΠΙΤΥΧΙΑ" if expected else "ΑΠΟΤΥΧΙΑ")
            self.assertEqual(done[17], 1.2 if expected else -1)
        self.assertIsNone(result_for("", "H"))

    def test_original_side_is_used_even_if_source_side_changes_after_entry(self):
        row = source_row(side="A"); counted = self.observe(row)
        row[3], row[15] = "H", "3-0"
        done = self.observe(row, now=NOW + timedelta(minutes=25), old=counted, fresh=False)
        self.assertEqual(done[15], "ΕΠΙΤΥΧΙΑ")

    def test_missing_entry_odds_or_result_are_not_invented(self):
        row = source_row(price=""); counted = self.observe(row)
        pending = self.observe(row, now=NOW + timedelta(minutes=25), old=counted, fresh=False)
        self.assertEqual(pending[16], "ΑΝΑΜΟΝΗ ΣΚΟΡ")
        row[15] = "0-0"
        done = self.observe(row, now=NOW + timedelta(minutes=26), old=pending, fresh=False)
        self.assertEqual(done[15], "ΕΠΙΤΥΧΙΑ")
        self.assertEqual(done[17], "")

    def test_freshness_accepts_only_numeric_g_writes(self):
        updates = [{"range": "G1203", "values": [[1.9]]}, {"range":"K1204:M1204","values":[[100,80,20]]},
                   {"range":"G1205","values":[["=1+1"]]}, {"range":"G1206:G1207","values":[[1.8],[1.9]]}]
        self.assertEqual(fresh_quote_rows(updates), {1203,1206,1207})


class FakeLedger:
    row_count = 1000
    def __init__(self):
        self.values = [[""] for _ in range(5)] + [HEADERS[:]]
    def get_all_values(self):
        return copy.deepcopy(self.values)
    def batch_update(self, changes, value_input_option):
        assert value_input_option == "RAW"
        for change in changes:
            n = int(change["range"].split(":")[0][1:])
            while len(self.values) < n:self.values.append([])
            self.values[n-1] = copy.deepcopy(change["values"][0])


class FakeLevels:
    def get(self, *args, **kwargs):
        return [[ALERT_NAME,"CONTRA",0,"🧪","RESEARCH_ONLY"]]


class FakeSpreadsheet:
    def __init__(self):self.ledger=FakeLedger()
    def worksheet(self, name):
        if name==SHEET_NAME:return self.ledger
        if name=="ALERT LEVELS":return FakeLevels()
        raise ValueError(name)


class FakeQuotes:
    def __init__(self, f=1.5,g=1.65):self.f,self.g=f,g
    def batch_get(self, ranges, value_render_option):
        assert value_render_option=="UNFORMATTED_VALUE"
        return [[[self.f,self.g,"","",2.2]] for _ in ranges]


class PersistenceTests(unittest.TestCase):
    def test_no_pending_results_does_not_read_unneeded_kickoff_column(self):
        class NoRead:
            def get(self,*args,**kwargs):raise AssertionError("Unneeded Pinnacle read")
        self.assertTrue(settle_results(FakeSpreadsheet(),NoRead(),[source_row()[:57]],NOW)["ok"])

    def test_post_sofa_settlement_enriches_legacy_history_without_kickoff(self):
        book=FakeSpreadsheet();row=source_row()
        update_research(book,[row],NOW,{3},first_row=3,quote_sheet=FakeQuotes())
        row[15]="0-0"
        class HistorySheet:
            def get(self,address,value_render_option):
                self.address=address
                return [[row[76]]]
        sheet=HistorySheet()
        settle_results(book,sheet,[row[:57]],NOW+timedelta(minutes=25))
        self.assertEqual(sheet.address,"BY3:BY3")
        self.assertEqual(book.ledger.values[6][15],"ΕΠΙΤΥΧΙΑ")

    def test_repeated_collector_then_result_stage_count_once_and_keep_entry(self):
        book=FakeSpreadsheet();row=source_row();quotes=FakeQuotes()
        update_research(book,[row],NOW,{1203},first_row=1203,quote_sheet=quotes)
        update_research(book,[row],NOW+timedelta(minutes=1),{1203},first_row=1203,quote_sheet=quotes)
        self.assertEqual(len(book.ledger.values),7)
        entry=book.ledger.values[6][12]
        row[15]="0-0"
        update_research(book,[row],NOW+timedelta(minutes=25),first_row=1203)
        self.assertEqual(book.ledger.values[6][12],entry)
        self.assertEqual(book.ledger.values[6][15],"ΕΠΙΤΥΧΙΑ")

    def test_source_precision_prevents_rounded_false_positive(self):
        book=FakeSpreadsheet();row=source_row(f=1.625,g=1.788)
        # Display rounds true G=1.7874 into apparent >=10%.
        update_research(book,[row],NOW,{1203},first_row=1203,quote_sheet=FakeQuotes(1.625,1.7874))
        self.assertEqual(len(book.ledger.values),6)


class ReviewOwnershipTests(unittest.TestCase):
    def test_level_review_does_not_replace_ledger_owned_metrics(self):
        from alert_level_review import run_level_review_if_due
        class Levels:
            def get(self,*args,**kwargs):
                row=[ALERT_NAME,"CONTRA",0,"🧪","RESEARCH_ONLY"]+[""]*15
                return [["ALERT"]*20,row]
            def update(self,*args,**kwargs):
                raise AssertionError("Dedicated metrics were overwritten")
        class Pin:
            def get(self,*args,**kwargs):return []
        class Book:
            def worksheet(self,name):return Levels() if name=="ALERT LEVELS" else Pin()
        self.assertTrue(run_level_review_if_due(Book(),force=True)["ok"])

    def test_settlement_only_pass_cannot_create_from_historical_prices(self):
        book=FakeSpreadsheet()
        r=update_research(book,[source_row()],NOW,first_row=1203)
        self.assertEqual(r["counted"],0)
        self.assertEqual(len(book.ledger.values),6)


if __name__ == "__main__":unittest.main()
