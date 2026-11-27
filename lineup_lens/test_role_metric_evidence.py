import unittest
from role_metric_evidence import evidence
from lineup_footprint import assess
from test_lineup_footprint import xi,games,player
from test_player_rating_evidence import ratings

def rows(won=5,lost=5,rec=3,inter=1,role="CB",n=6):
    return [{"match_id":i,"minutes":90,"role":role,"duels_won":won,"duels_lost":lost,
             "recoveries":rec,"interceptions":inter} for i in range(n)]
class RoleMetricTests(unittest.TestCase):
    def test_defence_positive(self):
        self.assertEqual(evidence(rows(3,7,2,1),rows(8,2,5,3),"CB")[0],"positive")
    def test_defence_negative(self):
        self.assertEqual(evidence(rows(8,2,5,3),rows(3,7,2,1),"CB")[0],"negative")
    def test_activity_alone_not_quality(self):
        self.assertIsNone(evidence(rows(5,5,2,1),rows(5,5,5,3),"CB"))
    def test_small_sample_and_wrong_role(self):
        self.assertIsNone(evidence(rows(),rows(n=3),"CB"))
        self.assertIsNone(evidence(rows(),rows(role="RB"),"CB"))
    def test_missing_metric_not_zero(self):
        b=rows(8,2,5,3)
        for r in b:r["duels_lost"]=None
        self.assertIsNone(evidence(rows(3,7,2,1),b,"CB"))
    def test_conflict_not_negative_or_positive(self):
        now=xi();now[2]=player(99,"CD-R")
        result=assess(now,games(),{},ratings={3:ratings(7.5),99:ratings(6.5)},role_metrics={3:rows(3,7,2,1),99:rows(8,2,5,3)})
        self.assertEqual(result[1]["status"],"unknown")
        self.assertIn("αντίθετες",result[1]["text"])
    def test_attack(self):
        def attack(xg,xa,sot):
            return [{"match_id":i,"minutes":90,"role":"CF","xg":xg,"xa":xa,"shots_on_target":sot} for i in range(6)]
        self.assertEqual(evidence(attack(.2,.1,.7),attack(.8,.3,2),"CF")[0],"positive")
if __name__=="__main__":unittest.main()
