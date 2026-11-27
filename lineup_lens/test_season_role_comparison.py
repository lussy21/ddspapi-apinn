import unittest
from season_role_comparison import findings

def data():
    current=[{"id":i,"name":str(i)} for i in range(1,11)]+[{"id":99,"name":"Welbeck"}]
    rows=[]
    for mid in range(1,12):
        for i in range(1,12):
            pid=i
            if i==11 and mid>6:pid=99
            k="G" if i==1 else "D" if i<=5 else "M" if i<=10 else "F"
            rows.append({"match_id":mid,"player_id":pid,"position":k,"started":True,"minutes":90 if pid!=99 else 25,
                "player_name":"Joao" if pid==11 else "Welbeck" if pid==99 else str(pid),"metrics":{"goals":1 if pid==11 else 0,"assists":0}})
    return current,rows
class TestSeasonRole(unittest.TestCase):
    def test_comparison(self):
        c,r=data();a=findings(c,r)
        self.assertTrue(any(x["line"]=="F" and x["kind"]=="attention" and "Welbeck" in x["text"] for x in a))
        self.assertTrue(any(x["line"]=="G" and x["kind"]=="neutral" for x in a))
    def test_substitute_with_production_not_flagged(self):
        c,r=data()
        for x in r:
            if x["player_id"]==99:x["metrics"]["goals"]=1
        self.assertFalse(any(x["line"]=="F" and x["kind"]=="attention" for x in findings(c,r)))
    def test_missing_current_identity(self):
        c,r=data();c[-1]["unresolved"]=True
        self.assertEqual(findings(c,r),[])
    def test_missing_metric_never_zero(self):
        c,r=data()
        for x in r:
            if x["player_id"]==99:x["metrics"]["goals"]=None
        self.assertFalse(any(x["line"]=="F" for x in findings(c,r)))
if __name__=="__main__":unittest.main()
