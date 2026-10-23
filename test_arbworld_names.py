"""Offline regression for Arbworld's verified Mgladbach short name."""

from copy import deepcopy
from datetime import datetime
import unittest

import test_pinnodds as writer


class ArbworldNameTests(unittest.TestCase):
    def setUp(self):
        writer.Clock.instant = datetime.fromisoformat("2026-10-21T13:50:00+03:00")

    def tearDown(self):
        writer.Clock.instant = writer.NOW

    def test_short_name_refreshes_turnover_and_preserves_fixture_snapshots(self):
        row = writer.row(home="Stuttgart", away="Borussia Monchengladbach",
                         event_id="pinnodds:1638200343", kickoff="2026-10-21T21:30:00+03:00")
        row[0], row[4], row[7], row[13] = "Germany - Bundesliga", 1.338, 3.51, 84
        initial = deepcopy(row)
        book = writer.FakeSpreadsheet([[], [], row])
        arb = {"date": "2026-10-21 18:30:00", "leage": "German Bundesliga",
               "odds_type": "MATCH_ODDS", "home": "Stuttgart", "away": "Mgladbach",
               "volume_1": 57595.3, "volume_x": 8359.43, "volume_2": 12287.2}
        event = writer.fixture(event_id=1638200343, home="Stuttgart", away="Borussia Monchengladbach",
                               starts=row[76], league_name=row[0])
        _, _, logs = writer.run_main(book, [event], arb_rows=[arb])
        actual = book.main.rows[2]
        self.assertEqual(actual[10:13], [78241.93, 73.6, 26.4])
        for col in [0, 1, 2, 3, 4, 5, 7, 8, 13, 15, 17, 76]:
            self.assertEqual(actual[col], initial[col])
        self.assertEqual(actual[22:25], ["", "", ""])
        self.assertIn("ARBWORLD INDEPENDENT MATCH: 3 Stuttgart vs Borussia Monchengladbach", logs)
        self.assertNotIn("ARBWORLD MATCH NOT FOUND: Stuttgart vs Borussia Monchengladbach", logs)

    def test_late_match_does_not_get_new_turnover(self):
        writer.Clock.instant = datetime.fromisoformat("2026-10-21T21:27:00+03:00")
        row = writer.row(home="Stuttgart", away="Borussia Monchengladbach",
                         event_id="pinnodds:1638200343", kickoff="2026-10-21T21:30:00+03:00")
        row[0], row[10:13] = "Germany - Bundesliga", [1234, 70, 30]
        book = writer.FakeSpreadsheet([[], [], row])
        arb = {"date": "2026-10-21 18:30:00", "leage": "German Bundesliga",
               "odds_type": "MATCH_ODDS", "home": "Stuttgart", "away": "Mgladbach",
               "volume_1": 57595.3, "volume_x": 8359.43, "volume_2": 12287.2}
        writer.run_main(book, [], arb_rows=[arb])
        self.assertEqual(book.main.rows[2][10:13], [1234, 70, 30])


if __name__ == "__main__":
    unittest.main()
