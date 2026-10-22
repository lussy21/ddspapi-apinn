"""Evaluate the real generated selection/tracking formulas without live APIs."""

import ast
from datetime import timedelta
from pathlib import Path
import re
import unittest

from test_pinnodds import Clock, FakeSpreadsheet, NOW, fixture, row, run_main


def generated_formulas():
    tree = ast.parse(Path(__file__).with_name("main.py").read_text())
    wanted = {"watch_fav_public_expr", "primary_alert_expr",
              "alert_count_formula", "alert_list_formula"}
    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and (node.targets[0].id in wanted
             or node.targets[0].id.endswith("_public_enabled"))
    ]
    ns = {"row_number": 1017}
    exec(compile(ast.Module(body=sorted(assignments, key=lambda n: n.lineno),
                            type_ignores=[]), "main.py", "exec"), ns)
    return ns


class Formula:
    """Small generic parser for the IF/boolean/TEXTJOIN formula subset."""
    pattern = re.compile(r'"(?:[^"]|"")*"|\$[A-Z]+\d+|>=|<=|<>|[=<>+();]|'
                         r'\d+(?:,\d+)?|[A-Z_][A-Z_0-9.]*')

    def __init__(self, text, cells):
        self.tokens = self.pattern.findall(text.lstrip("="))
        self.position = 0
        self.cells = cells

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.position += 1
        return token

    def expression(self):
        node = self.addition()
        if self.peek() in ("=", "<>", ">", "<", ">=", "<="):
            node = ("compare", self.take(), node, self.addition())
        return node

    def addition(self):
        node = self.atom()
        while self.peek() == "+":
            self.take()
            node = ("add", node, self.atom())
        return node

    def atom(self):
        token = self.take()
        if token.startswith('"'):
            return ("value", token[1:-1].replace('""', '"'))
        if token.startswith("$"):
            return ("cell", re.match(r"\$([A-Z]+)", token)[1])
        if token[0].isdigit():
            return ("value", float(token.replace(",", ".")))
        if token in ("TRUE", "FALSE") and self.peek() != "(":
            return ("value", token == "TRUE")
        if self.take() != "(":
            raise AssertionError("Expected function call")
        arguments = [self.expression()]
        while self.peek() == ";":
            self.take()
            arguments.append(self.expression())
        if self.take() != ")":
            raise AssertionError("Unbalanced formula")
        return ("call", token, arguments)

    def evaluate(self, node):
        kind = node[0]
        if kind == "value":
            return node[1]
        if kind == "cell":
            return self.cells.get(node[1], "")
        if kind == "add":
            return self.evaluate(node[1]) + self.evaluate(node[2])
        if kind == "compare":
            op, left, right = node[1], self.evaluate(node[2]), self.evaluate(node[3])
            return {"=": lambda: left == right, "<>": lambda: left != right,
                    ">": lambda: left > right, "<": lambda: left < right,
                    ">=": lambda: left >= right, "<=": lambda: left <= right}[op]()
        name, args = node[1], node[2]
        if name == "IF":
            return self.evaluate(args[1] if self.evaluate(args[0]) else args[2])
        values = [self.evaluate(arg) for arg in args]
        if name == "AND":
            return all(values)
        if name == "OR":
            return any(values)
        if name == "NOT":
            return not values[0]
        if name == "REGEXMATCH":
            return re.search(values[1], str(values[0])) is not None
        if name == "TO_TEXT":
            return str(values[0])
        if name == "TEXTJOIN":
            return values[0].join(str(value) for value in values[2:]
                                  if value != "" or not values[1])
        raise AssertionError("Unsupported function: " + name)

    def result(self):
        tree = self.expression()
        if self.peek() is not None:
            raise AssertionError("Unconsumed formula tokens")
        return self.evaluate(tree)


class EarlyAlertTests(unittest.TestCase):
    def setUp(self):
        self.formulas = generated_formulas()
        self.alerts = {
            "BO": "🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ",
            "BP": "🔔💎 ΦΑΒΟΡΙ ΓΥΡΙΣΜΑΤΟΣ",
            "BS": "🔔 ΦΑΒ 75+",
            "BR": "🔔 ΦΑΒ 60+",
        }

    def evaluate(self, name, cells):
        text = self.formulas[name]
        for key, value in self.formulas.items():
            if key.endswith("_public_enabled"):
                text = text.replace(value, "FALSE")
        return Formula(text, cells).result()

    def test_four_active_rules_open_before_close_and_keep_same_close_results(self):
        for column, alert in self.alerts.items():
            for phase in ("", "CLOSE"):
                with self.subTest(column=column, phase=phase):
                    self.assertEqual(self.evaluate("primary_alert_expr",
                                                  {column: alert, "BQ": phase}), alert)

    def test_internal_count_and_history_include_early_signals(self):
        for column, alert in self.alerts.items():
            with self.subTest(column=column):
                self.assertEqual(self.evaluate("alert_count_formula", {column: alert}), 1)
                self.assertEqual(self.evaluate("alert_list_formula", {column: alert}), alert)

    def test_time_alone_never_creates_a_signal(self):
        for phase in ("", "CLOSE"):
            self.assertEqual(self.evaluate("primary_alert_expr", {"BQ": phase}), "")
            self.assertEqual(self.evaluate("alert_count_formula", {"BQ": phase}), 0)

    def test_public_priority_and_research_suppression_are_preserved(self):
        cells = dict(self.alerts)
        self.assertEqual(self.evaluate("primary_alert_expr", cells), self.alerts["BO"])
        self.assertEqual(self.evaluate("primary_alert_expr",
                                      dict(cells, BG="🔔 OVER 1.5")), "🔔 OVER 1.5")
        retired = {"BG": "🔔🔥 ΔΥΝΑΤΟ ΦΑΒΟΡΙ", "BN": "turnover", "BT": "rise",
                   "CA": "3X", "CB": "sofa3X", "CC": "drop", "BZ": "84+",
                   "BK": "👀 WATCH ΦΑΒΟΡΙ", "BQ": "CLOSE"}
        self.assertEqual(self.evaluate("primary_alert_expr", retired), "")

    def test_writer_keeps_final_snapshot_marker_independent_of_early_eligibility(self):
        for instant, expected in ((NOW, ""), (NOW + timedelta(minutes=80), "CLOSE")):
            Clock.instant = instant
            live = row(event_id="pinnodds:1")
            live[4:10] = [1.6, "", 1.6, 2.2, "", 2.2]
            book = FakeSpreadsheet([[], [], live])
            run_main(book, [fixture()])
            self.assertEqual(book.main.rows[2][68], expected)
            self.assertIn(self.formulas["primary_alert_expr"].replace("1017", "3"),
                          book.main.rows[2][14])


if __name__ == "__main__":
    unittest.main()
