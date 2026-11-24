import unittest
from datetime import date
from archive_espn_belgium import parse_match, BelgianArchiveProblem, _id, MATCH_OFFSET

class BelgianLeagueParserTests(unittest.TestCase):
    def example(self,unknown=False):
        event={
           "id":"401896773","date":"2026-08-30T16:30Z",
           "status":{"type":{"completed":True}},
           "competitions":[{"competitors":[
               {"homeAway":"home","team":{"id":"11553","displayName":"Anderlecht"}},
               {"homeAway":"away","team":{"id":"1010","displayName":"Club Brugge"}}
           ]}]
        }
        codes=["G","LB","CD-L","CD-R","RB","LM","RM","AM-L","AM","AM-R","F"]
        rosters=[]
        for side,tid,prefix in (("home","11553","Anderlecht"),("away","1010","Brugge")):
            people=[]
            for idx,code in enumerate(codes):
                people.append({
                  "athlete":{"id":str(200000+idx+(0 if side=="home" else 1000)),
                             "displayName":prefix+" player "+str(idx)},
                  "starter":True,"position":{"abbreviation":"SUB" if unknown else code},
                  "jersey":str(idx+1)
                })
            people.append({"athlete":{"id":"999999","displayName":"Bench Player"},
                           "starter":False,"position":{"abbreviation":"SUB"}})
            rosters.append({"homeAway":side,"team":{"id":tid,"displayName":prefix},
                            "roster":people})
        return event,{"rosters":rosters}

    def test_real_starter_flags_and_neon_namespaces(self):
        event,summary=self.example()
        m=parse_match(event,summary)
        self.assertEqual(m["match_id"],MATCH_OFFSET+401896773)
        self.assertEqual(m["local_date"],date(2026,8,30))
        self.assertEqual(m["competition_code"],"BE1")
        self.assertEqual(len(m["home"]["players"]),11)
        self.assertEqual(len(m["away"]["players"]),11)
        self.assertEqual(m["home"]["players"][0]["position_code"],"G")
        self.assertEqual(m["home"]["players"][0]["player_name"],"Anderlecht player 0")
        self.assertFalse(m["position_unavailable"])
        self.assertGreater(m["home"]["id"],1_000_000_000)

    def test_espn_starter_position_sub_is_not_guessed(self):
        e,d=self.example(unknown=True)
        m=parse_match(e,d)
        self.assertTrue(m["position_unavailable"])
        self.assertTrue(all(p["position_code"] is None for p in m["home"]["players"]))
        self.assertEqual(len(m["home"]["players"]),11)

    def test_invalid_or_incomplete_starting_eleven_rejected(self):
        e,d=self.example()
        d["rosters"][0]["roster"][0]["starter"]=False
        with self.assertRaises(BelgianArchiveProblem):parse_match(e,d)

    def test_cross_team_mismatch_rejected(self):
        e,d=self.example()
        d["rosters"][0]["team"]["id"]="2222"
        with self.assertRaises(BelgianArchiveProblem):parse_match(e,d)

    def test_duplicate_player_id_rejected(self):
        e,d=self.example()
        d["rosters"][0]["roster"][1]["athlete"]["id"]=d["rosters"][0]["roster"][0]["athlete"]["id"]
        with self.assertRaises(BelgianArchiveProblem):parse_match(e,d)

    def test_id_bounds(self):
        with self.assertRaises(BelgianArchiveProblem):_id("999999999",1_500_000_000)

if __name__=="__main__":unittest.main()
