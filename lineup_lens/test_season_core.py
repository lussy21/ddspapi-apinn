import unittest
from season_core import normalize_official, season_starts, InvalidXI

def sample():
    match = {
        "id": "match_foo123", "season_id": "season_foo123",
        "competition_id": "competition_foo123", "utc_date": "2026-11-23T18:00:00Z",
        "home_team": {"id": "team_home123"}, "away_team": {"id": "team_away123"},
    }
    lineup = {
        "type": "team_sheet", "confirmed": True,
        "home": {"id": "team_home123", "starting_xi": [
            {"id": "player_home%02d" % i, "name": "H%s" % i} for i in range(11)
        ]},
        "away": {"id": "team_away123", "starting_xi": [
            {"id": "player_away%02d" % i, "name": "A%s" % i} for i in range(11)
        ]},
    }
    return match, lineup

class SeasonCoreTests(unittest.TestCase):
    def test_one_official_xi_has_11_per_team(self):
        game, xi = sample()
        report = normalize_official(game, xi, "soccer-data:match_foo123")
        self.assertEqual(len(report["teams"]), 2)
        self.assertEqual(len(report["teams"][0]["starters"]), 11)

    def test_no_predicted_lineups(self):
        game, xi = sample()
        xi["confirmed"] = False
        with self.assertRaises(InvalidXI):
            normalize_official(game, xi, "soccer-data:match_foo123")

    def test_no_incomplete_xi(self):
        game, xi = sample()
        xi["away"]["starting_xi"].pop()
        with self.assertRaises(InvalidXI):
            normalize_official(game, xi, "soccer-data:match_foo123")

    def test_no_repeated_player(self):
        game, xi = sample()
        xi["home"]["starting_xi"][4]["id"] = xi["home"]["starting_xi"][0]["id"]
        with self.assertRaises(InvalidXI):
            normalize_official(game, xi, "soccer-data:match_foo123")

    def test_no_double_count_for_repeat_import(self):
        game, xi = sample()
        report = normalize_official(game, xi, "soccer-data:match_foo123")
        stats = season_starts([report, report])
        self.assertEqual(stats[("season_foo123", "competition_foo123",
                                "team_home123", "player_home00")], {
            "starts": 1, "verified_games": 1,
        })

if __name__ == "__main__":
    unittest.main()
