# DreamTeamTips — Prelaunch Status

Updated: 2026-10-04

## Ready / implemented

- Customer public level symbols:
  - Favorite: 🔷 / 💎 / 👑
  - Contra: 🎯 / ⚡ / 💣
- WATCH alerts are customer-hidden / Admin-only.
- TEST alerts are customer-hidden until they have enough sample.
- A hidden `ALERT LEVELS` sheet is the central level registry.
- Level evaluation scope excludes:
  - USA / Brazil / Argentina
  - all national-team competitions
  - Greece Super League 2
- Current-rule backtests now respect core alert priority so higher-priority core alerts are not double-counted as lower-priority core alerts.
- Existing alert-specific league exclusions are preserved during backtests.
- A guarded 15-day review engine is deployed in the cron project.
- Next review is currently 2026-10-19.
- `AUTO_APPLY` is FALSE before public launch, so review calculations cannot silently change live levels yet.
- Public level statistics have NOT started. `PUBLIC_STATS_START` is intentionally blank until the owner explicitly says the service is open.
- Review engine writes clean metrics + suggested level/trend while preserving the current live mapping.
- Cron test after deployment succeeded and correctly logged that the review was not due.
- Newer BZ:CC favorite alert formulas are now part of the permanent cron writer and live alert aggregation, preventing current rows from losing those alerts.

## Important prelaunch audit finding

When the core hierarchy is reproduced correctly, overlapping high-priority alerts must not also count as plain alerts.

Clean current-rule examples:
- ΔΥΝΑΤΟ ΚΟΝΤΡΑ: 26/28
- ΚΟΝΤΡΑ: 7/11 (not the earlier overlapping 33/40)
- ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ: 12/13
- ΔΥΝΑΤΟ ΦΑΒΟΡΙ: 6/6, still TEST due to sample
- ΦΑΒΟΡΙ: 9/12
- WATCH ΚΟΝΤΡΑ: 2/9
- WATCH ΦΑΒΟΡΙ: 19/34

Current mapping is intentionally NOT silently rewritten because of this correction. The hidden level registry currently flags:
- ΚΟΝΤΡΑ: candidate down ⚡ -> 🎯
- ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ: candidate up 🎯 -> ⚡
- ΦΑΒΟΡΙ: candidate down 💎 -> 🔷

These are candidates for the review policy, not retroactive edits.

## Still intentionally pending

### Apps Script live sync
The repository version of `private_backend.gs` has been prepared to:
- read the `ALERT LEVELS` registry,
- select the highest ACTIVE public level when a match has multiple internal alerts,
- keep WATCH/TEST internal,
- expose level score / record / next review / trend to Admin.

Do not replace the live Apps Script blindly: the deployed Apps Script contains account-specific configuration such as the real ADMIN_CODE and may contain newer live functions not represented by the repository snapshot. Apply only a reconciled patch to the live Apps Script when doing the final backend sync.

### Device tests
Real-device verification remains necessary for:
- owner/Admin push registration,
- customer push,
- one-device login behavior on two physical devices.

Latest cron evidence still shows owner push targets at zero devices, so this cannot be declared complete from code inspection alone.

### Public stats launch
When the owner explicitly says “ανοίγουμε”:
1. record the public-stats start timestamp,
2. initialize each of the six public symbols at 0/0,
3. enable public-stat result tracking,
4. turn on level AUTO_APPLY only after the live Apps Script is reconciled,
5. preserve the symbol/level assigned at publication time for historical integrity.
