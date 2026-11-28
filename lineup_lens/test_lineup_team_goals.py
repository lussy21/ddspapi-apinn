import unittest
from test_lineup_impact import fixture
from lineup_team_goals import evaluate

def setup():
    c,h,s=fixture()
    p={"11footy":{(g,("goals",)):{"rates":[.3],"players":20,"minutes":10000}
                 for g in ("G","D","M","A","F")}}
    gf={1:1,2:2,3:0,4:3,5:1};ga={1:0,2:1,3:2,4:3,5:4}
    return c,h,s,p,gf,ga

class TeamGoalTest(unittest.TestCase):
    def test_scoring_delta_uses_goals_not_assists(self):
        c,h,s,p,gf,ga=setup()
        r=evaluate(c,h,s,p,gf,ga)
        self.assertEqual(r["for_goals"]["baseline"],1.4)
        self.assertEqual(r["for_goals"]["current"],2.55)
        self.assertEqual(r["against_goals"]["current"],2)
        for rows in s["11footy"].values():
            for row in rows:row["metrics"]["assists"]=100
        self.assertEqual(evaluate(c,h,s,p,gf,ga),r)
    def test_identical_lineup_keeps_team_average(self):
        c,h,s,p,gf,ga=setup();c[-1]=dict(id=11,name="P11",code="F")
        r=evaluate(c,h,s,p,gf,ga)
        self.assertEqual(r["for_goals"]["current"],1.4)
        self.assertEqual(r["against_goals"]["current"],2)
    def test_goals_from_defender_count(self):
        c,h,s,p,gf,ga=setup();c[-1]=dict(id=11,name="P11",code="F")
        c[1]=dict(id=99,name="New",code="LB")
        r=evaluate(c,h,s,p,gf,ga)
        self.assertEqual(r["for_goals"]["current"],2.55)
    def test_new_player_not_zero(self):
        c,h,s,p,gf,ga=setup();del s["11footy"][99]
        r=evaluate(c,h,s,p,gf,ga)
        self.assertEqual(r["for_goals"]["current"],1.7)
        self.assertTrue(r["for_goals"]["small_sample"])
    def test_missing_source_marks_historical_only(self):
        c,h,s,p,gf,ga=setup()
        r=evaluate(c,h,{},p,gf,ga)
        self.assertEqual(r["for_goals"]["status"],"historical")
        self.assertEqual(r["for_goals"]["current"],1.4)
    def test_no_scores_unknown(self):
        c,h,s,p,gf,ga=setup()
        r=evaluate(c,h,s,p,{1:1},ga)
        self.assertEqual(r["for_goals"]["status"],"unknown")
        self.assertIsNone(r["against_goals"]["current"])
    def test_unresolved_id_never_uses_individual_rate(self):
        c,h,s,p,gf,ga=setup();c[-1]["unresolved"]=True
        self.assertEqual(evaluate(c,h,s,p,gf,ga)["for_goals"]["current"],1.7)
    def test_combined_defensive_unit_not_sum(self):
        c,h,s,p,gf,ga=setup();c[1]=dict(id=100,name="New LB",code="LB")
        c[5]=dict(id=101,name="New CM",code="CM-L");c[0]=dict(id=102,name="New GK",code="G")
        r=evaluate(c,h,s,p,gf,ga)
        self.assertEqual(r["against_goals"]["current"],2)
        self.assertTrue(r["against_goals"]["small_sample"])
    def test_only_matched_final_scores_count(self):
        c,h,s,p,gf,ga=setup();gf[6]=100
        r=evaluate(c,h,s,p,gf,ga)
        self.assertEqual(r["games"],5)
        self.assertEqual(r["for_goals"]["baseline"],1.4)

if __name__=="__main__":unittest.main()
