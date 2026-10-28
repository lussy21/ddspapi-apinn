# ddspapi-apinn

## Contra Rise90 research

`ΚΟΝΤΡΑ ΑΝΟΔΟΥ 90′` is a separate prospective Contra +0.5 research rule from
2026-10-27 22:37 Europe/Athens. It requires numeric F/G >1 and G >= F * 1.10,
using the original favorite D. It covers exactly the existing ΜΕΓΑΛΑ and
ΛΟΙΠΑ ΕΥΡΩΠΗΣ competitions. No opening-odds floor, turnover, money share,
Sofa, home/away or clock-hour filter is added.

The dedicated `ΚΟΝΤΡΑ ΑΝΟΔΟΥ 90` tab records fresh observations after the
90-minute snapshot. A pick counts once at its first qualifying fresh quote
between 30 and 5 minutes before kickoff, inclusive. Its entry, original side
and actual available Contra +0.5 price are immutable, including when the
condition later disappears. Early-only observations do not count. Missing
entry prices remain unpriced; missing results remain pending. The live ledger
starts at 0/0; the earlier 14/21 closing-snapshot study stays historical and
uses a different observation convention.

The collector writes observations only after actual G value updates. The
post-Sofa history stage can settle existing entries but cannot create any.
Provider-ID changes and physical row moves do not duplicate a fixture. Level
review does not overwrite the ledger-owned metrics. This research rule does
not enter live O or push notifications, and existing alerts are unchanged.

The existing Render cron remains the only odds writer:

```sh
python main.py && python sofascore_runner-1.py && python alert_history.py
```

## Pinnodds standby feed

Set `PINNODDS_API_KEY` as a private Render environment variable and
`PINNODDS_FALLBACK_ENABLED=true`. Set the flag to `false` to disable standby.
No credential belongs in this repository.

APINN stays primary. If none of its recovered fixtures has usable current
moneyline prices, the same writer may fetch one Pinnodds bulk soccer prematch
board. Working APINN uses zero Pinnodds requests. Arbworld and SofaScore keep
their current collectors and ten-minute cron.

Pinnodds runs in `Europe/Athens`: once at 11:00, once at 12:00, then every ten
minutes from 13:00 through 22:30 inclusive (60 possible requests/day). Cron
startup delays are accepted within each ten-minute slot. A hidden `PINNODDS STATE`
tab reserves each slot before HTTP and caps automatic calls at 60/day across
process restarts and deployments. Failed requests count; no automatic retries
or per-event calls are made. Render's single-run cron guarantee serializes state
reservations. Outside this window an APINN outage leaves quotes unchanged;
fixtures after 22:30 have no guaranteed fallback close measurement.

Only fresh prematch boards with a reported age at most two minutes are accepted.
The full-match open period is used. Existing target-league filters apply, and
corners, bookings, women/youth/reserves, specials and child markets are excluded.
Upcoming overnight fixtures belong to the betting day starting at 11:00 Athens.

Both teams, league and kickoff bind fixtures to existing rows. New fallback rows
reuse existing competition labels so turnover percentiles keep the same groups.
These rows
use `pinnodds:<id>` in R; existing APINN IDs are retained during standby. APINN
recovery keeps the Sheet ID stable for alert history and SofaScore cache links,
using the real APINN request ID separately in memory. Ambiguous matches are withheld.
The existing SofaScore daily collector resolves these stable IDs against both
teams, league and kickoff when APINN returns; its schedule and writes are unchanged.
Fallback IDs are never sent to APINN endpoints. Existing favorite sides, OPEN
prices, recorded 90-minute prices, results and manual notes are preserved.
Fallback quotes stop five minutes before kickoff. A missed 90-minute snapshot
cannot be reconstructed from a late current quote.

Contra +0.5 uses only the exact full-match spread: away price at home handicap
-0.5 for a home favorite, or home price at +0.5 for an away favorite. If absent,
current J is blank; historical OPEN/90 prices remain intact. Prices are never
derived from moneyline or an adjacent handicap. Missing odds can limit dependent
signals. `ODDS SOURCE:` logs identify the selected provider without logging keys.

Run the offline regressions with:

```sh
python -m unittest -v test_pinnodds.py
```

Tests execute the real writer with fake HTTP/Sheets boundaries and cover provider
handoff, automatic discovery, fixed favorite sides, locked snapshots, missing
markets, stale feeds, request budgets, schedule/DST, and independent turnover.

## SofaScore daily snapshot

Render fills blank N values once per day near 12:30 Europe/Athens, and stores
stable fixture-to-SofaScore links in SOFA CACHE for the independent Google Apps
Script result writer in P. Fixtures already saved in PINNACLE remain usable
when APINN is unavailable. Manual N values are preserved, including values
entered while collection is waiting. An overnight fixture stays in the current
daily result batch. Neither the odds source order nor the paid schedule changes.

Germany Bundesliga 2 maps to SofaScore tournament 44; Belgium Challenger Pro
League maps to tournament 9, before their first-division name fragments.

The existing vote batches still contain at most five events. Each paid batch is
started once and returns a run ID; waiting and dataset retrieval use GETs for
that same run. Up to three batches can be in progress, with a shared 100-second
wait budget, a bounded Actor timeout and time reserved for Sheet writes before
the runner's 240-second limit. A lost start response is never retried. Missing
or unfinished batches remain blank; later ten-minute crons never repeat the
daily paid attempt. No manual catch-up is implied by a deployment.

An explicitly requested manual catch-up can reuse a successful fixture dataset
from the preceding 15 minutes when every needed team pair and kickoff matches.
It reads that existing run without starting another fixture Actor; normal daily
collection is unchanged.

ALERT STATS P3 reports matched/eligible, missing mappings, unmatched fixtures,
missing votes, writes and preserved values. Partial coverage is PARTIAL or
NO DATA, never DONE. These counts describe the snapshot; they do not prove that
Google's separate result/fixture workers are healthy. A missing SofaScore link
can still prevent that result worker from seeing a fixture. Provider failures
and unknown team names may therefore still leave real gaps.

Run the additional offline collector regressions with:

```sh
python -m unittest -v test_sofascore_candidates.py test_sofascore_reliability.py
```

## Alert font fitting

Column O displays the original full alert text. From 27 October 2026,
upcoming fixtures show all approved independent signals together with both Over
markets. The old primary remains first and retains its existing strength; other
signals are appended without inventing individual scores. The core strong/simple/
watch family stays hierarchical and the actionable Contra guard still applies.
Live O shows only configured ACTIVE signals. Research-only rules and ADMIN_ONLY
WATCH Contra stay in the helper/research view. The current approved eight are
Contra, Favorite, FAV60, FAV75, SOFA+turnover, Favorite reversal, Over1.5k and
Over1.5. Settled/past fixture formulas are untouched.

`alert_display.py` adapts only O's font from 11pt down to 6pt as the text grows.
It uses embedded Carlito Bold glyph advances and preserves the existing column
width, row heights, labels, colors, alignment and other font properties. It clears
the former literal-label number formats to plain text. It never resizes rows or
changes any neighboring cell. Very long combinations can still exceed the fixed
width at the minimum size; complete names remain in the actual cell value.
The collector and history reader continue reading canonical unformatted O values.
Font fitting runs after collector and history recalculation, including withdrawals
and empty tails. The layout cleanup hides internal R:CG columns and clips Q
comments without changing their values, formulas, or font. AZ:BA are visible
exceptions after Q: they show the real F/I 90-minute favorite and Contra +0.5
snapshots. Missing mirror formulas are installed on new rows without replacing
manual display values; they stay blank until a numeric snapshot exists.

Offline presentation/recording regressions:

```sh
python -m unittest -v test_alert_display.py test_parallel_alerts.py test_alert_helpers.py test_side_goal_alerts.py
```




# ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ −2%: prospective research

From 2026-10-28 02:45 Europe/Athens, this rule independently records original-favorite wins for the seven `BIG_LEAGUES`: current K turnover percentile strictly above 87 within the same league and fresh G <= F * 0.98 after the stored approximately -90-minute F snapshot. Only existing collector observations are consumed; no provider requests or extra scheduled runs are added.

The first qualifying fresh quote between -90 and -5 minutes inclusive is counted once. Entry G, original favorite side, F, K, percentile, league sample size and capture time are frozen in the dedicated `ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ −2%` sheet. Later departures, rerankings or quote changes never remove an entry or replace its entry price. Draws are favorite failures. Missing results stay pending. The historical 12/13 study remains separate; prospective counters start at 0/0.

This rule is ACTIVE in ALERT LEVELS following the user's 28 October promotion. It has no opening-odds, latest-odds-range, money-share, Sofa, home/away or clock-hour filter. It does not change the existing ΦΑΒΟΡΙ ΠΤΩΣΗ 2% rule. After Sofa updates, alert_history settles existing records; the level review preserves ledger-owned counters. The existing Contra Rise90 ledger also preserves its original entries across subsequent exact-quote reads.
# ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ 80%: prospective variant B

From 2026-10-28 03:04 Europe/Athens, variant B independently tracks original-favorite wins in BIG plus OTHER EUROPE leagues: current K rank >87 within the same league, total current favorite money L >=80%, and fresh G <= the stored -90-minute F. Stable prices and any decline qualify; no 2% minimum drop, Sofa, opening/latest price range, home/away or clock-hour filter applies.

The shared entry engine preserves variant A's criteria, identity, start time and ledger. B uses a separate `maroon80:` identity and 22-column ledger, freezes total money share and category alongside entry odds/color, and counts the first qualifying fresh observation from -90 to -5 inclusive once. New counters start at 0/0 separately for BIG and OTHER EUROPE. The historical 26/29 and 4/5 from row1020 remain benchmarks only. B is ACTIVE following the user's 28 October promotion. Existing level review never overwrites its prospective counters.

# ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ ≤1,70: prospective variant C

From 2026-10-28 13:11 Europe/Athens, variant C independently tracks original-favorite wins in BIG and OTHER EUROPE: current same-league K rank >87, total current favorite money L >=80%, and fresh current odds 1 < G <=1.70. It does not compare G with F. Rising odds and a missing F snapshot are allowed. Existing A/B definitions, identities, launch times and counters remain unchanged.

The first qualifying fresh quote from -90 to -5 minutes inclusive is counted once, freezing original favorite, entry G, K color/rank, total L, category and capture time in its own 22-column ledger. Optional F and price movement are informational only. Draws are failures; unknown scores stay pending. Prospective counters start at 0/0, apart from historical study benchmarks. The rule is ACTIVE following the user's 28 October promotion. Existing result and review integration settles only recorded picks and preserves the dedicated counters.

## Maroon A/B/C public operation

`favorite_maroon_live.py` publishes all independently issued A/B/C picks together in PINNACLE O after the three entry ledgers update. A matching real first fresh observation is required; current or historical final values alone never publish a signal. Issued picks stay visible and counted at their original entry odds even if later quotes withdraw the condition. Each rule has one separate entry per match. The existing font-fitting pass applies only to O. No new PINNACLE columns, provider requests, schedules or manual runs are introduced.

Publication wraps and preserves the existing O formula, checks the fixture's league, teams, original side and kickoff to prevent row reuse, honors each ACTIVE status independently, and never rewrites started/settled matches. The existing 1.39 opening floor remains inside the legacy formula; it is not imposed on Maroon A/B/C. History retains only these three exact approved identities below that floor and routes them through the existing alert log/notification workflow. Dedicated ledger metrics and all historical benchmarks remain separate.

## Frozen first morning-turnover colors

`morning_turnover.py` classifies the first stored T turnover across all PINNACLE competitions, separately per exact league. The user's latest 28 October instruction replaces v2 physical-row prefixes with a common numerical reference: every valid nonnegative first morning T already available in the same league, including the current atomic batch. Rank, color, reference size and mean do not depend on the fixture's physical row position. It retains the same empirical-rank convention and 35/75/87 boundaries as current K colors. Closing K, -90 W, money shares and Sofa never influence this classification.

Hidden CI:CQ stores the immutable rank, hex color, lock time, sample size, league mean, capture mode, original T, fixture identity and JSON evidence. The original v1 full-sample backup remains intact, and v2 row-order records are backed up before the one-time historical rebuild. Existing historical amounts are classified as HISTORICAL_COMMON_REFERENCE against the complete saved same-league morning-T cohort; this is a historical comparison and does not claim original capture timestamps or a reference available at those original times. New v3 FIRST_OBSERVATION locks accompany the actual first T:V write in the same collector batch, using all same-league morning T available at that capture time, regardless of row position. The evidence records that reference time. Adding later matches never re-ranks existing locks. Historical v1 and v2 modes remain reproducible for their archives. Both the independent Arbworld and regular odds paths share the existing final batch hook, with no provider calls or schedule changes.

Only T receives the new conditional colors. Its existing numeric format and all K/W/O rules stay intact. Missing/non-numeric/negative T remains uncolored; a changed T or reused fixture identity cannot inherit another observation's color. If preparing a first lock fails, the new T:V snapshot is withheld for retry while the rest of the live update continues. Historical benchmarks, alerts A/B/C, entry evidence and their counters are unchanged.

## Frozen final prematch-turnover colors

`final_turnover.py` archives the last stored prematch K after kickoff, or when a displayed score establishes that play has started. It uses raw numeric K and a common reference of finalized K snapshots in the exact same league, with 35/75/87 boundaries. Fixtures still before kickoff and records with unverified finality do not train this final reference. A one-time historical rebuild may include separately verified archival evidence without inventing a kickoff or quote timestamp. Frozen rank, color, lock time, population, mean, mode, original K, fixture identity and JSON evidence occupy hidden CR:CZ. Completed snapshots never re-rank when later fixtures arrive; their immutable source K trains subsequent final locks.

The CR1 activation marker is installed atomically with the native historical backfill and conditional rules. The existing live K color rules continue until finalization. After finalization, frozen colors take precedence and dynamic K rules exclude valid locks. The collector hook shares the existing final batch, handles unchanged terminal rows even when no new quote is available, and suppresses later K:M writes for a matching locked fixture while preserving other updates. A reused identity cannot inherit an old lock; a read failure defers finalization without withholding unrelated live data. Morning T locks, BM, public alert formulas, actual entry ledgers and their counters are not rewritten. No additional provider calls, schedules or manual collector runs are introduced.

