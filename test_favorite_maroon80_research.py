import copy
import json
import unittest
from datetime import timedelta

import favorite_maroon_research as a
import favorite_maroon80_research as b
from contra_rise_research import BIG_LEAGUES, OTHER_LEAGUES
from test_favorite_maroon_research import FakeLedger, source_row as a_source_row

NOW=b.START_AT+timedelta(days=1)


def source_row(minutes=40,money=85,**kwargs):
    row=a_source_row(minutes=minutes,**kwargs)
    row[11]=money;row[76]=(NOW+timedelta(minutes=minutes)).isoformat()
    return row


def item(row=None):
    r=b.fixture(row or source_row(),3)
    if r:r.update(rank=100,population=20)
    return r


def population():
    return [source_row(),source_row(minutes=-2000,k=100,home="Older Home")]


class Ledger(FakeLedger):
    def __init__(self,headers=b.HEADERS):self.values=[[""] for _ in range(5)]+[headers[:]]


class Levels:
    def __init__(self,status="RESEARCH_ONLY"):self.status=status
    def get(self,*args,**kwargs):
        return [[b.ALERT_NAME,"FAVORITE",0,"🧪",self.status],
                [a.ALERT_NAME,"FAVORITE",0,"🧪","RESEARCH_ONLY"]]


class Book:
    def __init__(self,status="RESEARCH_ONLY"):
        self.ledger=Ledger();self.a_ledger=Ledger(a.HEADERS);self.levels=Levels(status)
    def worksheet(self,name):
        if name==b.SHEET_NAME:return self.ledger
        if name==a.SHEET_NAME:return self.a_ledger
        if name=="ALERT LEVELS":return self.levels
        raise ValueError(name)


class Quotes:
    def __init__(self,rows,overrides=None,money_overrides=None):
        self.rows=rows;self.overrides=overrides or {};self.money_overrides=money_overrides or {}
    def batch_get(self,ranges,value_render_option):
        assert value_render_option=="UNFORMATTED_VALUE"
        output=[]
        for address in ranges:
            if address.startswith("A3:A"):output.append([[r[0]] for r in self.rows])
            elif address.startswith("K3:L"):
                output.append([[r[10],self.money_overrides.get(i+3,r[11])] for i,r in enumerate(self.rows)])
            elif address.startswith("K3:K"):output.append([[r[10]] for r in self.rows])
            else:
                index=int(address.split(":")[0][1:]);r=self.rows[index-3]
                output.append([self.overrides.get(index,[r[5],r[6]])])
        return output


class VariantBRuleTests(unittest.TestCase):
    def test_money80_boundary_and_stable_or_any_lower_price(self):
        self.assertTrue(b.qualifies(2,2,100,80))
        self.assertTrue(b.qualifies(2,1.999,100,80))
        self.assertFalse(b.qualifies(2,2.00001,100,100))
        self.assertFalse(b.qualifies(2,1.9,100,79.999))
        self.assertFalse(b.qualifies(2,1.9,87,90))
        self.assertFalse(b.qualifies(2,1.9,100,101))
        for money in [None,float("nan"),float("inf")]:
            self.assertFalse(b.qualifies(2,1.9,100,money))

    def test_a_and_b_remain_different_conditions(self):
        self.assertTrue(a.qualifies(2,1.95,100,65))
        self.assertFalse(b.qualifies(2,1.95,100,65))
        self.assertTrue(b.qualifies(2,1.99,100,85))
        self.assertFalse(a.qualifies(2,1.99,100,85))
        self.assertEqual(len(a.DEFAULT_PROFILE.headers),20)
        self.assertEqual(len(b.HEADERS),22)
        self.assertEqual(a.START_AT.isoformat(),"2026-10-28T02:45:00+02:00")

    def test_both_scope_groups_without_opening_floor_sofa_or_home_filter(self):
        for league in BIG_LEAGUES|OTHER_LEAGUES:
            for side in ["H","A"]:
                record=b.advance_record(None,item(source_row(league=league,side=side)),NOW,True)
                self.assertTrue(record[6])
                self.assertEqual(record[21],"ΜΕΓΑΛΑ" if league in BIG_LEAGUES else "ΛΟΙΠΑ ΕΥΡΩΠΗΣ")
        for league in ["USA - Major League Soccer","Germany - Bundesliga 2","Unknown"]:
            self.assertIsNone(b.fixture(source_row(league=league),3))

    def test_inclusive_entry_window_freshness_and_launch(self):
        for mins in [5,90]:self.assertTrue(b.advance_record(None,item(source_row(minutes=mins)),NOW,True)[6])
        for mins in [4.99,90.01,-1]:self.assertIsNone(b.advance_record(None,item(source_row(minutes=mins)),NOW,True))
        self.assertIsNone(b.advance_record(None,item(),NOW,False))
        self.assertIsNone(b.advance_record(None,item(),b.START_AT-timedelta(seconds=1),True))

    def test_original_money_color_and_price_remain_after_withdrawal(self):
        first=b.advance_record(None,item(),NOW,True)
        later=item(source_row(money=70,g=2.1,k=100));later["rank"]=10
        off=b.advance_record(first,later,NOW+timedelta(minutes=5),True)
        self.assertEqual(off[16],"ΕΦΥΓΕ")
        for i in [6,8,10,11,12,13,18,19,20,21]:self.assertEqual(off[i],first[i])
        self.assertEqual(json.loads(off[18])["L"],85)
        self.assertEqual(json.loads(off[18])["money_basis"],"total_favorite_share")

    def test_draw_is_failure_and_original_side_and_entry_price_settle(self):
        for side,score,won in [("H","0-0",False),("H","2-0",True),("A","1-3",True)]:
            row=source_row(side=side);first=b.advance_record(None,item(row),NOW,True)
            row[3]="A" if side=="H" else "H";row[15]=score;row[6]=1.1
            done=b.advance_record(first,item(row),NOW+timedelta(minutes=45))
            self.assertEqual(done[15],"ΕΠΙΤΥΧΙΑ" if won else "ΑΠΟΤΥΧΙΑ")
            self.assertEqual(done[17],.96 if won else -1)

    def test_native_fractional_percentage_keeps_exact_threshold(self):
        self.assertEqual(a.money_percentage(.8,"80,0%"),80)
        self.assertAlmostEqual(a.money_percentage(.79999,"80,0%"),79.999)
        self.assertEqual(a.money_percentage(79.999,"80,0%"),79.999)
        self.assertEqual(a.money_percentage(.8,"0,8%"),.8)


class VariantBPersistenceTests(unittest.TestCase):
    def test_entries_persist_and_new_fixture_does_not_overwrite(self):
        book=Book();rows=population()
        b.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows))
        frozen=copy.deepcopy(book.ledger.values[6])
        rows.append(source_row(home="Second Home"))
        result=b.update_research(book,rows,NOW+timedelta(minutes=1),{3,5},first_row=3,quote_sheet=Quotes(rows))
        self.assertEqual(result["counted"],2)
        self.assertEqual(len(book.ledger.values),8)
        self.assertEqual(len(book.ledger.values[6]),22)
        self.assertEqual(book.ledger.values[6][6],frozen[6])
        self.assertEqual(book.ledger.values[6][18:],frozen[18:])

    def test_exact_raw_money_rejects_rounded_display_and_accepts_fractional_cell(self):
        for raw,expected in [(79.999,0),(.79999,0),(.8,1),(80,1)]:
            rows=population();rows[0][11]="80,0%";book=Book()
            result=b.update_research(book,rows,NOW,{3},first_row=3,
                                      quote_sheet=Quotes(rows,money_overrides={3:raw}))
            self.assertEqual(result["counted"],expected)

    def test_exact_raw_price_rejects_tiny_rise(self):
        rows=population();rows[0][6]=2;book=Book()
        result=b.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows,{3:[2,2.00001]}))
        self.assertEqual(result["counted"],0)

    def test_a_b_have_independent_keys_and_counters_on_same_fixture(self):
        rows=population();book=Book()
        a.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows))
        b.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows))
        self.assertEqual(len(book.a_ledger.values),7)
        self.assertEqual(len(book.ledger.values),7)
        self.assertNotEqual(book.a_ledger.values[6][0],book.ledger.values[6][0])
        self.assertTrue(book.a_ledger.values[6][0].startswith("maroon2:"))
        self.assertTrue(book.ledger.values[6][0].startswith("maroon80:"))

    def test_no_historical_backfill_or_disabled_entry(self):
        book=Book();result=b.update_research(book,population(),NOW,first_row=3)
        self.assertEqual(result["counted"],0)
        result=b.update_research(Book("OFF"),population(),NOW,{3},first_row=3)
        self.assertEqual(result["counted"],0)

    def test_post_sofa_settlement_retains_money_and_entry_price(self):
        rows=population();book=Book()
        b.update_research(book,rows,NOW,{3},first_row=3,quote_sheet=Quotes(rows))
        rows[0][15]="2-0";rows[0][11]=50;rows[0][6]=1.1
        class Source:
            def get(self,*args,**kwargs):return [[r[76]] for r in rows]
        b.settle_results(book,Source(),[r[:57] for r in rows],NOW+timedelta(minutes=45))
        self.assertEqual(book.ledger.values[6][15],"ΕΠΙΤΥΧΙΑ")
        self.assertEqual(book.ledger.values[6][17],.96)
        self.assertEqual(book.ledger.values[6][20],85)

    def test_level_review_does_not_replace_b_counters(self):
        from alert_level_review import run_level_review_if_due
        class ReviewLevels:
            def get(self,*args,**kwargs):
                return [["ALERT"]*20,[b.ALERT_NAME,"FAVORITE",0,"🧪","RESEARCH_ONLY"]+[""]*15]
            def update(self,*args,**kwargs):raise AssertionError("B counters overwritten")
        class Source:
            def get(self,*args,**kwargs):return []
        class ReviewBook:
            def worksheet(self,name):return ReviewLevels() if name=="ALERT LEVELS" else Source()
        self.assertTrue(run_level_review_if_due(ReviewBook(),force=True)["ok"])


if __name__=="__main__":unittest.main()
