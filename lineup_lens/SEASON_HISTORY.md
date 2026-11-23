# Verified full-season starts — Lineup Lens

This is a development branch, **not deployed**. Existing production stays on `lineup-lens-personal`.

Goal: show `12/14` starts **across the full season** using official starting XIs, not the last five.

1. `season_core.py` validates the 11 unique starters from both confirmed official lineups and counts starts without duplicating matches. No predictions are counted.
2. `season_schema.sql` defines permanent PostgreSQL tables and separate tracking for total finished fixtures versus verified lineups. If some XIs are missing, the UI must say `12 starts / 13 verified of 14 played`, never invent a complete ratio.
3. Next: choose a durable database, add an authenticated batch importer and an incremental official-XI collector, then integrate into the existing Flask screen.
4. Read-only source assessment first: existing Soccer Data free API currently allows only ~50 requests/day, so a full-season historical backfill needs pagination, quota accounting, caching, and potentially a different provider.

**Important:** Render free web storage (`/tmp`) is ephemeral; Render free Postgres expires after 30 days. Do not deploy seasonal data on either. No credentials are stored in the repository. Do not change SharpVision.
