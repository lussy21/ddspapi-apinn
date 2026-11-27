import unittest
from lineup_summary import summarize
from lineup_footprint import line

def sample():
    prior=[]
    for mid in range(1,12):
        for pid in range(1,12):
            if pid==1: actual=1 if mid<=7 else 12
            elif pid==11:actual=11 if mid<=6 else 13
            else:actual=pid
            prior.append({"match_id":mid,"player_id":actual,"player_name":"Player "+str(actual),"position_code":"G" if pid==1 else "F" if pid==11 else "CM"})
    current=[{"id":i,"name":"Player "+str(i),"code":"G" if i==1 else "F" if i==13 else "CM"} for i in list(range(1,11))+[13]]
    production=[{"player_id":11,"match_id":i,"goals":1 if i<=5 else 0,"assists":1 if i<=3 else 0,"source":"fpl_elo"} for i in range(1,7)]
    lines=[{"line":"Τερματοφύλακας","status":"unknown","text":""}]
    return current,prior,production,lines
class SummaryTests(unittest.TestCase):
    def test_find_contributor_and_frequent_keeper(self):
        c,p,s,l=sample();r=summarize(c,p,s,l,line)
        self.assertIn("Player 11",r[0]["text"])
        self.assertIn("5 γκολ, 3 ασίστ",r[0]["detail"])
        self.assertTrue(any("Player 1:" in x["text"] for x in r))
    def test_never_double_count_sources(self):
        c,p,s,l=sample();s+= [dict(x,source="11footy") for x in s]
        self.assertIn("5 γκολ, 3 ασίστ",summarize(c,p,s,l,line)[0]["detail"])
    def test_missing_goals_not_zero(self):
        c,p,s,l=sample();s=[dict(x,assists=None) for x in s]
        self.assertFalse(any("γκολ" in x["detail"] for x in summarize(c,p,s,l,line)))
    def test_unknown_identity_no_false_absence(self):
        c,p,s,l=sample();c[0]["unresolved"]=True
        self.assertEqual(len(summarize(c,p,s,l,line)),1)
        self.assertIn("αντιστοιχιστεί",summarize(c,p,s,l,line)[0]["text"])
    def test_present_contributor_not_absent(self):
        c,p,s,l=sample();c[-1]["id"]=11
        self.assertFalse(any("Player 11" in x["text"] for x in summarize(c,p,s,l,line)))
if __name__=="__main__":unittest.main()
