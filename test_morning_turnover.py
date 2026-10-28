"""Frozen morning classification and the real collector's atomic write path."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest

from morning_turnover import (COLORS, FIRST_OBSERVATION, HISTORICAL, attach_morning_locks,
                              build_lock_updates, color_for, color_formula, overlay)
from test_pinnodds import Clock, FakeSheet, FakeSpreadsheet, NOW, fixture, row, run_main
import pinnodds as p

STAMP = datetime.fromisoformat("2026-10-28T14:00:00+02:00")


def morning(amount, league="League", name="Home", kickoff="2026-10-28T20:00:00+02:00"):
    result = [""] * 95
    result[:4] = [league, name, "Away", "H"]
    result[19], result[76] = amount, kickoff
    return result


def records(changes):
    return {int(update["range"].split(":")[0][2:]): update["values"][0] for update in changes}


class ClassificationTests(unittest.TestCase):
    def test_all_competitions_separately_and_only_morning_t_trains_the_reference(self):
        rows = [[], [], morning(100, "USA - Major League Soccer", "Low"),
                morning(200, "USA - Major League Soccer", "High"),
                morning(999999, "UEFA - Champions League", "Other")]
        first = build_lock_updates(rows, STAMP)
        actual = records(first)
        self.assertEqual(actual[3][0:2], [0, COLORS[0]])
        self.assertEqual(actual[4][0:2], [100, COLORS[3]])
        self.assertEqual(actual[3][3:5], [2, 150])
        self.assertEqual(actual[5][3:5], [1, 999999])
        changed = deepcopy(rows)
        for value in changed[2:]:
            value[6], value[10], value[11], value[13], value[22] = 1.1, 999999999, 99, 99, 55555555
        self.assertEqual(build_lock_updates(changed, STAMP), first)

    def test_exact_color_boundaries_and_rank_ties_match_k_convention(self):
        self.assertEqual([color_for(n) for n in (0,35,35.00001,75,75.00001,87,87.00001,100)],
                         [COLORS[0],COLORS[0],COLORS[1],COLORS[1],COLORS[2],COLORS[2],COLORS[3],COLORS[3]])
        actual = records(build_lock_updates([[],[],morning(0,name="Zero"),morning(100,name="A"),morning(100,name="B")], STAMP))
        self.assertEqual(actual[3][0], 0)
        self.assertEqual(actual[4][0], 100)
        self.assertEqual(actual[5][0], 100)

    def test_missing_negative_nonfinite_or_text_amounts_never_get_colored(self):
        rows = [[],[]] + [morning(v,name=str(i)) for i,v in enumerate(("",None,-1,float("nan"),float("inf"),True,"1234"))]
        self.assertEqual(build_lock_updates(rows, STAMP), [])

    def test_historical_seed_does_not_claim_original_observation_time(self):
        record = records(build_lock_updates([[],[],morning(100)], STAMP))[3]
        details = json.loads(record[8])
        self.assertEqual(record[5], HISTORICAL)
        self.assertIsNone(details["first_observed_at"])
        self.assertEqual(details["classified_at"], STAMP.isoformat())

    def test_later_population_changes_never_rewrite_a_locked_record(self):
        rows = [[],[],morning(100),morning(200,name="Other")]
        first = build_lock_updates(rows, STAMP)
        overlay(rows, first)
        old = deepcopy(rows[2][86:95])
        rows.extend(morning(10000+i,name=str(i)) for i in range(20))
        later = build_lock_updates(rows, STAMP+timedelta(days=1))
        self.assertNotIn(3, records(later))
        self.assertNotIn(4, records(later))
        self.assertEqual(rows[2][86:95], old)
        self.assertEqual(records(later)[5][3], 22)

    def test_every_color_formula_is_t_only_and_uses_frozen_key_and_source_amount(self):
        for color in COLORS:
            formula = color_formula(color)
            self.assertIn('$CJ3="'+color+'"', formula)
            self.assertIn("$CO3=$T3", formula)
            self.assertIn("$CP3=", formula)
            self.assertNotIn("COUNT", formula)
            self.assertNotIn("$K", formula)
            self.assertNotIn("$W", formula)


class AtomicWriterTests(unittest.TestCase):
    def test_first_capture_and_its_lock_share_one_batch_with_exact_raw_precision(self):
        rows = [[],[],morning("",name="New"),morning(100.00000001,name="Old")]
        sheet = FakeSheet(rows)
        pending = [{"range":"T3:V3","values":[[100,85,15]]},
                   {"range":"G3","values":[[1.55]]}]
        updates = attach_morning_locks(sheet, rows, pending, STAMP)
        record = records([u for u in updates if u["range"].startswith("CI")])[3]
        self.assertEqual(record[0], 0)  # No display rounding into a tied maximum.
        self.assertEqual(record[3], 2)
        self.assertEqual(record[5], FIRST_OBSERVATION)
        self.assertEqual(json.loads(record[8])["first_observed_at"], STAMP.isoformat())
        self.assertEqual(updates[:2], pending)
        sheet.batch_update(updates)
        self.assertEqual(sheet.rows[2][19], sheet.rows[2][92])

    def test_multiple_first_snapshots_use_the_same_complete_cohort_independent_of_order(self):
        rows = [[],[],morning("",name="A"),morning("",name="B"),morning(50,name="Old")]
        pending = [{"range":"T3:V3","values":[[100,80,20]]}, {"range":"T4:V4","values":[[200,90,10]]}]
        for order in (pending, list(reversed(pending))):
            changes = attach_morning_locks(FakeSheet(rows),rows,order,STAMP)
            actual = records([u for u in changes if u["range"].startswith("CI")])
            self.assertEqual(actual[3][0:2], [50, COLORS[1]])
            self.assertEqual(actual[4][0:2], [100, COLORS[3]])
            self.assertEqual(actual[3][3], 3)

    def test_new_row_identity_and_kickoff_are_overlaid_before_first_lock(self):
        rows = [[],[],morning(50,name="Old")]
        pending = [{"range":"A4:D4","values":[["League","New","Away","H"]]},
                   {"range":"BY4","values":[["2026-10-28T22:00:00+02:00"]]},
                   {"range":"T4:V4","values":[[200,80,20]]}]
        changes = attach_morning_locks(FakeSheet(rows),rows+[[]],pending,STAMP)
        record = records([u for u in changes if u["range"].startswith("CI")])[4]
        self.assertIn("New¦Away¦2026-10-28T22:00:00+02:00", record[7])

    def test_repeat_never_rewrites_and_read_failure_withholds_only_the_morning_snapshot(self):
        rows = [[],[],morning(100)]
        overlay(rows, build_lock_updates(rows, STAMP))
        pending = [{"range":"T3:V3","values":[[100,85,15]]},{"range":"K3:M3","values":[[200,90,10]]}]
        self.assertEqual(attach_morning_locks(FakeSheet(rows),rows,pending,STAMP+timedelta(days=1)), pending)
        class Broken:
            def batch_get(self,*args,**kwargs):
                raise RuntimeError("simulated Google outage")
        self.assertEqual(attach_morning_locks(Broken(),rows,pending,STAMP),pending[1:])

    def test_changed_t_or_reused_identity_cannot_overwrite_the_original_lock(self):
        rows = [[],[],morning(100)]
        overlay(rows, build_lock_updates(rows, STAMP))
        for prefix in ([], [{"range":"B3","values":[["Reused home"]]}]):
            pending = prefix + [{"range":"T3:V3","values":[[200,85,15]]},{"range":"G3","values":[[1.55]]}]
            result = attach_morning_locks(FakeSheet(rows),rows,pending,STAMP)
            self.assertFalse(any(u["range"].startswith("T") or u["range"].startswith("CI") for u in result))
            self.assertIn(pending[-1],result)

    def test_existing_unlocked_values_are_not_silently_backfilled_on_an_ordinary_run(self):
        rows = [[],[],morning(100)]
        class NoReads:
            def batch_get(self,*args,**kwargs):
                raise AssertionError("No first snapshot was written")
        pending = [{"range":"K3:M3","values":[[200,90,10]]}]
        self.assertEqual(attach_morning_locks(NoReads(),rows,pending,STAMP), pending)

    def test_real_main_collector_attaches_a_first_lock_with_independent_arbworld_and_no_extra_feed(self):
        for independent in (True,False):
            live = row(event_id="pinnodds:1")
            arb = {"home":"Home", "away":"Away", "leage":"UEFA - Champions League",
                   "volume_1":800, "volume_x":100, "volume_2":100}
            # The independent route needs the source kickoff. Without it,
            # only the regular quote-matched route can create the snapshot.
            if independent:
                arb.update(date="2026-10-21T19:00:00Z",odds_type="MATCH_ODDS")
            book = FakeSpreadsheet([[],[],live])
            Clock.instant = NOW
            error=p.FeedError("simulated odds outage") if independent else None
            calls, feeds, output = run_main(book,[fixture()],arb_rows=[arb],feed_error=error)
            self.assertEqual(len(feeds),1)
            self.assertIn("MORNING TURNOVER LOCK OK | new=1 | atomic=True",output)
            self.assertEqual(book.main.rows[2][19],1000)
            self.assertEqual(book.main.rows[2][86:88],[0,COLORS[0]])
            self.assertEqual(book.main.rows[2][91],FIRST_OBSERVATION)
            self.assertEqual(book.main.rows[2][92],1000)
            self.assertTrue(any(u["range"]=="T3:V3" for u in book.main.writes))
            self.assertTrue(any(u["range"]=="CI3:CQ3" for u in book.main.writes))


if __name__ == "__main__":
    unittest.main()
