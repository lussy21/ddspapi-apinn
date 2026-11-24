import unittest
from archive_pitch import pitch_from_codes

class PitchLayoutTests(unittest.TestCase):
    def records(self,codes):
        return [{"player_id":i+1,"position_code":v} for i,v in enumerate(codes)]

    def test_everton_4231(self):
        inp=self.records(["F","RM","G","AM","RB","AM-L","CD-L","LB","AM-R","CD-R","LM"])
        formation,ordered=pitch_from_codes(inp)
        self.assertEqual(formation,"4-2-3-1")
        self.assertEqual([x["position_code"] for x in ordered],
            ["G","LB","CD-L","CD-R","RB","LM","RM","AM-L","AM","AM-R","F"])

    def test_monza_3412(self):
        inp=self.records(["G","CD-R","CD","CD-L","RM","CM-R","CM-L","LM","AM","CF-R","CF-L"])
        formation, ordered=pitch_from_codes(inp)
        self.assertEqual(formation,"3-4-1-2")
        self.assertEqual(ordered[0]["position_code"],"G")
        self.assertEqual(ordered[-2]["position_code"],"CF-L")

    def test_french_left_defender_dl(self):
        inp=self.records(["G","DL","CD-L","CD-R","RB","LM","RM","AM-L","AM","AM-R","F"])
        formation,ordered=pitch_from_codes(inp)
        self.assertEqual(formation,"4-2-3-1")
        self.assertEqual(ordered[1]["position_code"],"DL")

    def test_invalid_lineup(self):
        with self.assertRaises(ValueError):
            pitch_from_codes(self.records(["G","CD-L"]))
        with self.assertRaises(ValueError):
            pitch_from_codes(self.records(["G"]*11))
        with self.assertRaises(ValueError):
            pitch_from_codes(self.records(["G"]+["??"]*10))
        arr=self.records(["G"]+["CD"]*10)
        arr[-1]["player_id"]=arr[0]["player_id"]
        with self.assertRaises(ValueError):
            pitch_from_codes(arr)

if __name__=="__main__": unittest.main()
