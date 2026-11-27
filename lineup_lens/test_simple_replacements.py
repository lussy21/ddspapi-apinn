import unittest
from simple_replacements import pairs,decorate,current_codes,profile
def setup():
    codes=["G","LB","CD-L","CD-R","RB","CM-L","CM-R","AM-L","AM","AM-R","F"]
    hist=[dict(match_id=m,player_id=i,player_name="P"+str(i),position_code=c) for m in range(10) for i,c in enumerate(codes,1)]
    current=[dict(id=i,name="P"+str(i),code=c) for i,c in enumerate(codes,1)]
    current[-2]=dict(id=99,name="New",code="RF")
    return current,hist
class SimpleTest(unittest.TestCase):
    def test_side_pair(self):
        c,h=setup();a=pairs(c,h)
        self.assertEqual(len(a),1);self.assertEqual(a[0]["old"]["id"],10);self.assertEqual(a[0]["new"]["id"],99)
    def test_not_absent(self):
        c,h=setup();c[8]=dict(id=10,name="P10",code="AM")
        self.assertFalse(any(x["old"]["id"]==10 for x in pairs(c,h)))
    def test_no_guess_unknown_identity(self):
        c,h=setup();c[-2]["unresolved"]=True
        self.assertEqual(pairs(c,h),[])
    def test_broad_verified_order(self):
        c,h=setup()
        for p in c[1:5]:p["code"]="D"
        self.assertEqual(current_codes(c,"4-2-3-1")[2]["code"],"CD-L")
    def test_missing_is_not_zero(self):
        p=profile([dict(match_id=1,minutes=90,metrics={"goals":None,"assists":0})],"CF")
        self.assertIsNone(p["metrics"][0]["value"]);self.assertEqual(p["metrics"][1]["value"],0)
    def test_production_risk(self):
        c,h=setup();p=pairs(c,h)[0]
        rows=lambda g,n:[dict(match_id=i,minutes=90,metrics={"goals":g,"assists":0}) for i in range(n)]
        a=decorate(p,{"11footy":{10:rows(1,6),99:rows(0,3)}})
        self.assertIn("Πιθανή απώλεια",a["summary"])
    def test_different_sources_not_mixed(self):
        c,h=setup();p=pairs(c,h)[0]
        a=decorate(p,{"A":{10:[dict(match_id=1,minutes=90,metrics={"goals":3,"assists":0})]},"B":{99:[dict(match_id=1,minutes=90,metrics={"goals":0,"assists":0})]}})
        self.assertFalse("metrics" in a["old"] and "metrics" in a["new"])
if __name__=="__main__":unittest.main()
