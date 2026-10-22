"""Offline regressions: SofaScore fixtures must survive an APINN outage.

Execute the real collector functions with fake HTTP/Sheets boundaries. No
credentials, live HTTP, actor runs or real Sheet writes are possible here.
"""

import ast
from copy import deepcopy
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
import re
import types
import unicodedata
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo


ATHENS = ZoneInfo("Europe/Athens")
NOW = datetime.fromisoformat("2026-10-22T12:30:00+03:00")


def sheet_row(key="pinnodds:99", home="Bayern Munich", away="Arsenal", kickoff="2026-10-22T22:00:00+03:00", side="H", vote=""):
    row = [""] * 82
    row[:4] = ["UEFA - Champions League", home, away, side]
    row[13], row[17], row[76] = vote, key, kickoff
    return row


class FakeSheet:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.writes = []

    def get_all_values(self):
        return deepcopy(self.rows)

    def append_rows(self, rows, **kwargs):
        self.rows.extend(deepcopy(rows))

    def batch_update(self, updates, **kwargs):
        self.writes.extend(deepcopy(updates))
        for item in updates:
            col, number = re.fullmatch(r"([A-Z]+)(\d+)", item["range"]).groups()
            self.rows[int(number)-1][ord(col)-ord("A")] = item["values"][0][0]


class SofaCandidateTests(unittest.TestCase):
    def load_collector(self, status=502, board=None):
        source = ast.parse(Path(__file__).with_name("sofascore_runner-1.py").read_text())
        ns = {"datetime": datetime, "timedelta": timedelta, "ZoneInfo": ZoneInfo,
              "re": re, "unicodedata": unicodedata, "SequenceMatcher": SequenceMatcher}
        nodes = []
        for node in source.body:
            if isinstance(node, ast.FunctionDef):
                nodes.append(node)
            elif isinstance(node, ast.Assign):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                for name in node.targets:
                    if isinstance(name, ast.Name):
                        ns[name.id] = value
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "sofascore_runner-1.py", "exec"), ns)
        ns["GREECE_TZ"], ns["UTC_TZ"] = ATHENS, ZoneInfo("UTC")
        # Keep this boundary fake; matching itself is independently covered by
        # the existing Pinnodds handoff regressions.
        ns["fallback_sheet_item"] = lambda match, items: None
        error = type("RequestException", (Exception,), {})
        def raise_for_status():
            if status >= 400:
                raise error("simulated provider outage")
        reply = types.SimpleNamespace(raise_for_status=raise_for_status, json=lambda: deepcopy(board or []))
        ns["requests"] = types.SimpleNamespace(RequestException=error, get=Mock(return_value=reply))
        self.ns = ns
        return ns

    def collect(self, rows, status=502, board=None, now=NOW, direct_fails=False):
        ns = self.load_collector(status, board)
        cache = FakeSheet([["APINN EVENT ID", "SOFA EVENT ID", "HOME", "AWAY", "DATE"]])
        sheet = FakeSheet([[], []] + rows)
        book = types.SimpleNamespace(worksheet=lambda title: cache)
        events = []
        for number, row in enumerate(rows, 1):
            if not row[76]:
                continue
            events.append({"id": 100 + number, "startTimestamp": int(datetime.fromisoformat(row[76]).timestamp()),
                           "homeTeam": {"name": row[1]}, "awayTeam": {"name": row[2]}})
        ns["fetch_sofa_schedule"] = Mock(side_effect=RuntimeError("simulated SofaScore HTTP 404")) if direct_fails else Mock(return_value=events)
        ns["fetch_votes"] = Mock(side_effect=lambda token, ids, **kw: [
            {"eventId": i, "votes": {"vote": {"vote1": 70, "voteX": 10, "vote2": 20}}} for i in ids])
        ns["fetch_fixtures"] = Mock(return_value=events) if direct_fails else Mock(side_effect=AssertionError("No paid actor allowed"))
        ns["fetch_all_fixtures"] = Mock(side_effect=AssertionError("No paid actor allowed"))
        result = ns["update_votes"](sheet, sheet.get_all_values(), book,
                                    "test-token", "test-primary-key", now,
                                    only_blank=True, allow_paid_fallback=direct_fails,
                                    include_next_morning=True)
        return ns, sheet, cache, result

    def test_outage_still_writes_votes_and_creates_result_cache(self):
        ns, sheet, cache, ok = self.collect([sheet_row()])
        self.assertTrue(ok)
        self.assertEqual(sheet.rows[2][13], 70)
        self.assertEqual(cache.rows[1][:4], ["pinnodds:99", 101, "Bayern Munich", "Arsenal"])
        self.assertEqual(len(sheet.writes), 1)
        self.assertEqual(ns["requests"].get.call_count, 1)
        ns["fetch_fixtures"].assert_not_called()
        ns["fetch_all_fixtures"].assert_not_called()

    def test_primary_and_sheet_candidate_produce_one_cache_entry(self):
        row = sheet_row(key="99")
        primary = {"event_id": 99, "runner_home": row[1], "runner_away": row[2],
                   "starts": row[76], "league_name": row[0]}
        ns, sheet, cache, _ = self.collect([row], status=200, board=[primary, dict(primary)])
        self.assertEqual(len(cache.rows), 2)
        self.assertEqual(ns["fetch_votes"].call_args.args[1], [101])
        self.assertEqual([u["range"] for u in sheet.writes], ["N3"])

    def test_missing_primary_fixture_is_recovered_from_sheet(self):
        ns, sheet, cache, ok = self.collect([sheet_row()], status=200, board=[])
        self.assertTrue(ok)
        self.assertEqual(len(cache.rows), 2)

    def test_primary_outage_and_sofa_block_use_existing_bounded_backup(self):
        ns, sheet, cache, ok = self.collect([sheet_row()], direct_fails=True)
        self.assertTrue(ok)
        self.assertEqual(sheet.rows[2][13], 70)
        self.assertEqual(len(cache.rows), 2)
        ns["fetch_fixtures"].assert_called_once_with("test-token", "2026-10-22", {7}, timeout=75, attempts=1)
        ns["fetch_all_fixtures"].assert_not_called()

    def test_started_undated_and_invalid_favorite_rows_are_not_requested(self):
        past = sheet_row(kickoff="2026-10-22T11:00:00+03:00")
        undated = sheet_row(key="undated", kickoff="")
        pending = sheet_row(key="pending", side="")
        ns, sheet, cache, _ = self.collect([past, undated, pending])
        self.assertEqual(sheet.writes, [])
        self.assertEqual(len(cache.rows), 1)
        ns["fetch_sofa_schedule"].assert_not_called()
        ns["fetch_votes"].assert_not_called()

    def test_manual_votes_are_preserved_and_away_favorite_uses_away_votes(self):
        manual = sheet_row(key="manual", vote=82)
        away = sheet_row(key="away", home="Como", away="Manchester United", side="A")
        ns, sheet, cache, _ = self.collect([manual, away])
        self.assertEqual(sheet.rows[2][13], 82)
        self.assertEqual(sheet.rows[3][13], 20)
        self.assertEqual([u["range"] for u in sheet.writes], ["N4"])
        self.assertEqual(len(cache.rows), 3)
        self.assertEqual(ns["fetch_votes"].call_args.args[1], [102])

    def test_all_manual_votes_still_create_result_links_without_vote_requests(self):
        ns, sheet, cache, ok = self.collect([sheet_row(vote=82)])
        self.assertTrue(ok)
        self.assertEqual(sheet.rows[2][13], 82)
        self.assertEqual(sheet.writes, [])
        self.assertEqual(len(cache.rows), 2)
        self.assertEqual(cache.rows[1][0], "pinnodds:99")
        ns["fetch_votes"].assert_not_called()

    def test_next_morning_fixture_is_included_but_next_evening_is_not(self):
        overnight = sheet_row(key="overnight", kickoff="2026-10-23T02:00:00+03:00")
        next_evening = sheet_row(key="tomorrow", kickoff="2026-10-23T22:00:00+03:00")
        ns, sheet, cache, _ = self.collect([overnight, next_evening])
        self.assertEqual([u["range"] for u in sheet.writes], ["N3"])
        self.assertEqual(len(cache.rows), 2)
        self.assertEqual(cache.rows[1][4], "2026-10-22")


if __name__ == "__main__":
    unittest.main()
