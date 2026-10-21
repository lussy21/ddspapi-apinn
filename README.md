# ddspapi-apinn

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
use `pinnodds:<id>` in R; existing APINN IDs are retained during standby. APINN
recovery replaces fallback IDs on the same rows. Ambiguous matches are withheld.
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
