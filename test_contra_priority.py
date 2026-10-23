"""Exercise generated Sheets expressions and the production writer offline."""

from datetime import datetime
import re
import unittest

from contra_priority import legacy_contra_guarded_expr
from test_early_alerts import Formula, generated_formulas
from test_pinnodds import Clock, FakeSpreadsheet, fixture, row, run_main


class GateFormula(Formula):
    pattern = re.compile(
        r'"(?:[^"]|"")*"|\$[A-Z]+\d+|>=|<=|<>|[=<>+();]|'
        r'\d+(?:,\d+)?|[A-Za-z_][A-Za-z_0-9.]*'
    )

    def __init__(self, text, cells):
        super().__init__(text, cells)
        self.variables = {}

    def atom(self):
        token = self.peek()
        if (token and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9.]*', token)
                and token not in ('TRUE', 'FALSE')
                and self.position + 1 < len(self.tokens)
                and self.tokens[self.position + 1] != '('):
            self.take()
            return ('variable', token)
        return super().atom()

    def evaluate(self, node):
        if node[0] == 'variable':
            return self.variables[node[1]]
        if node[0] == 'call':
            name, args = node[1], node[2]
            if name == 'LET':
                saved = dict(self.variables)
                try:
                    for index in range(0, len(args) - 1, 2):
                        self.variables[args[index][1]] = self.evaluate(args[index + 1])
                    return self.evaluate(args[-1])
                finally:
                    self.variables = saved
            if name == 'IFERROR':
                try:
                    return self.evaluate(args[0])
                except (ArithmeticError, TypeError, ValueError, KeyError):
                    return self.evaluate(args[1])
            if name == 'ISNUMBER':
                value = self.evaluate(args[0])
                return isinstance(value, (float, int)) and not isinstance(value, bool)
            if name == 'AND':
                return all(self.evaluate(arg) for arg in args)
            if name == 'OR':
                return any(self.evaluate(arg) for arg in args)
        return super().evaluate(node)


def evaluate_public(cells):
    formulas = generated_formulas()
    original = formulas['primary_alert_expr']
    for key, value in formulas.items():
        if key.endswith('_public_enabled'):
            original = original.replace(value, 'FALSE')
    return GateFormula(legacy_contra_guarded_expr(original, 1017), cells).result()


class ContraPriorityTests(unittest.TestCase):
    def setUp(self):
        self.basic = {'BI': '🔔 ΚΟΝΤΡΑ', 'E': 2.14, 'L': 62.1, 'N': 69.0}

    def test_retired_plus10_cannot_fall_through_as_simple(self):
        self.assertEqual(evaluate_public(dict(self.basic, N=74.0)), '')
        self.assertEqual(evaluate_public(self.basic), '🔔 ΚΟΝΤΡΑ')
        self.assertEqual(evaluate_public(dict(self.basic, N=72.1)), '')
        self.assertEqual(evaluate_public(dict(self.basic, N=72.099)), '🔔 ΚΟΝΤΡΑ')

    def test_original_strong_rule_blocks_even_when_new_over_entry_price_is_too_high(self):
        self.assertEqual(evaluate_public(dict(self.basic, L=59.9, N=65, J=2.8)), '')
        self.assertEqual(evaluate_public(dict(self.basic, L=60.0, N=65)), '🔔 ΚΟΝΤΡΑ')

    def test_retired_research_helpers_exclude_without_becoming_public(self):
        for column in ('CA', 'CB', 'CC', 'BZ'):
            with self.subTest(column=column):
                self.assertEqual(evaluate_public(dict(self.basic, **{column: 'research'})), '')
        for column in ('BN', 'BT'):
            self.assertEqual(evaluate_public(dict(self.basic, **{column: 'research'})), '🔔 ΚΟΝΤΡΑ')
            self.assertEqual(evaluate_public(dict(self.basic, BQ='CLOSE', **{column: 'research'})), '')

    def test_previous_away_fav60_priority_does_not_reactivate_away_fav60(self):
        cells = dict(self.basic, D='A', E=1.6, L=65, N=70, BM=65)
        self.assertEqual(evaluate_public(cells), '🔔 ΚΟΝΤΡΑ')
        self.assertEqual(evaluate_public(dict(cells, BQ='CLOSE')), '')

    def test_other_public_markets_and_empty_rows_are_unchanged(self):
        for column, alert in (
            ('BG', '🔔 OVER 1.5'), ('BO', '🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ'),
            ('BP', '🔔💎 ΦΑΒΟΡΙ ΓΥΡΙΣΜΑΤΟΣ'), ('BS', '🔔 ΦΑΒ 75+'),
            ('BR', '🔔 ΦΑΒ 60+'), ('BI', '🔔 ΦΑΒΟΡΙ'),
            ('BK', '👀 WATCH ΚΟΝΤΡΑ'),
        ):
            self.assertEqual(evaluate_public({column: alert}), alert)
        self.assertEqual(evaluate_public({}), '')
        self.assertEqual(evaluate_public({'BI': '🔔 ΚΟΝΤΡΑ'}), '')

    def test_historical_primary_examples_survive_without_fitting_observed_extrema(self):
        # E, favorite share, Sofa: actual final pre-kickoff inputs of the eight.
        for opening, share, sofa in (
            (1.885, 68.5, 77), (1.704, 66.0, 72), (2.09, 65.0, 65),
            (2.36, 63.4, 73), (2.09, 62.1, 70), (2.21, 65.5, 66),
            (2.11, 67.6, 68), (2.19, 63.7, 72),
        ):
            self.assertEqual(evaluate_public(dict(self.basic, E=opening, L=share, N=sofa)),
                             '🔔 ΚΟΝΤΡΑ')
        # This ninth row was absent only because historical BI/BJ were missing.
        self.assertEqual(evaluate_public(dict(self.basic, E=2.18, L=68.5, N=75)),
                         '🔔 ΚΟΝΤΡΑ')
        self.assertEqual(evaluate_public(dict(self.basic, E=2.0, L=60.0, N=60.0)),
                         '🔔 ΚΟΝΤΡΑ')

    def test_real_writer_applies_gate_only_to_new_profile_and_preserves_finished_rows(self):
        try:
            for day, filtered in (('2026-10-23', False), ('2026-10-24', True)):
                Clock.instant = datetime.fromisoformat(day + 'T20:30:00+03:00')
                kickoff = day + 'T22:00:00+03:00'
                live = row(event_id='pinnodds:1', kickoff=kickoff)
                old = row(home='Old', away='Fixture', event_id='old', kickoff='2026-10-20T22:00:00+03:00')
                old[14], old[15] = 'unchanged historical alert', '0-2'
                book = FakeSpreadsheet([[], [], live, old])
                run_main(book, [fixture(starts=kickoff)])
                self.assertEqual('LET(rawpick;' in book.main.rows[2][14], filtered)
                self.assertEqual(book.main.rows[3], old)
        finally:
            Clock.instant = datetime.fromisoformat('2026-10-21T20:30:00+03:00')


if __name__ == '__main__':
    unittest.main()
