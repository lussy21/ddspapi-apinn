"""Offline goal-market regression tests; collector/providers are always mocked."""

import ast
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from alert_formulas import legacy_alert_helper_updates
import side_goal_alerts as s
from contra_priority import legacy_contra_guarded_expr
from test_contra_priority import GateFormula
from test_early_alerts import generated_formulas
from test_pinnodds import Clock, FakeSpreadsheet, fixture, row, run_main


NOW = datetime.fromisoformat("2026-10-24T20:30:00+03:00")


def eligible():
    r = row(event_id="pinnodds:1", kickoff="2026-10-24T22:00:00+03:00")
    r[4:7] = [1.8, 1.8, 1.8]
    r[10:12] = [200, 80]
    r[19:21] = [100, 80]
    return r


def history_functions():
    tree = ast.parse(Path(__file__).with_name("alert_history.py").read_text())
    names = {"normalize_display_alert", "col_letter", "referenced_columns", "make_snapshot", "now_athens", "read_alert_inputs"}
    ns = {"re": re, "datetime": datetime, "ZoneInfo": __import__("zoneinfo").ZoneInfo}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "alert_history.py", "exec"), ns)
    return ns


class SideGoalsTests(unittest.TestCase):
    def test_frozen_rule_accepts_boundary_and_has_no_sofa_requirement(self):
        r = eligible()
        r[13] = ""
        ev = s.flow_evidence(r, NOW)
        self.assertIsNotNone(ev)
        self.assertEqual(ev["new_money11"], 80)
        self.assertEqual(ev["minutes_before"], 90)
        self.assertIsNotNone(s.flow_evidence(r, NOW + timedelta(minutes=85)))
        self.assertIsNone(s.flow_evidence(r, NOW - timedelta(seconds=1)))
        self.assertIsNone(s.flow_evidence(r, NOW + timedelta(minutes=85, seconds=1)))

    def test_uses_incremental_share_not_total_favorite_share(self):
        r = eligible()
        r[11], r[20] = 79, 80
        self.assertIsNone(s.flow_evidence(r, NOW))
        r[11], r[20] = 75, 50
        self.assertEqual(s.flow_evidence(r, NOW)["new_money11"], 100)
        r[11] = 76
        self.assertIsNone(s.flow_evidence(r, NOW))  # impossible >100%, not clipped

    def test_current_odds_can_rise_and_excessive_drop_is_rejected(self):
        r = eligible()
        r[6] = 2
        self.assertIsNotNone(s.flow_evidence(r, NOW))
        r[6] = 1.7
        self.assertIsNone(s.flow_evidence(r, NOW))

    def test_scope_opening_missing_inputs_and_settled_games(self):
        for index, value in ((0, "Argentina - Liga Pro"), (0, "Germany - Bundesliga 2"),
                             (3, ""), (4, 1.389), (5, ""), (6, 0), (10, 100),
                             (19, 0), (20, ""), (15, "0-0"), (76, "not a timestamp")):
            r = eligible(); r[index] = value
            self.assertIsNone(s.flow_evidence(r, NOW), (index, value))

    def test_greek_formatted_data_and_timestamps(self):
        r = eligible()
        r[4:7] = ["1,80", "1,80", "1,80"]
        r[10:12] = ["2.000,00", "80%"]
        r[19:21] = ["1.000,00", "80"]
        self.assertEqual(s.flow_evidence(r, NOW)["new_money11"], 80)

    def test_first_opening_is_immutable_and_fixture_reuse_does_not_inherit(self):
        r = eligible(); updates = s.collect_flow_updates([[], [], r], NOW, {3})
        self.assertEqual(len(updates), 1)
        r.extend(updates[0]["values"][0])
        r[11] = 1
        self.assertEqual(s.collect_flow_updates([[], [], r], NOW + timedelta(minutes=10), {3}), [])
        r[17] = "different fixture"
        reset = s.collect_flow_updates([[], [], r], NOW + timedelta(minutes=10), set())
        self.assertEqual(reset, [{"range": "CE3:CG3", "values": [["", "", ""]]}])

    def test_no_signal_from_stale_cycle_without_both_fresh_sources(self):
        self.assertEqual(s.collect_flow_updates([[], [], eligible()], NOW, set()), [])
        updates = [{"range": "G3"}, {"range": "K3:M3"}, {"range": "G4"}, {"range": "K5:M5"}]
        self.assertEqual(s.freshly_updated_rows(updates), {3})

    def test_flow_never_continues_legacy_over_buffer(self):
        formula = legacy_alert_helper_updates(3, use_over15=True, side_goals=True)[1]["values"][0][0]
        regex = re.search(r'REGEXMATCH\(\$BF3;"([^"]+)"\)', formula)[1]
        for text in (s.LEGACY_KEY, s.LEGACY_DISPLAY, "🔔 ΦΑΒ 75+ | " + s.LEGACY_DISPLAY):
            self.assertTrue(re.search(regex, text), text)
        for text in (s.FLOW_DISPLAY, "🔔 ΦΑΒ 75+ | " + s.FLOW_DISPLAY):
            self.assertFalse(re.search(regex, text), text)

    def test_remove_goal_priority_preserves_other_primary_and_contra_guard(self):
        f = generated_formulas(); expr = s.primary_without_goals(f["primary_alert_expr"], 1017)
        for k, v in f.items():
            if k.endswith("_public_enabled"):
                expr = expr.replace(v, "FALSE")
        expr = legacy_contra_guarded_expr(expr, 1017)
        cells = {"BG": s.LEGACY_KEY, "BS": "🔔 ΦΑΒ 75+", "E": 1.6, "L": 55, "N": 60}
        self.assertEqual(GateFormula(expr, cells).result(), "🔔 ΦΑΒ 75+")
        del cells["BS"]
        self.assertEqual(GateFormula(expr, cells).result(), "")
        cells["BI"] = "🔔 ΚΟΝΤΡΑ"
        self.assertEqual(GateFormula(expr, cells).result(), "")

    def test_goal_names_do_not_mix_identities_and_history_keeps_all_markets(self):
        text = "🔔 ΦΑΒ 75+ · 8,3/10 | " + s.LEGACY_DISPLAY + " | " + s.FLOW_DISPLAY
        expected = "🔔 ΦΑΒ 75+ | " + s.LEGACY_DISPLAY + " | " + s.FLOW_DISPLAY
        ns = history_functions()
        self.assertEqual(ns["normalize_display_alert"](text), expected)
        self.assertTrue(s.has_legacy_over(expected))
        self.assertFalse(s.has_legacy_over(s.FLOW_DISPLAY))
        self.assertTrue(s.is_goal_alert(s.LEGACY_DISPLAY))
        self.assertTrue(s.is_goal_alert(s.FLOW_DISPLAY))
        r = eligible(); r.extend([s.FLOW_DISPLAY, NOW.isoformat(), "evidence"])
        self.assertEqual(ns["make_snapshot"](r, "=1")["values"]["CG"], "evidence")

    def test_actual_writer_installs_parallel_display_only_from_cutover(self):
        try:
            Clock.instant = NOW
            r = eligible()
            book = FakeSpreadsheet([[], [], r])
            _, _, log = run_main(book, [fixture(starts=r[76])])
            display = book.main.rows[2][14]
            self.assertIn(s.LEGACY_DISPLAY, display)
            self.assertIn("$CE3", display)
            self.assertIn("LET(rawpick;", display)
            self.assertNotIn("FLOW OVER OPENINGS:", log)  # missing fresh turnover
        finally:
            Clock.instant = datetime.fromisoformat("2026-10-21T20:30:00+03:00")


if __name__ == "__main__":
    unittest.main()
