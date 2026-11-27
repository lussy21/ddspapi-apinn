import unittest
from lineup_footprint import assess,compare,sample
from private_11footy_subs import reconcile_subs
from private_11footy_stats import FIELDS

def player(i,code):
    return {"id":i,"name":"Player "+str(i),"code":code}
def xi():
    return [player(i,c) for i,c in enumerate(["G","RB","CD-R","CD-L","LB","DM","CM-L","CM-R","LF","F","RF"],1)]
def games():
    return [{"kickoff_utc":i,"players":xi()} for i in range(5)]
def samples(shots,goals,assists,mins=90,n=5):
    return [{"match_id":i,"metrics":{"minutes_played":mins,"shots_on_target":shots,"goals":goals,"assists":assists}} for i in range(n)]
class TestFootprint(unittest.TestCase):
    def test_usual(self):
        self.assertTrue(all(x["status"]=="usual" for x in assess(xi(),games(),{})))
    def test_substitute_not_penalized(self):
        now=xi();now[9]=player(99,"F")
        self.assertEqual(assess(now,games(),{})[-1]["status"],"unknown")
        stats={10:samples(1,0,0),99:samples(3,1,1,45,9)}
        self.assertEqual(assess(now,games(),stats)[-1]["status"],"positive")
    def test_negative_requires_evidence(self):
        self.assertEqual(compare(samples(3,1,1),samples(1,0,0),"F")[0],"negative")
    def test_short_sample_unknown(self):
        self.assertEqual(compare(samples(1,0,0),samples(3,1,1,30,4),"F")[0],"unknown")
    def test_defence_unknown_even_many_goals(self):
        self.assertEqual(compare(samples(1,0,0),samples(3,1,1),"CB")[0],"unknown")
    def test_role_change_unknown(self):
        now=xi();now[9]=player(99,"LF")
        self.assertEqual(assess(now,games(),{})[-1]["status"],"unknown")
    def test_missing_field(self):
        self.assertIsNone(sample([{"match_id":i,"metrics":{"minutes_played":90,"goals":0}} for i in range(5)],("goals","assists")))
    def test_missing_history(self):
        self.assertTrue(all(x["status"]=="unknown" for x in assess(xi(),games()[:3],{})))
    def test_actual_sub_linking_and_unused_excluded(self):
        anchors=[];rosters={123:{1:[],2:[]},124:{1:[],2:[]}};people={}
        for mid in (123,124):
            for team in (1,2):
                start=list(range(team*100+1,team*100+12))
                if mid==124:start[-1]=team*100+12
                for pid in start:
                    anchors.append({"match_id":mid+500,"provider_match_id":str(mid),"team_id":team+10,"provider_player_id":str(pid),"player_id":pid+1000})
                    people[pid]="Player "+str(pid)
                    rosters[mid][team].append({"player_id":pid,"started":1})
                for pid,mins in [(team*100+(12 if mid==123 else 11),30),(team*100+14,0)]:
                    people[pid]="Player "+str(pid)
                    row={k:0 for k in FIELDS};row.update(player_id=pid,started=0,minutes_played=mins,shirt_number=14)
                    rosters[mid][team].append(row)
        rows,n=reconcile_subs(anchors,rosters,people)
        self.assertEqual(n,2);self.assertEqual(len(rows),4)
        self.assertTrue(all(r[4] is not None for r in rows))
if __name__=="__main__":unittest.main()
