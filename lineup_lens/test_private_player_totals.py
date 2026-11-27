import unittest
from decimal import Decimal
from private_player_totals import totals
class TestTotals(unittest.TestCase):
    def test_unknown_not_zero(self):
        d=totals([{"minutes_played":90,"goals":0},{"minutes_played":75,"goals":None}],"11footy")
        self.assertEqual(d["matches"],2)
        self.assertEqual(d["metrics"]["minutes"],{"value":165,"matches":2})
        self.assertEqual(d["metrics"]["goals"],{"value":0,"matches":1})
        self.assertEqual(d["metrics"]["assists"],{"value":None,"matches":0})
    def test_decimal_xg(self):
        d=totals([{"xg":Decimal("0.24")},{"xg":Decimal("0.10")}],"soccer_data")
        self.assertEqual(d["metrics"]["xg"],{"value":Decimal("0.34"),"matches":2})
    def test_empty(self):
        self.assertEqual(totals([],"11footy")["matches"],0)
if __name__=="__main__":unittest.main()
