import unittest
from unittest.mock import patch
from datetime import datetime,date,timezone
import soccer_stats_archive as a

class Result:
    def fetchall(self):return []
class DB:
    def __init__(self):self.inserts=[]
    def execute(self,sql,params=()):
        if "INSERT INTO soccer_stats_fixture" in sql:self.inserts.append(params)
        return Result()
class CollectionTests(unittest.TestCase):
    def test_one_week_maps_all_matches_not_only_preferred(self):
        day=date(2026,11,22);ko=datetime(2026,11,22,12,tzinfo=timezone.utc)
        missing=[{"match_id":i,"competition_code":"TR1","local_date":day,"kickoff_utc":ko,
            "home_team_id":i*2,"away_team_id":i*2+1,"comp":"competition_demo","season_id":"season_demo"} for i in (1,2)]
        db=DB()
        with patch.object(a,"request",return_value=[{}]) as req,patch.object(a,"find_fixture",side_effect=lambda rows,m:("match_%05d"%m["match_id"],"team_11111","team_22222")),patch.object(a,"status"):
            self.assertTrue(a.discover(None,None,db,missing,({},set()),preferred={1}))
        self.assertEqual(req.call_count,1)
        self.assertEqual({i[0] for i in db.inserts},{1,2})
    def test_preferred_empty_does_not_spend_call(self):
        with patch.object(a,"request") as req:
            self.assertFalse(a.discover(None,None,DB(),[],({},set()),preferred=set()))
            req.assert_not_called()
if __name__=="__main__":unittest.main()
