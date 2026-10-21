"""Offline regression tests. No credentials, HTTP or live Sheets are used."""

import ast
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta
import io
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import patch

import pinnodds as p

NOW = datetime.fromisoformat("2026-10-21T20:30:00+03:00")


class Clock(datetime):
    instant = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


def fixture(event_id=1, home="Home", away="Away", starts="2026-10-21T22:00:00+03:00", **overrides):
    result = {"event_id": event_id, "sport_id": 1, "event_type": "prematch",
              "league_name": "UEFA - Champions League", "home": home, "away": away,
              "starts": starts, "parent_id": None,
              "periods": {"num_0": {"number": 0, "status": "open",
                  "money_line": {"home": 1.8, "away": 4.0, "draw": 3.5},
                  "spreads": {"-0.5": {"hdp": -0.5, "home": 1.8, "away": 2.1},
                              "0.5": {"hdp": 0.5, "home": 1.2, "away": 4.4}}}}}
    result.update(overrides)
    return result


FRESH = {"status": "fresh", "board": "prematch", "age_ms": "0"}


def board(events):
    return {"sport_id": 1, "events": events}


def normalized(events):
    return p.normalize_board(board(events), FRESH, Clock.instant, lambda _: True)


def row(home="Home", away="Away", event_id="", kickoff="2026-10-21T22:00:00+03:00", side="H"):
    result = [""] * 82
    result[:4] = ["UEFA - Champions League", home, away, side]
    result[17], result[76] = event_id, kickoff
    return result


class MissingWorksheet(Exception):
    pass


class FakeSheet:
    def __init__(self, rows=None):
        self.rows = deepcopy(rows or [])
        self.writes = []

    def get_all_values(self):
        return deepcopy(self.rows)

    def get(self, address):
        return [self.rows[1][:4]] if len(self.rows) > 1 else []

    def batch_update(self, updates, value_input_option=None):
        self.writes.extend(deepcopy(updates))
        for update in updates:
            address = update["range"]
            letter, start_row = re.match(r"([A-Z]+)(\d+)", address).groups()
            start_col = 0
            for ch in letter:
                start_col = start_col * 26 + ord(ch) - 64
            for offset, values in enumerate(update["values"]):
                index = int(start_row) - 1 + offset
                while len(self.rows) <= index:
                    self.rows.append([])
                while len(self.rows[index]) < start_col - 1 + len(values):
                    self.rows[index].append("")
                self.rows[index][start_col - 1:start_col - 1 + len(values)] = values


class FakeSpreadsheet:
    def __init__(self, rows=None):
        self.main = FakeSheet(rows)
        self.state = None
        self.structure_writes = []

    def worksheet(self, title):
        if title == "PINNACLE":
            return self.main
        if title == p.STATE_TITLE and self.state is not None:
            return self.state
        raise MissingWorksheet(title)

    def batch_update(self, body):
        self.structure_writes.append(deepcopy(body))
        self.state = FakeSheet()
        return {"replies": [{"addSheet": {"properties": {"sheetId": 123}}}]}

    def get_worksheet_by_id(self, sheet_id):
        return self.state


def fake_gspread(spreadsheet):
    module = types.ModuleType("gspread")
    module.WorksheetNotFound = MissingWorksheet
    module.authorize = lambda _: types.SimpleNamespace(open_by_key=lambda _: spreadsheet)
    return module


def run_main(spreadsheet, events, primary=None, arb_rows=None, feed_error=None):
    """Execute the real main.py with a frozen clock and fake boundary adapters."""
    calls, feeds = [], []
    requests = types.ModuleType("requests")
    requests.RequestException = type("RequestException", (Exception,), {})

    class Reply:
        status_code = 200 if primary is not None else 502

        def raise_for_status(self):
            if self.status_code != 200:
                raise requests.RequestException("simulated provider outage")

        def json(self):
            return deepcopy(primary or [])

    def get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        return Reply()

    requests.get = get
    credentials = types.ModuleType("google.oauth2.service_account")
    credentials.Credentials = types.SimpleNamespace(from_service_account_file=lambda *a, **kw: None)
    # Real Arbworld matching/normalization code; only its HTTP boundary is replaced.
    arb = types.ModuleType("arbworld")
    with patch.dict(sys.modules, {"requests": requests}):
        exec(compile(Path(__file__).with_name("arbworld.py").read_text(), "arbworld.py", "exec"), arb.__dict__)
    arb.fetch_today = lambda: deepcopy(arb_rows or [])

    def fetch(_):
        feeds.append(True)
        if feed_error:
            raise feed_error
        return board(deepcopy(events)), FRESH

    tree = ast.parse(Path(__file__).with_name("main.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            node.names = [alias for alias in node.names if alias.name != "datetime"]
    namespace = {"__name__": "__collector_test__", "datetime": Clock}
    modules = {"requests": requests, "gspread": fake_gspread(spreadsheet),
               "google": types.ModuleType("google"), "google.oauth2": types.ModuleType("google.oauth2"),
               "google.oauth2.service_account": credentials, "arbworld": arb}
    output = io.StringIO()
    with patch.dict(sys.modules, modules), patch.dict("os.environ", {
            "APINN_API_KEY": "test-primary", "PINNODDS_API_KEY": "test-fallback",
            "PINNODDS_FALLBACK_ENABLED": "true"}), patch("time.sleep"), \
            patch("os._exit", side_effect=SystemExit(0)), patch.object(p, "datetime", Clock), \
            patch.object(p, "read_board", side_effect=fetch), redirect_stdout(output):
        try:
            exec(compile(tree, "main.py", "exec"), namespace)
        except SystemExit as exc:
            if exc.code:
                raise
    return calls, feeds, output.getvalue()


class FallbackTests(unittest.TestCase):
    def setUp(self):
        Clock.instant = NOW

    def test_schedule_60_slots_and_dst(self):
        for day in ("2026-10-21", "2026-10-25", "2026-12-01"):
            start = datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=p.ATHENS)
            slots = [p.request_slot(start + timedelta(minutes=m)) for m in range(0, 1440, 10)]
            self.assertEqual(sum(slot is not None for slot in slots), 60)
        for clock in ("11:10", "12:10", "12:50", "22:40", "23:00", "10:50"):
            self.assertIsNone(p.request_slot(datetime.fromisoformat(f"2026-10-21T{clock}:00+03:00")))
        self.assertEqual(p.request_slot(NOW + timedelta(minutes=3)), NOW)

    def test_stale_unknown_live_old_or_malformed_feed_rejected(self):
        for changes in ({"status": "stale"}, {"status": "unknown"}, {"board": "live"},
                        {"age_ms": None}, {"age_ms": "NaN"}, {"age_ms": "120001"}):
            with self.assertRaises(p.FeedError):
                p.normalize_board(board([fixture()]), dict(FRESH, **changes), NOW, lambda _: True)
        with self.assertRaises(p.FeedError):
            p.normalize_board({"sport_id": 2, "events": []}, FRESH, NOW, lambda _: True)

    def test_main_market_only_and_exact_contra(self):
        valid = fixture()
        events = [valid, fixture(2, special="Draw No Bet"), fixture(3, parent_id=1),
                  fixture(4, league_name="UEFA - Champions League Corners"),
                  fixture(5, home="Home U19"), fixture(6, away="Away (Women)"),
                  fixture(7, starts="2026-10-20T22:00:00+03:00"),
                  fixture(8, starts="2026-10-22T22:00:00+03:00"),
                  fixture(9, starts="2026-10-21T20:34:00+03:00")]
        result = normalized(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["_direct_event_odds"][0]["odds2"], 2.1)
        missing = fixture(10)
        missing["periods"]["num_0"]["spreads"] = {"-1": {"hdp": -1, "away": 1.7}}
        self.assertEqual(normalized([missing])[0]["_direct_event_odds"], [])
        bad = fixture(11)
        bad["periods"]["num_0"]["spreads"]["-0.5"]["hdp"] = -1
        self.assertEqual(normalized([bad]), [])
        closed = fixture(12)
        closed["periods"]["num_0"]["status"] = "closed"
        self.assertEqual(normalized([closed]), [])

    def test_cross_provider_handoff_preserves_row_and_old_primary_id(self):
        rows = [[], [], row("Lans", "Sporting lisbon", "original-apinn")]
        matches = normalized([fixture(2, "Lens", "Sporting CP")])
        mapping = {"original-apinn": 3}
        self.assertEqual(p.link_fixture_rows(rows, matches, mapping), [])
        self.assertEqual(matches[0]["event_id"], "original-apinn")
        rows[2][17] = "pinnodds:2"
        matches[0].pop("_provider")
        matches[0]["event_id"] = "new-apinn"
        changes = p.link_fixture_rows(rows, matches, {"pinnodds:2": 3})
        self.assertEqual(changes, [{"range": "R3", "values": [["new-apinn"]]}])
        self.assertEqual(len(rows), 3)
        rows[2] = row("Lans", "Sporting lisbon", event_id="new-apinn")[:18]
        p.link_fixture_rows(rows, matches, {"new-apinn": 3})
        self.assertEqual(len(matches), 1)

    def test_ambiguous_completed_and_wrong_youth_identity_are_not_linked(self):
        for rows in ([[], [], row(), row()], [[], [], row("Homme", "Away")]):
            matches = normalized([fixture()])
            self.assertEqual(p.link_fixture_rows(rows, matches, {}), [])
            self.assertEqual(matches, [])
        rows = [[], [], row()]
        rows[2][15] = "1-0"
        matches = normalized([fixture()])
        p.link_fixture_rows(rows, matches, {})
        self.assertEqual(matches, [])
        rows[2] = row("Home U19", "Away U19", "pinnodds:1")
        matches = normalized([fixture()])
        p.link_fixture_rows(rows, matches, {"pinnodds:1": 3})
        self.assertEqual(matches, [])

    def test_full_writer_adds_new_and_updates_manual_without_rewriting_snapshots(self):
        existing = row()
        existing[4:10] = [1.9, 1.85, 1.84, 2.2, 2.15, 2.14]
        existing[16] = "My manual note"
        existing[76] = "2026-10-21T22:00:00+03:00"
        rows = [[], [], existing]
        spreadsheet = FakeSpreadsheet(rows)
        events = [fixture(), fixture(2, home="New Home", away="New Away")]
        calls, feeds, output = run_main(spreadsheet, events)
        after = spreadsheet.main.rows
        self.assertEqual(len(feeds), 1)
        self.assertEqual(after[2][3:6], existing[3:6])
        self.assertEqual(after[2][7:9], existing[7:9])
        self.assertEqual(after[2][6], 1.8)
        self.assertEqual(after[2][9], 2.1)
        self.assertEqual(after[2][74], "My manual note")
        self.assertEqual(after[3][:3], ["UEFA - Champions League", "New Home", "New Away"])
        self.assertEqual(after[3][17], "pinnodds:2")
        self.assertEqual(after[3][4:10], [1.8, 1.8, 1.8, 2.1, 2.1, 2.1])
        self.assertTrue(all("pinnodds:" not in str(params or {}) for _, params in calls))
        self.assertIn("ODDS SOURCE: PINNODDS FALLBACK", output)
        self.assertTrue(spreadsheet.structure_writes[0]["requests"][0]["addSheet"]["properties"]["hidden"])
        # A repeated run in the same slot consumes no additional API request.
        _, feeds, _ = run_main(spreadsheet, events)
        self.assertEqual(feeds, [])
        self.assertEqual(len(spreadsheet.main.rows), 4)

    def test_fixed_away_favorite_and_missing_contra_clear_only_current_quote(self):
        existing = row(side="A", event_id="old-primary")
        existing[4:10] = [2.0, 2.1, 2.2, 1.7, 1.6, 1.5]
        event = fixture()
        event["periods"]["num_0"]["spreads"].pop("0.5")
        spreadsheet = FakeSpreadsheet([[], [], existing])
        run_main(spreadsheet, [event])
        after = spreadsheet.main.rows[2]
        self.assertEqual(after[3], "A")
        self.assertEqual(after[6], 4.0)
        self.assertEqual(after[9], "")
        self.assertEqual(after[17], "old-primary")
        self.assertEqual(after[4:6], [2.0, 2.1])
        self.assertEqual(after[7:9], [1.7, 1.6])

    def test_healthy_primary_uses_no_fallback_and_recovers_same_row(self):
        existing = row(event_id="pinnodds:1")
        existing[4], existing[7] = 1.7, 2.2
        primary = {"event_id": 99, "runner_home": "Home", "runner_away": "Away",
                   "league_name": "UEFA - Champions League", "starts": fixture()["starts"],
                   "odds": {"moneyline": {"odds1": 1.8, "odds2": 4}}, "_direct_event_odds": []}
        spreadsheet = FakeSpreadsheet([[], [], existing])
        _, feeds, output = run_main(spreadsheet, [fixture()], primary=[primary])
        self.assertEqual(feeds, [])
        self.assertEqual(len(spreadsheet.main.rows), 3)
        self.assertEqual(spreadsheet.main.rows[2][17], "99")
        self.assertEqual(spreadsheet.main.rows[2][4], 1.7)
        self.assertEqual(spreadsheet.main.rows[2][7], 2.2)
        self.assertIn("ODDS SOURCE: APINN", output)

    def test_late_quote_does_not_create_fake_90_snapshot_or_touch_started_rows(self):
        Clock.instant = NOW + timedelta(minutes=40)
        active = row()
        started = row("Started Home", "Started Away", kickoff="2026-10-21T21:00:00+03:00")
        started[4:10] = [1.3, 1.2, 1.1, 4, 5, 6]
        spreadsheet = FakeSpreadsheet([[], [], active, started])
        run_main(spreadsheet, [fixture(), fixture(2, "Started Home", "Started Away", starts=started[76])])
        self.assertEqual(spreadsheet.main.rows[2][5], "")
        self.assertEqual(spreadsheet.main.rows[2][8], "")
        self.assertEqual(spreadsheet.main.rows[2][6], 1.8)
        self.assertEqual(spreadsheet.main.rows[3], started)

    def test_outside_schedule_and_bad_state_make_zero_fallback_requests(self):
        Clock.instant = datetime.fromisoformat("2026-10-21T22:40:00+03:00")
        spreadsheet = FakeSpreadsheet([[], [], row()])
        _, feeds, _ = run_main(spreadsheet, [fixture()])
        self.assertEqual(feeds, [])
        self.assertIsNone(spreadsheet.state)
        Clock.instant = NOW
        spreadsheet.state = FakeSheet([[], ["2026-10-21", "", 60, ""]])
        _, feeds, _ = run_main(spreadsheet, [fixture()])
        self.assertEqual(feeds, [])

    def test_failed_feed_is_counted_once_and_arbworld_keeps_refreshing(self):
        existing = row()
        arb = {"home": "Home", "away": "Away", "leage": "UEFA - Champions League",
               "odds_type": "MATCH_ODDS", "date": "2026-10-21T19:00:00Z",
               "volume_1": 400, "volume_x": 100, "volume_2": 500}
        spreadsheet = FakeSpreadsheet([[], [], existing])
        _, feeds, output = run_main(spreadsheet, [fixture()], arb_rows=[arb], feed_error=p.FeedError("HTTP 503; no retry."))
        self.assertEqual(len(feeds), 1)
        self.assertEqual(spreadsheet.state.rows[1][2], 1)
        self.assertEqual(spreadsheet.main.rows[2][10:13], [1000, 40, 60])
        self.assertEqual(spreadsheet.main.rows[2][6], "")
        self.assertIn("PINNODDS WITHHELD", output)
        _, feeds, _ = run_main(spreadsheet, [fixture()], feed_error=p.FeedError("HTTP 503"))
        self.assertEqual(feeds, [])

    def test_request_error_does_not_print_credential_or_retry(self):
        import urllib.error
        opener = types.SimpleNamespace(open=lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.HTTPError(p.ENDPOINT, 401, "Unauthorized", {}, None)))
        with patch.object(p.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(p.FeedError) as caught:
                p.read_board("test-secret-never-log")
        self.assertEqual(str(caught.exception), "HTTP 401; no retry.")


if __name__ == "__main__":
    unittest.main()
