from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest

import final_turnover as f
from test_pinnodds import Clock, FakeSheet, FakeSpreadsheet, NOW, fixture, row, run_main

STAMP=datetime.fromisoformat('2026-10-28T17:00:00+02:00')


def market(amount, name='Home', league='League', kickoff='2026-10-28T16:00:00+02:00', score=''):
    r=['']*104
    r[:4]=[league,name,'Away','H']
    r[10],r[15],r[76]=amount,score,kickoff
    return r


def activated(items):
    header=['']*104
    header[95]=f.ACTIVATION
    return [header,[]]+items


def records(updates):
    return {int(u['range'].split(':')[0][2:]):u['values'][0] for u in updates if u['range'].startswith('CR')}


class ClassificationTests(unittest.TestCase):
    def test_common_exact_league_reference_excludes_prematch_and_ignores_other_inputs(self):
        rows=activated([market(100,'Low'),market(200,'High'),
                        market(1,'Future',kickoff='2026-10-28T20:00:00+02:00'),
                        market(9999,'Separate',league='USA - Major League Soccer')])
        actual=records(f.build_lock_updates(rows,STAMP))
        self.assertEqual(actual[3][:2],[0,f.COLORS[0]])
        self.assertEqual(actual[4][:2],[100,f.COLORS[3]])
        self.assertEqual(actual[3][3:5],[2,150])
        self.assertNotIn(5,actual)
        self.assertEqual(actual[6][3:5],[1,9999])
        other=deepcopy(rows)
        for r in other[2:]:
            r[19],r[22],r[64],r[11],r[13]=1e12,1e11,100,99,99
        self.assertEqual(f.build_lock_updates(other,STAMP),f.build_lock_updates(rows,STAMP))

    def test_physical_row_order_does_not_change_rank_color_or_reference(self):
        items=[market(200,'A'),market(100,'B'),market(150,'C')]
        def by_id(values):
            return {r[7]:(r[:2],r[3:5]) for r in records(f.build_lock_updates(activated(values),STAMP)).values()}
        self.assertEqual(by_id(items),by_id(list(reversed(items))))

    def test_kickoff_boundary_score_fallback_and_no_unverified_finality(self):
        rows=activated([market(100,'At',kickoff=STAMP.isoformat()),
                        market(200,'Future',kickoff=(STAMP+timedelta(seconds=1)).isoformat(),score='1-0'),
                        market(300,'Score only',kickoff='',score='2-1'),
                        market(400,'Unknown',kickoff=''),
                        market(500,'Naive',kickoff='2026-10-20T12:00:00')])
        actual=records(f.build_lock_updates(rows,STAMP))
        self.assertEqual(set(actual),{3,5})
        self.assertEqual(json.loads(actual[3][8])['finalization_reason'],'KICKOFF_PASSED')
        self.assertEqual(json.loads(actual[5][8])['finalization_reason'],'SCORE_PRESENT')

    def test_only_valid_numeric_k_is_eligible(self):
        rows=activated([market(x,str(i)) for i,x in enumerate(('',None,-1,True,float('inf'),float('nan'),'1234'))])
        self.assertEqual(f.build_lock_updates(rows,STAMP),[])

    def test_archive_evidence_is_exact_identity_and_amount_and_historical_only(self):
        r=market(278177,kickoff='')
        proof={f.identity(r):{'K':278177,'source':'ALERT LOG!I688','recorded_at':'2026-09-21T08:11:07+03:00'}}
        record=records(f.build_lock_updates(activated([r]),STAMP,f.HISTORICAL,proof))[3]
        details=json.loads(record[8])
        self.assertEqual(details['finalization_reason'],'ARCHIVED_K_SNAPSHOT')
        self.assertIsNone(details['first_finalized_at'])
        self.assertFalse(details['quote_timestamp_known'])
        with self.assertRaises(ValueError):
            f.build_lock_updates(activated([r]),STAMP,historical_evidence=proof)
        changed=deepcopy(r);changed[10]=278178
        self.assertEqual(f.build_lock_updates(activated([changed]),STAMP,f.HISTORICAL,proof),[])
        changed=deepcopy(r);changed[1]='Different fixture'
        self.assertEqual(f.build_lock_updates(activated([changed]),STAMP,f.HISTORICAL,proof),[])

    def test_locked_records_never_rerank_and_the_frozen_k_trains_later_locks(self):
        rows=activated([market(100,'Old'),market(200,'Other')])
        f.overlay(rows,f.build_lock_updates(rows,STAMP))
        old=deepcopy(rows[2][95:104])
        rows[2][10]=999999  # Manual edits cannot silently retrain the baseline.
        rows.append(market(150,'New'))
        new=records(f.build_lock_updates(rows,STAMP+timedelta(days=1)))
        self.assertEqual(set(new),{5})
        self.assertEqual(new[5][3:5],[3,150])
        self.assertEqual(rows[2][95:104],old)
        rows[2][10]=''
        self.assertEqual(records(f.build_lock_updates(rows,STAMP))[5][3:5],[3,150])

    def test_reused_identity_cannot_inherit_or_overwrite_an_old_lock(self):
        rows=activated([market(100)])
        f.overlay(rows,f.build_lock_updates(rows,STAMP))
        old=deepcopy(rows[2][95:104]);rows[2][1]='Reused'
        self.assertFalse(f.locked_identity(rows[2]))
        self.assertEqual(f.build_lock_updates(rows,STAMP+timedelta(days=1)),[])
        self.assertEqual(rows[2][95:104],old)

    def test_frozen_color_formula_guards_source_and_fixture_and_has_no_dynamic_rank(self):
        for c in f.COLORS:
            formula=f.color_formula(c)
            self.assertIn('$CX3=$K3',formula)
            self.assertIn('$CY3=',formula)
            self.assertIn('$CS3="'+c+'"',formula)
            self.assertNotIn('COUNT',formula)
            self.assertNotIn('$BM',formula)


class WriterTests(unittest.TestCase):
    def test_inactive_marker_needs_no_reads_and_preserves_updates(self):
        class NoReads:
            def batch_get(self,*a,**kw):raise AssertionError('Unexpected read')
        pending=[{'range':'G3','values':[[1.5]]}]
        self.assertEqual(f.attach_final_locks(NoReads(),[[],[],market(100)],pending,STAMP),pending)

    def test_latest_raw_k_and_lock_share_one_batch_with_precision(self):
        rows=activated([market(100.00000001,'Old'),market(50,'New')])
        f.overlay(rows,f.build_lock_updates(rows,STAMP))
        rows[3][95:104]=['']*9
        pending=[{'range':'K4:M4','values':[[100,85,15]]},{'range':'G4','values':[[1.5]]}]
        updates=f.attach_final_locks(FakeSheet(rows),rows,pending,STAMP)
        record=records(updates)[4]
        self.assertEqual(record[:2],[0,f.COLORS[0]])
        self.assertEqual(record[6],100)
        sheet=FakeSheet(rows);sheet.batch_update(updates)
        self.assertEqual(sheet.rows[3][10],sheet.rows[3][101])

    def test_normal_updates_cannot_rewrite_locked_k_money_or_evidence(self):
        rows=activated([market(100)])
        f.overlay(rows,f.build_lock_updates(rows,STAMP))
        pending=[{'range':'K3:M3','values':[[999,1,99]]},
                 {'range':'G3','values':[[1.5]]},{'range':'T3:V3','values':[[10,80,20]]}]
        updates=f.attach_final_locks(FakeSheet(rows),rows,pending,STAMP+timedelta(days=1))
        self.assertEqual(updates,pending[1:])
        self.assertEqual(rows[2][10],100)

    def test_multirow_and_mixed_column_writes_keep_unlocked_and_unrelated_values(self):
        rows=activated([market(100,'Locked'),market(200,'Live',kickoff='2026-10-28T22:00:00+02:00')])
        f.overlay(rows,f.build_lock_updates(rows,STAMP))
        pending=[{'range':'K3:N4','values':[[1,2,3,4],[5,6,7,8]]}]
        actual=f.suppress_locked_k_writes(rows,pending)
        self.assertEqual(actual,[{'range':'N3:N3','values':[[4]]},{'range':'K4:N4','values':[[5,6,7,8]]}])

    def test_postkickoff_without_a_new_quote_still_finalizes(self):
        rows=activated([market(100,kickoff=STAMP.isoformat())])
        self.assertIn(3,records(f.attach_final_locks(FakeSheet(rows),rows,[],STAMP)))

    def test_raw_read_failure_defers_only_finalization(self):
        class Broken:
            def batch_get(self,*a,**kw):raise RuntimeError('Google outage')
        rows=activated([market(100)])
        pending=[{'range':'G3','values':[[1.5]]}]
        self.assertEqual(f.attach_final_locks(Broken(),rows,pending,STAMP),pending)

    def test_live_prematch_fixture_does_not_get_a_final_lock(self):
        rows=activated([market(100,kickoff=(STAMP+timedelta(minutes=1)).isoformat())])
        self.assertEqual(f.attach_final_locks(FakeSheet(rows),rows,[],STAMP),[])

    def test_real_collector_finalizes_old_row_without_extra_feed_or_alert_changes(self):
        live=row(event_id='pinnodds:1')
        old=row(home='Old',away='Opponent',event_id='pinnodds:999',kickoff=(NOW-timedelta(days=1)).isoformat())
        old[10],old[15]=1000,'1-0'
        header=['']*104;header[95]=f.ACTIVATION
        book=FakeSpreadsheet([header,[],old,live])
        Clock.instant=NOW
        calls,feeds,output=run_main(book,[fixture()])
        self.assertEqual(len(feeds),1)
        self.assertIn('FINAL TURNOVER LOCK OK | new=1',output)
        self.assertEqual(book.main.rows[2][101],1000)
        self.assertEqual(book.main.rows[2][100],f.FINAL_OBSERVATION)
        self.assertFalse(any(u['range'].startswith('CR4:') for u in book.main.writes))


if __name__=='__main__':unittest.main()
