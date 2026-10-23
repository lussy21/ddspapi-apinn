"""Offline replay of partial snapshots and slow Apify runs. No live services."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
from io import StringIO
import types
import unittest
from unittest.mock import Mock

import test_sofascore_candidates as fixtures


class Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def response(data):
    return types.SimpleNamespace(json=lambda: deepcopy(data), raise_for_status=lambda: None)


class Control:
    def __init__(self, marker=""):
        self.marker = marker
        self.writes = []

    def acell(self, name):
        return types.SimpleNamespace(value=self.marker)

    def update(self, *args, **kwargs):
        values = kwargs.get("values", args[1] if len(args) > 1 else None)
        self.marker = values[0][0]
        self.writes.append(self.marker)


class SofaReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.ns = fixtures.SofaCandidateTests().load_collector()
        self.clock = Clock()
        self.ns["time"] = self.clock

    def prepare(self, rows, missing_fixture=False, votes=None):
        sheet = fixtures.FakeSheet([[], []] + rows)
        cache = fixtures.FakeSheet([["KEY", "SOFA", "HOME", "AWAY", "DATE"]])
        book = types.SimpleNamespace(worksheet=lambda title: cache)
        events = [{"id": 101+i,
                   "startTimestamp": int(datetime.fromisoformat(r[76]).timestamp()),
                   "homeTeam": {"name": r[1]}, "awayTeam": {"name": r[2]}}
                  for i, r in enumerate(rows)]
        self.ns["fetch_sofa_schedule"] = Mock(return_value=events[:-1] if missing_fixture else events)
        self.ns["fetch_votes"] = Mock(side_effect=votes or (lambda token, ids, **kw: [
            {"eventId": i, "votes": {"vote": {"vote1": 70, "voteX": 10, "vote2": 20}}}
            for i in ids]))
        return sheet, cache, book

    def collect(self, sheet, book, report, **kwargs):
        return self.ns["update_votes"](
            sheet, sheet.get_all_values(), book, "fake-token", "fake-key", fixtures.NOW,
            only_blank=True, include_next_morning=True, report=report, **kwargs)

    def test_second_divisions_do_not_resolve_to_first_divisions(self):
        for label, expected in {
            "Germany - Bundesliga 2": 44, "Germany - 2. Bundesliga": 44,
            "Germany - Bundesliga 2 Regular Season": 44,
            "Belgium - Challenger Pro League": 9,
            "Belgium - Challenger Pro League Regular Season": 9,
            "Germany - Bundesliga": 35, "Belgium - Pro League": 38,
            "Greece - Super League 2": 186,
        }.items():
            with self.subTest(label=label):
                self.assertEqual(self.ns["sheet_league_tournament_id"](label), expected)
        self.assertEqual(self.ns["sofa_tournament_id"](None, "Germany - Bundesliga 2"), 44)
        self.assertEqual(self.ns["sofa_tournament_id"](None, "Belgium - Challenger Pro League"), 9)

    def test_backup_receives_correct_second_division_tournaments(self):
        german = fixtures.sheet_row(key="g", home="Bochum", away="Wolfsburg")
        german[0] = "Germany - Bundesliga 2"
        belgian = fixtures.sheet_row(key="b", home="Francs Borains", away="Dender")
        belgian[0] = "Belgium - Challenger Pro League"
        sheet, cache, book = self.prepare([german, belgian])
        events = self.ns["fetch_sofa_schedule"].return_value
        self.ns["fetch_sofa_schedule"] = Mock(side_effect=RuntimeError("blocked"))
        self.ns["fetch_fixtures"] = Mock(return_value=events)
        stats = {}
        self.assertTrue(self.collect(sheet, book, stats, allow_paid_fallback=True))
        self.ns["fetch_fixtures"].assert_called_once_with(
            "fake-token", "2026-10-22", {9, 44}, timeout=75, attempts=1)
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(len(cache.rows), 3)

    def test_a_missing_match_is_partial_even_when_other_votes_write(self):
        rows = [fixtures.sheet_row(), fixtures.sheet_row(key="missing", home="Bochum", away="Wolfsburg")]
        sheet, cache, book = self.prepare(rows, missing_fixture=True)
        stats = {}
        self.assertFalse(self.collect(sheet, book, stats))
        self.assertEqual(stats, dict(eligible=2, matched=1, unmapped=0, unmatched=1,
                                    missing_votes=0, preserved=0, wrote=1))
        self.assertTrue(self.ns["sofa_snapshot_summary"](stats).startswith("PARTIAL"))
        self.assertEqual(sheet.rows[3][13], "")
        self.assertEqual(len(cache.rows), 2)

    def test_missing_votes_are_not_success_but_result_cache_is_kept(self):
        sheet, cache, book = self.prepare([fixtures.sheet_row()], votes=lambda *a, **kw: [])
        stats = {}
        self.assertFalse(self.collect(sheet, book, stats))
        self.assertEqual(stats["missing_votes"], 1)
        self.assertTrue(self.ns["sofa_snapshot_summary"](stats).startswith("NO DATA"))
        self.assertEqual(len(cache.rows), 2)
        self.assertEqual(sheet.writes, [])

    def test_unmapped_upcoming_league_cannot_be_reported_as_complete(self):
        unknown = fixtures.sheet_row(key="unknown", home="Bochum", away="Wolfsburg")
        unknown[0] = "Unknown competition"
        sheet, _, book = self.prepare([fixtures.sheet_row(), unknown])
        stats = {}
        self.assertFalse(self.collect(sheet, book, stats))
        self.assertEqual((stats["eligible"], stats["unmapped"]), (2, 1))
        self.assertTrue(self.ns["sofa_snapshot_summary"](stats).startswith("PARTIAL"))

    def test_manual_vote_entered_during_actor_wait_is_preserved(self):
        sheet, _, book = self.prepare([fixtures.sheet_row()])
        def during_wait(*args, **kwargs):
            sheet.rows[2][13] = 88
            return [{"eventId": 101, "votes": {"vote": {"vote1": 70, "voteX": 10, "vote2": 20}}}]
        self.ns["fetch_votes"] = Mock(side_effect=during_wait)
        stats = {}
        self.assertTrue(self.collect(sheet, book, stats))
        self.assertEqual(sheet.rows[2][13], 88)
        self.assertEqual(sheet.writes, [])
        self.assertEqual((stats["preserved"], stats["missing_votes"]), (1, 0))

    def test_changed_row_identity_is_not_written(self):
        sheet, _, book = self.prepare([fixtures.sheet_row()])
        def during_wait(*args, **kwargs):
            sheet.rows[2][17] = "another-stable-id"
            return [{"eventId": 101, "votes": {"vote": {"vote1": 70}}}]
        self.ns["fetch_votes"] = Mock(side_effect=during_wait)
        stats = {}
        self.assertFalse(self.collect(sheet, book, stats))
        self.assertEqual(sheet.writes, [])
        self.assertEqual(stats["missing_votes"], 1)

    def fake_actors(self, finish_at=60, post_error=False, poll_error=False, dataset_error=False):
        posted, polled, datasets = [], [], []
        def post(url, **kw):
            posted.append((url, kw))
            n = len(posted)
            if post_error and n == 1:
                raise RuntimeError("lost start response fake-secret")
            return response({"data": {"id": str(n), "status": "RUNNING", "defaultDatasetId": "ds"+str(n)}})
        def get(url, **kw):
            if "/actor-runs/" in url:
                polled.append(url)
                if poll_error and len(polled) == 1:
                    raise RuntimeError("temporary read error fake-secret")
                number = int(url.rsplit("/", 1)[-1])
                ready = finish_at if number == 1 else 8
                self.clock.sleep(min(kw["params"]["waitForFinish"], max(0, ready-self.clock.value)))
                status = "SUCCEEDED" if self.clock.value >= ready else "RUNNING"
                return response({"data": {"id": str(number), "status": status, "defaultDatasetId": "ds"+str(number)}})
            datasets.append(url)
            if dataset_error and len(datasets) == 1:
                raise RuntimeError("temporary dataset read failure")
            n = int(url.split("/datasets/ds")[1].split("/")[0])
            ids = posted[n-1][1]["json"]["eventIds"]
            return response([{"eventId": i, "votes": {"vote": {"vote1": 70}}} for i in ids])
        self.ns["requests"] = types.SimpleNamespace(post=Mock(side_effect=post), get=Mock(side_effect=get))
        return posted, polled, datasets

    def test_slow_batch_completes_after_45s_with_one_start_per_batch(self):
        posted, polled, datasets = self.fake_actors(finish_at=65)
        batches = [{"eventIds": list(range(i, i+5))} for i in (1, 6, 11)]
        rows = self.ns["apify_vote_batches"]("fake-token", batches)
        self.assertEqual(sorted(r["eventId"] for r in rows), list(range(1, 16)))
        self.assertEqual(len(posted), 3)
        self.assertEqual(len(datasets), 3)
        self.assertGreaterEqual(self.clock.value, 65)
        self.assertLess(self.clock.value, 100)
        self.assertTrue(all(url.endswith("/runs") for url, _ in posted))
        self.assertTrue(all("/v2/actors/" in url for url, _ in posted))
        self.assertTrue(all("token" not in kw["params"] for _, kw in posted))
        self.assertTrue(all(kw["params"]["restartOnError"] == "false" for _, kw in posted))

    def test_lost_start_response_never_starts_that_batch_again(self):
        posted, _, _ = self.fake_actors(post_error=True)
        output = StringIO()
        with redirect_stdout(output):
            rows = self.ns["apify_vote_batches"]("fake-token", [{"eventIds": [1]}, {"eventIds": [2]}])
        self.assertEqual([r["eventId"] for r in rows], [2])
        self.assertEqual([kw["json"]["eventIds"] for _, kw in posted], [[1], [2]])
        self.assertNotIn("fake-secret", output.getvalue())
        self.assertNotIn("fake-token", output.getvalue())

    def test_transient_poll_error_reads_same_run_without_paid_restart(self):
        posted, polled, _ = self.fake_actors(finish_at=10, poll_error=True)
        rows = self.ns["apify_vote_batches"]("fake-token", [{"eventIds": [1]}])
        self.assertEqual([r["eventId"] for r in rows], [1])
        self.assertEqual(len(posted), 1)
        self.assertEqual(len(set(polled)), 1)

    def test_wait_deadline_does_not_restart_slow_actor(self):
        posted, _, _ = self.fake_actors(finish_at=200)
        rows = self.ns["apify_vote_batches"]("fake-token", [{"eventIds": [1]}], wait_seconds=20)
        self.assertEqual(rows, [])
        self.assertEqual(len(posted), 1)
        self.assertLessEqual(self.clock.value, 20)
        self.assertLessEqual(posted[0][1]["params"]["timeout"], 15)

    def test_dataset_read_retry_reuses_finished_run(self):
        posted, _, datasets = self.fake_actors(finish_at=5, dataset_error=True)
        rows = self.ns["apify_vote_batches"]("fake-token", [{"eventIds": [1]}])
        self.assertEqual([r["eventId"] for r in rows], [1])
        self.assertEqual(len(posted), 1)
        self.assertEqual(len(datasets), 2)
        self.assertEqual(len(set(datasets)), 1)

    def test_insufficient_runner_budget_starts_no_actor(self):
        posted, _, _ = self.fake_actors()
        self.ns["RUNNER_DEADLINE"] = 25
        rows = self.ns["apify_vote_batches"]("fake-token", [{"eventIds": [1]}])
        self.assertEqual((rows, posted), ([], []))

    def test_daily_marker_prevents_paid_retry_even_after_partial(self):
        control = Control("RENDER SOFA 2026-10-22 | PARTIAL | wrote=9")
        self.ns["update_votes"] = Mock(side_effect=AssertionError("No paid retry"))
        self.assertTrue(self.ns["run_daily_paid_sofa_snapshot"](
            control, None, [], None, "fake-token", "fake-key", fixtures.NOW))
        self.ns["update_votes"].assert_not_called()
        self.assertEqual(control.writes, [])

    def test_daily_status_reports_partial_coverage_and_consumes_attempt_first(self):
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixtures.NOW
        self.ns["datetime"] = Frozen
        self.ns["random"] = types.SimpleNamespace(SystemRandom=lambda: types.SimpleNamespace(randint=lambda a,b: 0))
        rows = [fixtures.sheet_row(), fixtures.sheet_row(key="missing", home="Bochum", away="Wolfsburg")]
        sheet, _, book = self.prepare(rows, missing_fixture=True)
        control = Control()
        self.assertTrue(self.ns["run_daily_paid_sofa_snapshot"](
            control, sheet, sheet.get_all_values(), book, "fake-token", "fake-key", fixtures.NOW))
        self.assertIn("RUNNING", control.writes[0])
        self.assertIn("PARTIAL", control.marker)
        self.assertIn("matched=1/2", control.marker)
        self.assertIn("unmatched=1", control.marker)
        self.assertNotIn("DONE", control.marker)


if __name__ == "__main__":
    unittest.main()
