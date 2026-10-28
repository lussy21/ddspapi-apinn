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

This is `RESEARCH_ONLY` in ALERT LEVELS. It has no opening-odds, latest-odds-range, money-share, Sofa, home/away or clock-hour filter. It does not enter public O or notifications, and it does not change the existing ΦΑΒΟΡΙ ΠΤΩΣΗ 2% rule. After Sofa updates, alert_history settles existing research records; the level review preserves ledger-owned counters. The existing Contra Rise90 ledger also preserves its original entries across subsequent exact-quote reads.
