import unittest
from test_lineup_impact import fixture
from lineup_goal_context import evaluate,context,defensive

class GoalContextTest(unittest.TestCase):
    def test_attacking_real_values_and_split(self):
        c,h,s=fixture();v=evaluate(c,h,s,{m:1 for m in range(1,6)})[0]
        self.assertEqual(v["status"],"measured")
        self.assertEqual((v["baseline"],v["current"]),(1,2))
        self.assertEqual(v["components"],[{"label":"Γκολ","baseline":0,"current":2},{"label":"Ασίστ","baseline":1,"current":0}])
    def test_defence_same_group_counts_match_once(self):
        c,h,s=fixture();r=evaluate(c,h,s,{1:0,2:1,3:2,4:3,5:4})
        for v in (r[2],r[3]):
            self.assertEqual(v["status"],"measured")
            self.assertEqual((v["baseline"],v["current"]),(2,2))
            self.assertTrue(v["lower_better"])
            self.assertTrue(v["same_lineup"])
    def test_changed_defence_uses_overlap_weight(self):
        ms=[(i,{"D":[1,2] if i<4 else [1,3]}) for i in range(1,7)]
        sc={i:0 if i<4 else 3 for i in range(1,7)}
        x=context([1,3],"D",ms,sc)
        self.assertAlmostEqual(x["value"],2)
        r=defensive([1,3],[[1,2]]*3,"D",ms,sc)
        self.assertEqual((r["baseline"],r["current"]),(1,2))
        self.assertTrue(r["lower_better"])
    def test_missing_scores_and_novel_player(self):
        ms=[(i,{"D":[1,2]}) for i in range(1,6)]
        self.assertIsNone(context([1,3],"D",ms,{i:1 for i in range(1,6)}))
        self.assertIsNone(context([1,2],"D",ms,{1:1,2:0}))
    def test_zero_baseline_allowed_for_absolute_metric(self):
        c,h,s=fixture()
        for r in s["11footy"][11]:r["metrics"]["assists"]=0
        v=evaluate(c,h,s,{m:0 for m in range(1,6)})[0]
        self.assertEqual((v["baseline"],v["current"]),(0,2))
    def test_expected_goals_not_added_to_assists(self):
        c,h,s=fixture()
        for rows in s["11footy"].values():
            for r in rows:r["metrics"].update(xg=.1,xa=.2)
        v=evaluate(c,h,s,{})[0]
        self.assertEqual([x["metric"] for x in v["additional"]],["xG / 90′","xA / 90′"])
if __name__=="__main__":unittest.main()
