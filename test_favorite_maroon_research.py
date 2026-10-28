import copy
import json
import unittest
from datetime import timedelta

from favorite_maroon_research import (
    ALERT_NAME, BIG_LEAGUES, HEADERS, SHEET_NAME, START_AT, advance_record,
    fixture, qualifies, result_for, settle_results, turnover_ranks, update_research,
)

NOW = START_AT + timedelta(days=1)


def source_row(minutes=40, side="H", f=2.0, g=1.96, k=1000,
               league="England - Premier League", home="Home"):
    row = [""] * 86
    row[:4] = [league, home, "Away", side]
    row[4], row[5], row[6], row[10], row[17] = 1.10, f, g, k, "provider-1"
    row[76] = (NOW + timedelta(minutes=minutes)).isoformat()
    return row


def item(row=None, index=3, rank=100):
    value = fixture(row or source_row(), index)
    if value:
        value.update(rank=rank, population=20)
    return value


class RuleTests(unittest.TestCase):
    def test_exact_relative_drop_and_color_boundaries(self):
        self.assertTrue(qualifies(2,1.96,100))
        self.assertTrue(qualifies(1.5,1.47,100))
        self.assertFalse(qualifies(2,1.96001,100))
        self.assertFalse(qualifies(2,1.96,87))
        self.assertTrue(qualifies(2,1.96,87.00001))
        for args in [(None,2,100),(2,None,100),(2,1.9,None),(1,0.98,100),
                     (2,float("nan"),100),(2,1.9,float("inf"))]:
            self.assertFalse(qualifies(*args))

    def test_only_big_leagues_and_no_money_sofa_opening_floor_or_side_filter(self):
        for league in BIG_LEAGUES:
            for side in ["H","A"]:
                record=advance_record(None,item(source_row(league=league,side=side)),NOW,True)
                self.assertTrue(record[6])  # E=1.10, L/N absent: no extra condition.
        for league in ["Netherlands - Eredivisie","Belgium - Pro League", "USA - Major League Soccer",
                       "Germany - Bundesliga 2","UEFA - Conference League","Unknown"]:
            self.assertIsNone(fixture(source_row(league=league),3))

    def test_first_fresh_observation_in_inclusive_90_to5_window(self):
        for minutes in [5,30,89,90]:
            self.assertTrue(advance_record(None,item(source_row(minutes=minutes)),NOW,True)[6])
        for minutes in [4.99,90.01,-1]:
            self.assertIsNone(advance_record(None,item(source_row(minutes=minutes)),NOW,True))
        self.assertIsNone(advance_record(None,item(),NOW,False))

    def test_launch_and_no_clock_hour_filter(self):
        self.assertIsNone(advance_record(None,item(),START_AT-timedelta(seconds=1),True))
        old=source_row();old[76]=(START_AT-timedelta(days=1)).isoformat()
        self.assertIsNone(advance_record(None,item(old),NOW,True))
        for hour in [12,22]:
            now=NOW.replace(hour=hour);row=source_row()
            row[76]=(now+timedelta(minutes=20)).isoformat()
            self.assertTrue(advance_record(None,item(row),now,True)[6])

    def test_first_entry_price_color_and_evidence_survive_signal_disappearing(self):
        first=advance_record(None,item(),NOW,True)
        later=item(source_row(g=2.1,k=100),rank=10)
        off=advance_record(first,later,NOW+timedelta(minutes=5),True)
        self.assertEqual(off[16],"ΕΦΥΓΕ")
        for index in [6,8,10,11,12,13,18,19]:self.assertEqual(off[index],first[index])
        self.assertEqual(off[9],2.1)

    def test_changed_reference_or_original_side_cannot_rewrite_entry(self):
        first=advance_record(None,item(),NOW,True)
        for changed,message in [(item(source_row(f=2.1)),"ΕΛΕΓΧΟΣ ΣΤΙΓΜΙΟΤΥΠΟΥ −90′"),
                                (item(source_row(side="A")),"ΕΛΕΓΧΟΣ ΑΡΧΙΚΗΣ ΠΛΕΥΡΑΣ")]:
            checked=advance_record(first,changed,NOW+timedelta(minutes=1),True)
            self.assertEqual(checked[16],message)
            self.assertEqual(checked[13],first[13])
            self.assertEqual(checked[18],first[18])

    def test_results_use_frozen_original_favorite_and_draw_is_failure(self):
        for side,score,expected in [("H","2-0",True),("H","0-0",False),
                                    ("A","1-3",True),("A","2-1",False)]:
            row=source_row(side=side);first=advance_record(None,item(row),NOW,True)
            row[3]="A" if side=="H" else "H";row[15]=score
            done=advance_record(first,item(row),NOW+timedelta(minutes=45))
            self.assertEqual(done[15],"ΕΠΙΤΥΧΙΑ" if expected else "ΑΠΟΤΥΧΙΑ")
            self.assertEqual(done[17],.96 if expected else -1)
        self.assertIsNone(result_for("", "H"))

    def test_unknown_score_stays_pending_without_loss(self):
        first=advance_record(None,item(),NOW,True)
        pending=advance_record(first,item(),NOW+timedelta(minutes=45))
        self.assertEqual(pending[16],"ΑΝΑΜΟΝΗ ΣΚΟΡ")
        self.assertEqual(pending[15:16],[""])
        self.assertEqual(pending[17],"")

    def test_row_and_provider_changes_do_not_duplicate_fixture(self):
        row=source_row();original=fixture(row,3)
        row[17]="new-provider"
        self.assertEqual(original["key"],fixture(row,25)["key"])
        row[1]="Different Home"
        self.assertNotEqual(original["key"],fixture(row,25)["key"])


class ColorTests(unittest.TestCase):
    def test_same_league_rank_with_ties_missing_and_zero(self):
        leagues=[["L"],["L"],["L"],["Other"],["L"],["L"]]
        ranks=turnover_ranks(leagues,[[0],[100],[100],[999999],[],[-5]])
        self.assertEqual(ranks[3]["rank"],0)
        self.assertEqual(ranks[4]["rank"],100)
        self.assertEqual(ranks[5]["rank"],100)
        self.assertEqual(ranks[4]["population"],3)
        self.assertEqual(ranks[6]["rank"],0)
        self.assertNotIn(7,ranks)
        self.assertNotIn(8,ranks)


class FakeLedger:
    row_count=1000
    def __init__(self):self.values=[[""] for _ in range(5)]+[HEADERS[:]]
    def get_all_values(self,**kwargs):
        assert kwargs.get("value_render_option")=="UNFORMATTED_VALUE"
        return copy.deepcopy(self.values)
    def batch_update(self,changes,value_input_option):
        assert value_input_option=="RAW"
        for change in changes:
            row=int(change["range"].split(":")[0][1:])
            while len(self.values)<row:self.values.append([])
            self.values[row-1]=copy.deepcopy(change["values"][0])


class FakeLevels:
    def __init__(self,status="RESEARCH_ONLY"):self.status=status
    def get(self,*args,**kwargs):return [[ALERT_NAME,"FAVORITE",0,"🧪",self.status]]


class FakeBook:
    def __init__(self,status="RESEARCH_ONLY"):
        self.ledger=FakeLedger();self.levels=FakeLevels(status)
    def worksheet(self,name):
        if name==SHEET_NAME:return self.ledger
        if name=="ALERT LEVELS":return self.levels
        raise ValueError(name)


class FakeQuotes:
    def __init__(self,rows,overrides=None):self.rows=rows;self.overrides=overrides or {}
    def batch_get(self,ranges,value_render_option):
        assert value_render_option=="UNFORMATTED_VALUE"
        output=[]
        for address in ranges:
            if address.startswith("A3:A"):output.append([[r[0]] for r in self.rows])
            elif address.startswith("K3:K"):output.append([[r[10]] for r in self.rows])
            else:
                index=int(address.split(":")[0][1:]);r=self.rows[index-3]
                output.append([self.overrides.get(index,[r[5],r[6]])])
        return output


def population():
    old=source_row(minutes=-2000,home="Older Home",k=100)
    return [source_row(),old]


class PersistenceTests(unittest.TestCase):
    def test_repeat_keeps_first_quote_and_new_fixture_does_not_overwrite_it(self):
        book=FakeBook();rows=population()
        update_research(book,rows,NOW,{3},first_row=3,quote_sheet=FakeQuotes(rows))
        first=copy.deepcopy(book.ledger.values[6])
        rows.append(source_row(home="Second Home"))
        result=update_research(book,rows,NOW+timedelta(minutes=1),{3,5},first_row=3,quote_sheet=FakeQuotes(rows))
        self.assertEqual(result["counted"],2)
        self.assertEqual(len(book.ledger.values),8)
        for index in [0,6,8,10,11,12,13,18,19]:
            self.assertEqual(book.ledger.values[6][index],first[index])
        self.assertNotEqual(book.ledger.values[6][0],book.ledger.values[7][0])

    def test_exact_source_quotes_reject_rounded_false_positive(self):
        rows=population();rows[0][6]=1.96;book=FakeBook()
        result=update_research(book,rows,NOW,{3},first_row=3,
                               quote_sheet=FakeQuotes(rows,{3:[2.0,1.96001]}))
        self.assertEqual(result["counted"],0)

    def test_live_turnover_rerank_does_not_change_frozen_entry(self):
        book=FakeBook();rows=population()
        update_research(book,rows,NOW,{3},first_row=3,quote_sheet=FakeQuotes(rows))
        frozen=book.ledger.values[6][11:14]
        rows[1][10]=2000
        update_research(book,rows,NOW+timedelta(minutes=1),{3},first_row=3,quote_sheet=FakeQuotes(rows))
        self.assertEqual(book.ledger.values[6][11:14],frozen)
        self.assertEqual(book.ledger.values[6][16],"ΕΦΥΓΕ")

    def test_settlement_only_does_not_backfill_historical_entries(self):
        book=FakeBook();result=update_research(book,population(),NOW,first_row=3)
        self.assertEqual(result["counted"],0)
        self.assertEqual(len(book.ledger.values),6)

    def test_disabled_rule_does_not_read_quotes_or_create_entries(self):
        result=update_research(FakeBook("OFF"),population(),NOW,{3},first_row=3)
        self.assertEqual(result["counted"],0)

    def test_missing_raw_quote_sheet_and_incomplete_response_fail_without_writes(self):
        book=FakeBook()
        with self.assertRaises(ValueError):update_research(book,population(),NOW,{3},first_row=3)
        class Incomplete:
            def batch_get(self,*args,**kwargs):return []
        with self.assertRaises(ValueError):update_research(book,population(),NOW,{3},first_row=3,quote_sheet=Incomplete())
        self.assertEqual(len(book.ledger.values),6)

    def test_duplicate_identity_is_rejected(self):
        book=FakeBook();rows=population()
        update_research(book,rows,NOW,{3},first_row=3,quote_sheet=FakeQuotes(rows))
        book.ledger.values.append(copy.deepcopy(book.ledger.values[6]))
        with self.assertRaises(ValueError):update_research(book,rows,NOW,first_row=3)

    def test_post_sofa_result_enriches_kickoff_and_uses_entry_price(self):
        book=FakeBook();rows=population()
        update_research(book,rows,NOW,{3},first_row=3,quote_sheet=FakeQuotes(rows))
        rows[0][15]="2-0";rows[0][6]=1.2
        class Source:
            def get(self,address,value_render_option):return [[r[76]] for r in rows]
        settle_results(book,Source(),[r[:57] for r in rows],NOW+timedelta(minutes=45))
        self.assertEqual(book.ledger.values[6][15],"ΕΠΙΤΥΧΙΑ")
        self.assertEqual(book.ledger.values[6][17],.96)

    def test_no_pending_results_avoids_source_reads(self):
        class Source:
            def get(self,*args,**kwargs):raise AssertionError("Unneeded source read")
        self.assertTrue(settle_results(FakeBook(),Source(),[source_row()[:57]],NOW)["ok"])

    def test_level_review_preserves_prospective_counters(self):
        from alert_level_review import run_level_review_if_due
        class Levels:
            def get(self,*args,**kwargs):
                return [["ALERT"]*20,[ALERT_NAME,"FAVORITE",0,"🧪","RESEARCH_ONLY"]+[""]*15]
            def update(self,*args,**kwargs):raise AssertionError("Ledger counters overwritten")
        class Source:
            def get(self,*args,**kwargs):return []
        class Book:
            def worksheet(self,name):return Levels() if name=="ALERT LEVELS" else Source()
        self.assertTrue(run_level_review_if_due(Book(),force=True)["ok"])


if __name__=="__main__":unittest.main()
