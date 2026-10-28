import copy
import json
import unittest
from datetime import timedelta

import favorite_maroon_research as a
import favorite_maroon80_research as b
import favorite_maroon170_research as c
from contra_rise_research import BIG_LEAGUES, OTHER_LEAGUES
from test_favorite_maroon80_research import Ledger, Quotes, source_row as b_source_row

NOW=c.START_AT+timedelta(days=1)


def source_row(minutes=40,money=85,f=None,g=1.60,**kwargs):
    row=b_source_row(minutes=minutes,money=money,f=f,g=g,**kwargs)
    row[76]=(NOW+timedelta(minutes=minutes)).isoformat()
    return row


def item(row=None):
    value=c.fixture(row or source_row(),3)
    if value:value.update(rank=100,population=20)
    return value


def population():
    return [source_row(),source_row(minutes=-2000,k=100,home="Older Home")]


class Levels:
    def __init__(self,status="RESEARCH_ONLY"):self.status=status
    def get(self,*args,**kwargs):
        return [[c.ALERT_NAME,"FAVORITE",0,"🧪",self.status],
                [b.ALERT_NAME,"FAVORITE",0,"🧪","RESEARCH_ONLY"],
                [a.ALERT_NAME,"FAVORITE",0,"🧪","RESEARCH_ONLY"]]


class Book:
    def __init__(self,status="RESEARCH_ONLY"):
        self.ledger=Ledger(c.HEADERS);self.b_ledger=Ledger(b.HEADERS)
        self.a_ledger=Ledger(a.HEADERS);self.levels=Levels(status)
    def worksheet(self,name):
        if name==c.SHEET_NAME:return self.ledger
        if name==b.SHEET_NAME:return self.b_ledger
        if name==a.SHEET_NAME:return self.a_ledger
        if name=="ALERT LEVELS":return self.levels
        raise ValueError(name)


class VariantCRuleTests(unittest.TestCase):
    def test_exact_price_money_and_color_boundaries(self):
        self.assertTrue(c.qualifies(None,1.70,100,80))
        self.assertFalse(c.qualifies(None,1.70001,100,80))
        self.assertFalse(c.qualifies(None,1.6,100,79.999))
        self.assertFalse(c.qualifies(None,1.6,87,90))
        for g in [None,1,float("nan"),float("inf")]:self.assertFalse(c.qualifies(None,g,100,90))

    def test_missing_90_snapshot_and_rising_price_are_allowed_only_for_c(self):
        self.assertTrue(c.qualifies(None,1.60,100,85))
        self.assertTrue(c.qualifies(1.30,1.60,100,85))
        self.assertFalse(b.qualifies(1.30,1.60,100,85))
        self.assertFalse(b.qualifies(None,1.60,100,85))
        self.assertFalse(a.qualifies(None,1.60,100,85))
        self.assertEqual(a.HEADERS[10],"ΠΤΩΣΗ ΣΤΗΝ ΕΙΣΟΔΟ")
        self.assertEqual(b.HEADERS[10],"ΠΤΩΣΗ ΣΤΗΝ ΕΙΣΟΔΟ")
        self.assertNotEqual(c.HEADERS[10],a.HEADERS[10])

    def test_scope_and_no_opening_sofa_or_home_away_restriction(self):
        for league in BIG_LEAGUES|OTHER_LEAGUES:
            for side in ["H","A"]:
                record=c.advance_record(None,item(source_row(league=league,side=side)),NOW,True)
                self.assertTrue(record[6])
        for league in ["USA - Major League Soccer","Germany - Bundesliga 2","Unknown"]:
            self.assertIsNone(c.fixture(source_row(league=league),3))

    def test_first_fresh_observation_in_inclusive_window_and_launch_gate(self):
        for minutes in [5,90]:self.assertTrue(c.advance_record(None,item(source_row(minutes=minutes)),NOW,True)[6])
        for minutes in [4.99,90.01,-1]:self.assertIsNone(c.advance_record(None,item(source_row(minutes=minutes)),NOW,True))
        self.assertIsNone(c.advance_record(None,item(),NOW,False))
        self.assertIsNone(c.advance_record(None,item(),c.START_AT-timedelta(seconds=1),True))

    def test_missing_optional_f_does_not_divide_or_invent_movement(self):
        record=c.advance_record(None,item(),NOW,True)
        self.assertEqual(record[8],"")
        self.assertEqual(record[10],"")
        self.assertEqual(record[13],1.6)
        details=json.loads(record[18])
        self.assertIsNone(details["F"])
        self.assertEqual(details["max_price"],1.70)
        self.assertFalse(details["comparison_to_F"])

    def test_f_appearing_later_does_not_block_or_rewrite_entry(self):
        first=c.advance_record(None,item(),NOW,True)
        later=c.advance_record(first,item(source_row(f=1.5,g=1.65)),NOW+timedelta(minutes=1),True)
        self.assertEqual(later[16],"ΕΝΕΡΓΟ")
        self.assertEqual(later[8],"")
        self.assertEqual(later[13],1.6)
        self.assertEqual(later[18],first[18])

    def test_departure_keeps_frozen_color_money_price_and_timestamp(self):
        first=c.advance_record(None,item(),NOW,True)
        changed=item(source_row(g=1.8,money=50,k=100));changed["rank"]=10
        off=c.advance_record(first,changed,NOW+timedelta(minutes=2),True)
        self.assertEqual(off[16],"ΕΦΥΓΕ")
        for index in [6,8,10,11,12,13,18,19,20,21]:self.assertEqual(off[index],first[index])

    def test_original_side_and_entry_price_settle_with_draw_as_failure(self):
        for side,score,won in [("H","2-0",True),("H","0-0",False),("A","1-3",True)]:
            row=source_row(side=side);first=c.advance_record(None,item(row),NOW,True)
            row[3]="A" if side=="H" else "H";row[15]=score;row[6]=1.1
            done=c.advance_record(first,item(row),NOW+timedelta(minutes=45))
            self.assertEqual(done[15],"ΕΠΙΤΥΧΙΑ" if won else "ΑΠΟΤΥΧΙΑ")
            self.assertEqual(done[17],.6 if won else -1)


class VariantCPersistenceTests(unittest.TestCase):
    def test_fresh_source_without_f_records_and_repeated_reads_keep_one_entry(self):
        book=Book();rows=population()
        c.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows))
        first=copy.deepcopy(book.ledger.values[6])
        c.update_research(book,rows,NOW+timedelta(minutes=1),{3},first_row=3,quote_sheet=Quotes(rows))
        self.assertEqual(len(book.ledger.values),7)
        self.assertEqual(book.ledger.values[6][6],first[6])
        self.assertEqual(book.ledger.values[6][18:],first[18:])

    def test_precise_raw_price_rejects_rounded_over_cap(self):
        rows=population();rows[0][6]=1.70;book=Book()
        result=c.update_research(book,rows,NOW,{3},first_row=3,
                                 quote_sheet=Quotes(rows,{3:[None,1.70001]}))
        self.assertEqual(result["counted"],0)

    def test_all_three_rules_can_capture_one_fixture_independently(self):
        book=Book();rows=population();rows[0][5]=1.65
        for module in [a,b,c]:module.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows))
        ledgers=[book.a_ledger,book.b_ledger,book.ledger]
        self.assertTrue(all(len(l.values)==7 for l in ledgers))
        self.assertEqual(len({l.values[6][0] for l in ledgers}),3)

    def test_settlement_uses_existing_entry_and_missing_f_is_irrelevant(self):
        book=Book();rows=population()
        c.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows))
        rows[0][15]="2-0"
        class Source:
            def get(self,*args,**kwargs):return [[r[76]] for r in rows]
        c.settle_results(book,Source(),[r[:57] for r in rows],NOW+timedelta(minutes=45))
        self.assertEqual(book.ledger.values[6][15],"ΕΠΙΤΥΧΙΑ")
        self.assertEqual(book.ledger.values[6][17],.6)

    def test_no_historical_backfill_or_disabled_entry(self):
        self.assertEqual(c.update_research(Book(),population(),NOW,first_row=3)["counted"],0)
        self.assertEqual(c.update_research(Book("OFF"),population(),NOW,{3},first_row=3)["counted"],0)

    def test_level_review_preserves_c_ledger_owned_metrics(self):
        from alert_level_review import run_level_review_if_due
        class ReviewLevels:
            def get(self,*args,**kwargs):
                return [["ALERT"]*20,[c.ALERT_NAME,"FAVORITE",0,"🧪","RESEARCH_ONLY"]+[""]*15]
            def update(self,*args,**kwargs):raise AssertionError("C metrics overwritten")
        class Source:
            def get(self,*args,**kwargs):return []
        class ReviewBook:
            def worksheet(self,name):return ReviewLevels() if name=="ALERT LEVELS" else Source()
        self.assertTrue(run_level_review_if_due(ReviewBook(),force=True)["ok"])


if __name__=="__main__":unittest.main()
