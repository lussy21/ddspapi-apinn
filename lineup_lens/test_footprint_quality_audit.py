import unittest
from datetime import datetime,timezone,timedelta
from player_rating_evidence import compare_group
from test_player_rating_evidence import ratings
from test_lineup_footprint import xi,player
from footprint_audit import evaluate
from soccer_stats_coverage import verify_season,match_competition
from soccer_stats_archive import collection_key,norm

class QualityAuditTests(unittest.TestCase):
    def test_group_rating(self):
        self.assertEqual(compare_group([ratings(6.6),ratings(6.7)],[ratings(7.4),ratings(7.2)],"D")[0],"positive")
        self.assertIsNone(compare_group([ratings(6.6),ratings(6.7)],[ratings(7.4),[]],"D"))
    def test_season_coverage_not_league_flag(self):
        doc={"id":"competition_test","seasons":[
            {"id":"season_older","year":"25/26","data_types":{"player_stats":{"available":True}}},
            {"id":"season_current","year":"26/27","data_types":{"player_stats":{"available":False}}}]}
        self.assertEqual(verify_season("TR1","competition_test",doc)[2],"no_current_season_stats")
        doc["seasons"][1]["data_types"]["player_stats"]["available"]=True
        self.assertEqual(verify_season("TR1","competition_test",doc)[2],"ready")
        self.assertEqual(verify_season("NO1","competition_test",doc)[2],"season_unverified")
    def test_exact_turkish_names(self):
        self.assertEqual(norm("Kasımpaşa"),norm("Kasimpasa"))
        r,state=match_competition("TR1",[{"id":"competition_test","country":"Türkiye","name":"Trendyol Süper Lig"}])
        self.assertEqual(state,"found")
    def test_collection_prioritizes_upcoming_and_coverage(self):
        now=datetime(2026,11,27,tzinfo=timezone.utc)
        common={"match_id":1,"home_team_id":1,"away_team_id":2,"kickoff_utc":now-timedelta(days=10)}
        a=dict(common,competition_code="TR1");b=dict(common,competition_code="PL",match_id=2)
        self.assertLess(collection_key(a,{"PL":.6,"TR1":0},set(),now),collection_key(b,{"PL":.6,"TR1":0},set(),now))
        self.assertLess(collection_key(b,{"PL":.6,"TR1":0},{("PL",1)},now),collection_key(a,{"PL":.6,"TR1":0},{("PL",1)},now))
    def test_real_historical_order_and_no_current_match_leakage(self):
        fixtures=[];starters=[];stats=[];rt=[]
        for i in range(1,7):
            fixtures.append({"match_id":i,"kickoff_utc":i,"home_team_id":1,"away_team_id":2})
            for tid in (1,2):
                current=xi()
                if i==6 and tid==1:current[2]=player(99,"CD-R")
                for p in current:
                    starters.append({"match_id":i,"team_id":tid,"player_id":p["id"],"player_name":p["name"],"position_code":p["code"]})
                if tid==1:
                    rt.append({"match_id":i,"team_id":tid,"player_id":3,"rating":6.2,"minutes":90,"position":"D"})
                    if i>=2:rt.append({"match_id":i,"team_id":tid,"player_id":99,"rating":9.2,"minutes":90,"position":"D"})
        result=evaluate(fixtures,starters,stats,rt)
        self.assertEqual(sum(result["lines"].values()),48)
        # Player 99's fifth appearance is this match; cannot use it to qualify.
        self.assertEqual(result["individual_quality_lines"],0)
        self.assertEqual(result["lines"]["unknown"],41)
if __name__=="__main__":unittest.main()
