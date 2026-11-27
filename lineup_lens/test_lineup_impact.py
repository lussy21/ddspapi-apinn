import unittest
from lineup_impact import evaluate,profile,aggregate

CODES=["G","LB","CD-L","CD-R","RB","CM-L","CM-R","AM-L","AM","AM-R","F"]
def fixture():
    history=[dict(match_id=m,kickoff_utc=m,player_id=i,player_name="P"+str(i),position_code=c)
        for m in range(1,6) for i,c in enumerate(CODES,1)]
    current=[dict(id=i,name="P"+str(i),code=c) for i,c in enumerate(CODES,1)]
    current[-1]=dict(id=99,name="New",code="F")
    def stats(i):
        return [dict(match_id=m,minutes=90 if i!=99 else 45,metrics={"goals":1 if i==99 else 0,"assists":1 if i==11 else 0}) for m in range(1,6)]
    return current,history,{"11footy":{i:stats(i) for i in [*range(1,12),99]}}
class ImpactTest(unittest.TestCase):
    def test_substitute_can_improve(self):
        c,h,s=fixture();v=evaluate(c,h,s)[0]
        self.assertEqual(v["status"],"measured");self.assertEqual(v["value"],100)
        self.assertEqual(v["baseline"],1);self.assertEqual(v["current"],2)
        self.assertEqual(v["current_only"],["New"])
        self.assertEqual(v["reference_games"],5);self.assertTrue(v["small_sample"])
    def test_missing_is_unknown_not_zero(self):
        c,h,s=fixture()
        for r in s["11footy"][99]:r["metrics"]["goals"]=None
        self.assertEqual(evaluate(c,h,s)[0]["status"],"unknown")
    def test_all_same_no_claim_of_equal_quality(self):
        c,h,s=fixture()
        c[-1]=dict(id=11,name="P11",code="F")
        self.assertEqual(evaluate(c,h,s)[0]["status"],"unchanged")
        self.assertIsNone(evaluate(c,h,s)[0]["value"])
    def test_no_mixing_providers(self):
        c,h,s=fixture();new=s["11footy"].pop(99);s["other"]={99:new}
        self.assertEqual(evaluate(c,h,s)[0]["status"],"unknown")
    def test_duel_group_uses_weighted_success(self):
        p={1:{"values":[6,4]},2:{"values":[1,9]}}
        self.assertEqual(aggregate([1,2],p,"duels"),35)
    def test_unknown_zero_base(self):
        c,h,s=fixture()
        for r in s["11footy"][11]:r["metrics"]["assists"]=0
        self.assertEqual(evaluate(c,h,s)[0]["status"],"unknown")
    def test_no_duplicate_matches(self):
        rows=[dict(match_id=1,minutes=90,metrics={"goals":1})]*3
        self.assertIsNone(profile(rows,("goals",),"sum"))
    def test_unresolved_only_affected_line(self):
        c,h,s=fixture();c[-1]["unresolved"]=True
        a=evaluate(c,h,s);self.assertEqual(a[0]["status"],"unknown");self.assertEqual(a[1]["status"],"unchanged")
if __name__=="__main__":unittest.main()
