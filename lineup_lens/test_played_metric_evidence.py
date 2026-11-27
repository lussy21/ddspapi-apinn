import unittest
from private_fpl_played import reconcile,blob_sha
from played_metric_evidence import keeper,keeper_profile,compare
from test_lineup_footprint import xi,games,player
from lineup_footprint import assess

def fixture():
    anchors=[];stats=[];players=[];ids={}
    for t in (1,2):
        for i in range(1,13):
            sid=str(t*100+i);pid=t*1000+i
            players.append({"player_id":sid,"team_code":str(t),"position":"Defender"})
            stats.append({"player_id":sid,"match_id":"x","minutes_played":"90" if i<=11 else "30","start_min":"0" if i<=11 else "60","goals_prevented":"-0.8"})
            if i<=11:anchors.append({"sid":sid,"pid":pid,"tid":t})
            if i==12 and t==1:ids[(t,sid)]={pid}
    return {"anchors":anchors,"source_match":"x","match_id":10,"sha":"x","gw":1},stats,players,ids

def gk(gp,n=5):
    return [{"match_id":i,"minutes":90,"position":"G","metrics":{"xgot_faced":1+gp,"goals_conceded":1,"saves":4,"goals_prevented":gp}} for i in range(n)]

class PlayedTests(unittest.TestCase):
    def test_exact_22_and_sub_identity(self):
        m,s,p,i=fixture();rows=reconcile(m,s,p,i)
        self.assertEqual(len(rows),24)
        self.assertEqual(sum(r[4] for r in rows),22)
        self.assertEqual(sum(not r[4] and r[3] is not None for r in rows),1)
        self.assertEqual(sum(not r[4] and r[3] is None for r in rows),1)
    def test_wrong_starter_rejected(self):
        m,s,p,i=fixture();s[0]["start_min"]="10"
        self.assertIsNone(reconcile(m,s,p,i))
    def test_unused_excluded(self):
        m,s,p,i=fixture();s[-1]["minutes_played"]="0"
        self.assertEqual(len(reconcile(m,s,p,i)),23)
    def test_negative_goal_prevention(self):
        m,s,p,i=fixture();rows=reconcile(m,s,p,i)
        self.assertIn("-0.8",rows[0][7])
    def test_keeper_quality(self):
        self.assertEqual(keeper(gk(-.2),gk(.6))[0],"positive")
        self.assertEqual(keeper(gk(.6),gk(-.2))[0],"negative")
    def test_keeper_tiny_sample_no_grade(self):
        self.assertIsNone(keeper_profile(gk(.6,2)))
        self.assertIsNone(keeper(gk(-.2),gk(.6,2)))
    def test_keeper_inconsistent_metric_rejected(self):
        b=gk(.6)
        for r in b:r["metrics"]["goals_prevented"]=5
        self.assertIsNone(keeper_profile(b))
    def test_keeper_in_line_assessment(self):
        c=xi();c[0]=player(99,"G")
        r=assess(c,games(),{},played_metrics={1:gk(-.2),99:gk(.6)})
        self.assertEqual(r[0]["status"],"positive")
    def test_substitute_in_same_nominal_position(self):
        def rows(won,lost,recoveries,interceptions,position="D"):
            return [{"match_id":i,"minutes":45,"position":position,"started":False,
                     "metrics":{"duels_won":won,"duels_lost":lost,"recoveries":recoveries,"interceptions":interceptions}} for i in range(9)]
        self.assertEqual(compare(rows(2,5,1,1),rows(6,1,3,2),"CB","D")[0],"positive")
        self.assertIsNone(compare(rows(2,5,1,1),rows(6,1,3,2,"M"),"CB","D"))
if __name__=="__main__":unittest.main()
