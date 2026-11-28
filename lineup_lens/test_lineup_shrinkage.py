import unittest
from test_lineup_impact import fixture
from lineup_goal_context import evaluate
from lineup_shrinkage import player_profile,priors_from,defensive,PRIOR_MINUTES

def prior(rates):return dict(rates=rates,players=20,minutes=12000)
def sample_priors():
    fields=("goals","assists")
    return {"11footy":{(g,fields):prior([.3,.1]) for g in ("F","A","M","D","G")}}

class ShrinkageTest(unittest.TestCase):
    def test_debut_is_prior_not_zero(self):
        p=player_profile([],("goals",),prior([.3]),0)
        self.assertEqual(p["values"],[.3])
        self.assertEqual(p["weight"],0)
        self.assertIsNone(p["raw"])
        self.assertIsNone(p["totals"])
    def test_missing_is_not_debut(self):
        p=player_profile([],("goals",),prior([.3]),8)
        self.assertEqual(p["state"],"ελλιπή στατιστικά")
        self.assertIsNone(p["raw"])
    def test_twenty_minutes_as_sub_are_used(self):
        p=player_profile([dict(match_id=1,minutes=20,metrics={"goals":1})],("goals",),prior([.3]),0)
        self.assertAlmostEqual(p["values"][0],(90+430*.3)/450)
        self.assertAlmostEqual(p["weight"],20/450)
        self.assertEqual(p["raw"],[4.5])
        self.assertEqual(p["matches"],1)
    def test_ten_goals_vs_debut(self):
        rows=[dict(match_id=m,minutes=90,metrics={"goals":1}) for m in range(10)]
        p=player_profile(rows,("goals",),prior([.3]),10)
        self.assertAlmostEqual(p["values"][0],1.0)
        self.assertAlmostEqual(p["values"][0]-.3,.7)
    def test_450_minutes_raw_exactly(self):
        rows=[dict(match_id=m,minutes=90,metrics={"goals":1}) for m in range(5)]
        p=player_profile(rows,("goals",),prior([.3]),5)
        self.assertEqual(p["values"],[1.0])
        self.assertEqual(p["weight"],1.0)
        self.assertEqual(p["raw"],p["values"])
        self.assertEqual(player_profile(rows,("goals",),None,5)["values"],[1.0])
    def test_weight_continuous_at_threshold(self):
        rows=[dict(match_id=m,minutes=90,metrics={"goals":1}) for m in range(4)]
        rows.append(dict(match_id=4,minutes=89,metrics={"goals":0}))
        p=player_profile(rows,("goals",),prior([.3]),4)
        self.assertAlmostEqual(p["weight"],449/450)
        self.assertAlmostEqual(p["values"][0],(360+.3)/450)
    def test_three_full_matches_sixty_percent(self):
        rows=[dict(match_id=m,minutes=90,metrics={"goals":1}) for m in range(3)]
        p=player_profile(rows,("goals",),prior([.3]),3)
        self.assertAlmostEqual(p["weight"],.6)
        self.assertAlmostEqual(p["values"][0],.72)
    def test_missing_field_does_not_count_toward_threshold(self):
        rows=[dict(match_id=m,minutes=90,metrics={"goals":1,"assists":0}) for m in range(4)]
        rows.append(dict(match_id=4,minutes=90,metrics={"goals":1}))
        p=player_profile(rows,("goals","assists"),prior([.3,.1]),5)
        self.assertEqual(p["minutes"],360)
        self.assertEqual(p["observed_minutes"],450)
        self.assertAlmostEqual(p["weight"],.8)
        self.assertEqual(p["state"],"μερικά στατιστικά")
    def test_line_not_removed_for_debut(self):
        c,h,s=fixture();s["11footy"].pop(99)
        before=evaluate(c,h,s,{m:1 for m in range(1,6)})[0]
        after=evaluate(c,h,s,{m:1 for m in range(1,6)},priors=sample_priors())[0]
        self.assertEqual(before["status"],"unknown")
        self.assertEqual(after["status"],"estimated")
        self.assertTrue(after["small_sample"])
        self.assertEqual(next(p for p in after["profiles"] if p["id"]==99)["minutes"],0)
    def test_unresolved_identity_prior_explicit(self):
        c,h,s=fixture();c[-1]["id"]=-99;c[-1]["unresolved"]=True
        p=evaluate(c,h,s,{},priors=sample_priors())[0]["profiles"][-1]
        self.assertIn("μη επιβεβαιωμένη",p["state"])
        self.assertIsNone(p["raw"])
    def test_missing_prior_not_fabricated(self):
        c,h,s=fixture();s["11footy"].pop(99)
        self.assertEqual(evaluate(c,h,s,{},priors={})[0]["status"],"unknown")
    def test_no_team_reference_evidence(self):
        c,h,s=fixture();s={"11footy":{99:s["11footy"][99]}}
        self.assertEqual(evaluate(c,h,s,{},priors=sample_priors())[0]["status"],"unknown")
    def test_same_line_stable(self):
        c,h,s=fixture();c[-1]=dict(id=11,name="P11",code="F")
        self.assertEqual(evaluate(c,h,s,{},priors=sample_priors())[0]["value"],0)
    def test_defence_with_new_player(self):
        ms=[(i,{"D":[1,2]}) for i in range(1,6)]
        r=defensive([1,99],[[1,2]]*5,"D",ms,{i:i%3 for i in range(1,6)})
        self.assertEqual(r["status"],"estimated")
        self.assertTrue(r["small_sample"])
        self.assertIn("1 χωρίς ιστορικό",r["sample_label"])
    def test_actual_prior_from_starters_not_guessed_sub_positions(self):
        rows={i:[dict(match_id=m,minutes=90,metrics={"goals":1,"assists":0}) for m in range(1,4)] for i in range(1,9)}
        rows[99]=[dict(match_id=1,minutes=20,metrics={"goals":10,"assists":0})]
        positions={(m,i):"F" for i in range(1,9) for m in range(1,4)}
        p=priors_from({"ESPN":rows},positions)["ESPN"][("F",("goals","assists"))]
        self.assertEqual(p["rates"],[1,0])
        self.assertEqual(p["players"],8)
    def test_missing_metric_never_zero(self):
        p=player_profile([dict(match_id=1,minutes=20,metrics={"goals":0})],("goals","assists"),prior([.3,.1]),1)
        self.assertEqual(p["values"],[.3,.1])
        self.assertEqual(p["minutes"],0)
        self.assertIsNone(p["raw"])
if __name__=="__main__":unittest.main()
