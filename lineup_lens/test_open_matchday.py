"""Run: PYTHONPATH=lineup_lens python -m unittest discover -s lineup_lens -p 'test_open_matchday.py' -v"""
import unittest
from open_matchday import parse_fixture_csv, fetch_day, FixtureSourceProblem

FAKE="gw,date,time,home,away\n11,2026-11-23,21:00,Brentford,Everton\n12,2026-11-24,19:00,Other,Visitor\n"

class TestOpenFixtures(unittest.TestCase):
    def test_only_selected_date(self):
        rows=parse_fixture_csv(FAKE,"2026-11-23","england")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["home"],"Brentford")
        self.assertIs(rows[0]["confirmed_lineup"],False)
        self.assertIsNone(rows[0].get("match_id"))

    def test_no_fake_time(self):
        rows=parse_fixture_csv("date,time,home,away\n2026-11-23,,A,B\n","2026-11-23","italy")
        self.assertIsNone(rows[0]["kickoff_source_time"])

    def test_untrusted_rows(self):
        rows=parse_fixture_csv("date,time,home,away\n2026-11-23,20:00,A,A\n","2026-11-23","italy")
        self.assertEqual(rows,[])

    def test_bad_league(self):
        with self.assertRaises(FixtureSourceProblem):
            parse_fixture_csv(FAKE,"2026-11-23","bad")

    def test_invalid_schema(self):
        with self.assertRaises(FixtureSourceProblem):
            parse_fixture_csv("day,club\n2026-11-23,X","2026-11-23","england")

    def test_fetch_without_network(self):
        class Response:
            text=FAKE
            content=FAKE.encode()
            def raise_for_status(self): pass
        called=[]
        def get(url,**kwargs):
            called.append(url)
            return Response()
        r=fetch_day("2026-11-23",("england",),get=get)
        self.assertEqual(r["count"],1)
        self.assertEqual(len(called),1)
        self.assertFalse(r["fixtures"][0]["has_lineup_data"])

if __name__=="__main__":
    unittest.main()
