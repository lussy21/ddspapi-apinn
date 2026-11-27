import unittest,json
from collections import defaultdict
from private_11footy_stats import match_side,reconcile,FIELDS,RELEASE
class TestPrivateStats(unittest.TestCase):
    def setUp(self):
        self.canonical=[];self.provider=[]
        for i in range(1,12):
            self.canonical.append(dict(player_id=i,team_id=10,player_name="Player "+str(i),jersey_number=i))
            self.provider.append(dict(player_id=i+100,player_name="Player "+str(i),shirt_number=i,**{k:90 if k=="minutes_played" else None for k in FIELDS}))
    def test_exact_name_jersey(self):self.assertEqual(len(match_side(self.canonical,self.provider)),11)
    def test_missing_jersey_and_wrong_name_rejected(self):
        self.canonical[0]["jersey_number"]=None;self.provider[0]["player_name"]="Different"
        self.assertIsNone(match_side(self.canonical,self.provider))
    def test_wrong_jersey(self):
        self.provider[0]["shirt_number"]=22
        self.assertIsNone(match_side(self.canonical,self.provider))
    def test_duplicate_identity(self):
        self.provider[0]["player_id"]=self.provider[1]["player_id"]
        self.assertIsNone(match_side(self.canonical,self.provider))
    def test_missing_minutes(self):
        self.provider[0]["minutes_played"]=None
        self.assertIsNone(match_side(self.canonical,self.provider))
    def test_two_full_sides(self):
        away=[dict(p,player_id=p["player_id"]+50,team_id=20,player_name="Away "+str(i)) for i,p in enumerate(self.canonical)]
        away_src=[dict(p,player_id=p["player_id"]+50,player_name="Away "+str(i)) for i,p in enumerate(self.provider)]
        games=[dict(match_id=1,local_date="2026-08-21",home_team_id=10,away_team_id=20,source_release="espn-test")]
        starts=defaultdict(list,{(1,10):self.canonical,(1,20):away})
        src=[dict(match_id=2,local_date="2026-08-21",home_team_id=11,away_team_id=21)]
        sides=defaultdict(list,{(2,11):self.provider,(2,21):away_src})
        rows,miss=reconcile(games,starts,src,sides)
        self.assertEqual(len(rows),22);self.assertEqual(miss,[])
        self.assertIsNone(json.loads(rows[0][-1])["goals"])
        sides[(2,21)].pop()
        self.assertEqual(reconcile(games,starts,src,sides),([],[1]))
if __name__=="__main__":unittest.main()
