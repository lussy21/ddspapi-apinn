"""Offline public-visibility and cutover regressions; no provider requests."""

from datetime import datetime
import re
import unittest

from contra_priority import legacy_contra_guarded_expr
from parallel_alerts import parallel_alert_formula
from side_goal_alerts import active_expr, primary_without_goals
from test_contra_priority import GateFormula
from test_early_alerts import generated_formulas
from test_pinnodds import Clock, FakeSpreadsheet, fixture, row, run_main


ACTIVE = {"ΚΟΝΤΡΑ", "ΦΑΒΟΡΙ", "ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ", "ΦΑΒΟΡΙ ΓΥΡΙΣΜΑΤΟΣ",
          "ΦΑΒ 75+", "ΦΑΒ 60+", "Over1.5k", "Over1.5"}
CONFIGS = ACTIVE | {"ΔΥΝΑΤΟ ΦΑΒΟΡΙ", "WATCH ΦΑΒΟΡΙ", "WATCH ΚΟΝΤΡΑ",
                    "ΦΑΒΟΡΙ ΤΖΙΡΟΥ", "ΦΑΒΟΡΙ ΤΖΙΡΟΥ 3X", "ΦΑΒΟΡΙ SOFA+3X",
                    "ΦΑΒΟΡΙ ΠΤΩΣΗ 2%", "ΦΑΒΟΡΙ 84+P60", "ΤΖΙΡΟΣ ↑"}


class ParallelFormula(GateFormula):
    pattern = re.compile(GateFormula.pattern.pattern.replace('[=<>+();]', '[=<>+&();-]'))

    def addition(self):
        node = self.atom()
        while self.peek() in ("+", "&", "-"):
            operator = self.take()
            node = ({"+": "add", "&": "concat", "-": "subtract"}[operator], node, self.atom())
        return node

    def evaluate(self, node):
        if node[0] == "concat":
            return str(self.evaluate(node[1])) + str(self.evaluate(node[2]))
        if node[0] == "subtract":
            return self.evaluate(node[1]) - self.evaluate(node[2])
        if node[0] == "call" and node[1] in ("LEFT", "FIND"):
            values = [self.evaluate(arg) for arg in node[2]]
            if node[1] == "LEFT":
                return values[0][:int(values[1])]
            return values[1].index(values[0]) + 1
        return super().evaluate(node)


def expression(active=ACTIVE):
    old = generated_formulas()["primary_alert_expr"]
    old = legacy_contra_guarded_expr(primary_without_goals(old, 1017), 1017)
    formula = parallel_alert_formula(old, 1017)
    for name in CONFIGS:
        formula = formula.replace(active_expr(name), "TRUE" if name in active else "FALSE")
    admin = active_expr("WATCH ΚΟΝΤΡΑ").replace('="ACTIVE"', '="ADMIN_ONLY"')
    return formula.replace(admin, "TRUE")


class ParallelAlertTests(unittest.TestCase):
    def evaluate(self, cells, active=ACTIVE):
        return ParallelFormula(expression(active), {"E": 1.6, **cells}).result()

    def test_two_primary_alerts_show_without_any_over_and_preserve_head_strength(self):
        result = self.evaluate({"BO": "🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ", "BS": "🔔 ΦΑΒ 75+",
                                "BX": "8,0/10 · EARLY"})
        self.assertEqual(result, "🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ · 8,0/10 | 🔔 ΦΑΒ 75+")

    def test_all_independent_signals_keep_both_goal_identities(self):
        cells = {"BG": "🔔 OVER 1.5", "BH": "🔔 OVER 1.5", "CE": "latched",
                 "BO": "🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ", "BP": "🔔💎 ΦΑΒΟΡΙ ΓΥΡΙΣΜΑΤΟΣ",
                 "BS": "🔔 ΦΑΒ 75+", "BR": "🔔 ΦΑΒ 60+", "BI": "🔔 ΦΑΒΟΡΙ"}
        parts = self.evaluate(cells).split(" | ")
        self.assertEqual(len(parts), 7)
        self.assertEqual(len(parts), len(set(parts)))
        self.assertEqual(parts[-2:], ["🔔 Over1.5k", "🔔 Over1.5"])
        self.assertIn("🔔 ΦΑΒΟΡΙ", parts)

    def test_research_helpers_do_not_leak_and_retained_contra_guard_still_applies(self):
        cells = {"BG": "🔔🔥 ΔΥΝΑΤΟ ΦΑΒΟΡΙ", "CA": "research", "CB": "research",
                 "CC": "research", "BZ": "research", "BN": "research", "BT": "research",
                 "BQ": "CLOSE", "BK": "👀 WATCH ΦΑΒΟΡΙ"}
        self.assertEqual(self.evaluate(cells), "")
        contra = {"E": 2.14, "L": 62.1, "N": 69, "BI": "🔔 ΚΟΝΤΡΑ"}
        self.assertEqual(self.evaluate(contra), "🔔 ΚΟΝΤΡΑ")
        self.assertEqual(self.evaluate({**contra, "CA": "research"}), "")
        self.assertEqual(self.evaluate({**contra, "BS": "🔔 ΦΑΒ 75+"}), "🔔 ΦΑΒ 75+")

    def test_core_entry_and_continuation_do_not_duplicate_and_watch_stays_subordinate(self):
        cells = {"BI": "🔔 ΦΑΒΟΡΙ", "BJ": "🔔 ΦΑΒΟΡΙ", "BK": "👀 WATCH ΦΑΒΟΡΙ",
                 "BS": "🔔 ΦΑΒ 75+"}
        result = self.evaluate(cells)
        self.assertEqual(result, "🔔 ΦΑΒ 75+ | 🔔 ΦΑΒΟΡΙ")
        self.assertEqual(self.evaluate({"BK": "👀 WATCH ΚΟΝΤΡΑ"}), "👀 WATCH ΚΟΝΤΡΑ")

    def test_disabled_configuration_and_opening_floor_remain_closed(self):
        self.assertEqual(self.evaluate({"BO": "🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ"}, set()), "")
        self.assertEqual(self.evaluate({"E": 1.389, "BS": "🔔 ΦΑΒ 75+", "CE": "latched"}), "")
        self.assertEqual(self.evaluate({"E": "", "BS": "🔔 ΦΑΒ 75+"}), "")

    def test_real_writer_uses_new_formula_only_for_upcoming_cutover_fixtures(self):
        try:
            for day in ("2026-10-26", "2026-10-27"):
                Clock.instant = datetime.fromisoformat(day + "T20:30:00+02:00")
                kickoff = day + "T22:00:00+02:00"
                live = row(event_id="pinnodds:1", kickoff=kickoff)
                old = row(home="Old", away="Fixture", event_id="old", kickoff="2026-10-25T22:00:00+02:00")
                old[14], old[15] = "historical alert", "0-2"
                book = FakeSpreadsheet([[], [], live, old])
                run_main(book, [fixture(starts=kickoff)])
                self.assertEqual("LET(rawhead;" in book.main.rows[2][14], day == "2026-10-27")
                self.assertEqual(book.main.rows[3], old)
        finally:
            Clock.instant = datetime.fromisoformat("2026-10-21T20:30:00+03:00")


if __name__ == "__main__":
    unittest.main()
