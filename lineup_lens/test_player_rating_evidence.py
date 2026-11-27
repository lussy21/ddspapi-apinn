import unittest
from player_rating_evidence import profile,compare
from lineup_footprint import assess
from test_lineup_footprint import xi,games,player

def ratings(r,pos="D",minutes=90,n=6):
    return [{"match_id":i,"rating":r,"position":pos,"minutes":minutes} for i in range(n)]
class RatingEvidenceTests(unittest.TestCase):
    def test_strong_defender(self):
        self.assertEqual(compare(ratings(6.6),ratings(7.2),"D")[0],"positive")
    def test_weak_defender(self):
        self.assertEqual(compare(ratings(7.2),ratings(6.6),"D")[0],"negative")
    def test_similar(self):
        self.assertEqual(compare(ratings(7.1),ratings(7.15),"D")[0],"similar")
    def test_substitute_minutes_count(self):
        self.assertIsNotNone(profile(ratings(7.1,minutes=45,n=8),"D"))
    def test_short_subs_insufficient(self):
        self.assertIsNone(compare(ratings(6.6),ratings(9.0,minutes=15,n=6),"D"))
    def test_different_positions(self):
        self.assertIsNone(compare(ratings(6.6),ratings(8.0,pos="F"),"D"))
    def test_missing_rating(self):
        self.assertIsNone(profile(ratings(None),"D"))
    def test_duplicate_matches(self):
        self.assertIsNone(profile(ratings(7.0)+ratings(7.0),"D"))
    def test_familiar_not_quality(self):
        now=xi();now[2]=player(99,"CD-R")
        result=assess(now,games(),{},team_starts={3:10,99:9})[1]
        self.assertEqual(result["status"],"familiar")
    def test_familiar_does_not_override_real_evidence(self):
        now=xi();now[2]=player(99,"CD-R")
        result=assess(now,games(),{},ratings={3:ratings(7.5),99:ratings(6.5)},team_starts={3:10,99:9})[1]
        self.assertEqual(result["status"],"negative")
if __name__=="__main__":unittest.main()
