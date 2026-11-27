import unittest
from decimal import Decimal
from private_player_totals import totals

class TestExtraSource(unittest.TestCase):
    def test_fpl_separate_and_null(self):
        r=totals([{"minutes":90,"xg":Decimal("0.24"),"chances_created":2},
                  {"minutes":75,"xg":None,"chances_created":0}],"fpl_elo")
        self.assertEqual(r["source"],"fpl_elo")
        self.assertEqual(r["metrics"]["minutes"],{"value":165,"matches":2})
        self.assertEqual(r["metrics"]["xg"],{"value":Decimal("0.24"),"matches":1})
        self.assertEqual(r["metrics"]["chances_created"],{"value":2,"matches":2})
        self.assertNotIn("key_passes",r["metrics"])
        self.assertEqual(r["metrics"]["xa"],{"value":None,"matches":0})
if __name__=="__main__":unittest.main()
