import unittest
from copy import deepcopy
from espn_player_metrics import parse,minute,InvalidStats
from lineup_goal_context import evaluate
from test_lineup_impact import fixture

def sheet():
    match=dict(match_id=500000001,home_team_id=1000000001,away_team_id=1000000002,home_goals=1,away_goals=0)
    def player(i,starter=True,ins=False,outs=False,goals=0,assists=0,own=0,red=0,plays=None,keeper=False,gc=0):
        metrics=dict(appearances=1,redCards=red,totalGoals=goals,goalAssists=assists,ownGoals=own)
        if keeper:metrics.update(saves=2,goalsConceded=gc)
        return dict(athlete=dict(id=str(i),displayName="P"+str(i)),starter=starter,subbedIn=ins,subbedOut=outs,
                    plays=plays or [],stats=[dict(name=k,value=v) for k,v in metrics.items()])
    sub=dict(substitution=True,clock=dict(displayValue="45'+2'"))
    red=dict(redCard=True,clock=dict(displayValue="70'"))
    h=[player(i,keeper=i==1,goals=int(i==2),assists=int(i==3),outs=i==11,plays=[sub] if i==11 else []) for i in range(1,12)]
    h.append(player(12,starter=False,ins=True,plays=[sub]))
    a=[player(i,keeper=i==21,gc=1,red=int(i==31),plays=[red] if i==31 else []) for i in range(21,32)]
    doc=dict(header=dict(id="1",competitions=[dict(status=dict(type=dict(completed=True,name="STATUS_FULL_TIME")),
          competitors=[dict(id="1",score="1"),dict(id="2",score="0")])]),
          rosters=[dict(team=dict(id="1"),roster=h),dict(team=dict(id="2"),roster=a)])
    expected={1000000001:{1500000000+i for i in range(1,12)},1000000002:{1500000000+i for i in range(21,32)}}
    return doc,match,expected

class EspnVerifiedTest(unittest.TestCase):
    def test_minutes_red_and_stoppage(self):
        d,m,x=sheet();rows=parse(d,m,x);p={r["player_id"]:r for r in rows}
        self.assertEqual(len(rows),23)
        self.assertEqual(p[1500000011]["minutes"],45)
        self.assertEqual(p[1500000012]["minutes"],45)
        self.assertEqual(p[1500000031]["minutes"],70)
        self.assertEqual(sum(r["minutes"] for r in rows),1960)
        self.assertEqual(p[1500000021]["metrics"]["goals_conceded"],1)
        self.assertNotIn("goals_conceded",p[1500000022]["metrics"])
    def test_missing_goals_not_zero(self):
        d,m,x=sheet();d["rosters"][0]["roster"][1]["stats"]=[s for s in d["rosters"][0]["roster"][1]["stats"] if s["name"]!="totalGoals"]
        with self.assertRaises(InvalidStats):parse(d,m,x)
    def test_identity_rejected(self):
        d,m,x=sheet();x[1000000001].remove(1500000001)
        with self.assertRaises(InvalidStats):parse(d,m,x)
    def test_score_rejected(self):
        d,m,x=sheet();m["home_goals"]=2
        with self.assertRaises(InvalidStats):parse(d,m,x)
    def test_unbalanced_substitutions_rejected(self):
        d,m,x=sheet();d["rosters"][0]["roster"][-1]["plays"][0]["clock"]["displayValue"]="60'"
        with self.assertRaises(InvalidStats):parse(d,m,x)
    def test_extra_time_rejected(self):
        d,m,x=sheet();d["header"]["competitions"][0]["status"]["type"]["name"]="STATUS_FULL_TIME_ET"
        with self.assertRaises(InvalidStats):parse(d,m,x)
    def test_own_goal(self):
        d,m,x=sheet()
        next(s for s in d["rosters"][0]["roster"][1]["stats"] if s["name"]=="totalGoals")["value"]=0
        next(s for s in d["rosters"][0]["roster"][2]["stats"] if s["name"]=="goalAssists")["value"]=0
        next(s for s in d["rosters"][1]["roster"][1]["stats"] if s["name"]=="ownGoals")["value"]=1
        self.assertEqual(sum(r["metrics"]["own_goals"] for r in parse(d,m,x)),1)
    def test_keeper_fallback_separate_metric(self):
        c,h,s=fixture()
        for r in s["11footy"][1]:r["metrics"]["goals_conceded"]=1
        result=evaluate(c,h,s,{})[-1]
        self.assertEqual(result["status"],"measured")
        self.assertEqual(result["metric"],"Γκολ κατά / 90′")
        self.assertTrue(result["lower_better"])
if __name__=="__main__":unittest.main()
