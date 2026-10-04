# DreamTeamTips — Alert Levels Method

Last agreed: 2026-10-04

## Purpose
This document is the reference for how a NEW internal alert is evaluated and assigned to a customer-facing level.

The internal alert name never determines its level. Labels such as "ΔΥΝΑΤΟ" are ignored for grading. The level is earned from data.

## Public symbol system

### Favorite side
- Level 1: 🔷
- Level 2: 💎
- Level 3: 👑

### Contra side
- Level 1: 🎯
- Level 2: ⚡
- Level 3: 💣

If more than one internal alert is active for the same match and same direction, the customer sees ONLY the highest public level. The match must count only once in public statistics, under that highest level.

## Dataset scope for grading
Use the `PINNACLE` sheet only.

For historical evaluation, run the CURRENT alert rule retrospectively over all compatible historical rows in `PINNACLE`, regardless of when the alert was first discovered.

### Core-rule priority is mandatory
For the legacy/core family, the backtest must reproduce the same IFS/priority used by the live model. A row that qualifies for a higher-priority core alert must NOT also be counted as a lower-priority core alert.

Current core priority:
1. ΔΥΝΑΤΟ ΚΟΝΤΡΑ
2. ΔΥΝΑΤΟ ΚΟΝΤΡΑ (+10)
3. ΔΥΝΑΤΟ ΦΑΒΟΡΙ
4. ΚΟΝΤΡΑ
5. ΦΑΒΟΡΙ
6. WATCH ΚΟΝΤΡΑ
7. WATCH ΦΑΒΟΡΙ

Independent alerts such as turnover, reversal, 3X and drop alerts are evaluated by their own rules and may coexist on the same match. For the customer, coexistence is resolved by showing only the highest public level.

INCLUDED:
- Main leagues
- "Λοιπά Ευρώπης"

EXCLUDED:
- USA
- Brazil
- Argentina
- all `ΕΘΝΙΚΕΣ - ...`
- `Greece - Super League 2`

The excluded categories are to be evaluated separately later and must not affect the current public level grading.

## Metrics used

Each alert is evaluated with four dimensions:

1. **Real ROI / edge — 35%**
   - Use the available relevant odds from the PINNACLE row.
   - For favorite alerts use favorite odds.
   - For contra alerts use contra odds.
   - ROI is important because hit rate alone can be misleading.

2. **Adjusted success rate — 30%**
   - Do not trust raw hit rate alone.
   - Small samples are penalized using a conservative estimate (Wilson lower bound / equivalent conservative adjustment).
   - Example: 5/5 must not be treated as equal evidence to 20/20.

3. **Sample reliability — 20%**
   - More completed qualifying matches = more confidence.
   - Very small samples stay TEST / WAITING even if raw success is 100%.

4. **Stability — 15%**
   - Check that the alert does not depend on one short streak.
   - Compare performance across time / sub-samples and, when useful, across leagues.
   - A signal that collapses in one half of the sample must be downgraded.

Reference weighting:
- 35% ROI / edge
- 30% adjusted success
- 20% sample
- 15% stability

## Review cadence and movement rules

The public level of an alert is NOT recalculated every day.

- Official review cadence: every 15 days.
- Between reviews, the current public level stays locked.
- At review time, recompute the alert from the allowed PINNACLE scope using all completed qualifying matches.
- Maximum movement per review: one level up or one level down.
- New alerts remain TEST / WAITING until they have enough sample.

Working score thresholds (diagnostic, not a blind auto-switch):
- Level 1 -> Level 2: score >= 62 and enough sample (normally at least 12-15 completed matches).
- Level 2 -> Level 3: score >= 80 and at least 20 completed matches.
- Level 3 -> Level 2: downgrade only if score < 72.
- Level 2 -> Level 1: downgrade only if score < 55.

Important: the score is a decision aid, not the only criterion. Favorite and contra alerts have different odds/hit-rate profiles. The automatic review must also respect family-specific evidence and sample size; it must not downgrade or upgrade solely because a generic ROI-heavy score crossed one line. Until family-specific gates are validated, the system may calculate a recommendation/trend but must not silently rewrite the live level.

This creates a safety band (hysteresis) so one or two results cannot make an alert bounce between levels.

Historical integrity rule:
- A selection keeps the level/symbol it had when it was published.
- A later review changes only future selections.
- Past public statistics are never rewritten because an alert later moved level.

Admin should show, when available:
- current symbol / level
- current quality score
- last review date
- next review date
- trend toward the next/previous level
- last level change

## Practical safeguards

- No Level 3 from a tiny sample.
- A 100% raw hit rate does NOT automatically mean Level 3.
- High ROI alone does NOT automatically mean Level 3.
- Favorite and contra alerts can have different natural hit-rate profiles.
- WATCH alerts stay Admin-only unless explicitly reclassified later.
- New alerts begin as TEST / WAITING until there is enough sample to evaluate.
- Re-grade only after meaningful new data, not after every single result.
- Do not use America, Nationals or Super League 2 to raise/lower the current level.

## Current mapping (agreed working mapping)

### Contra
- 🎯 Level 1: ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ
- ⚡ Level 2: ΚΟΝΤΡΑ
- 💣 Level 3: ΔΥΝΑΤΟ ΚΟΝΤΡΑ
- TEST / waiting: ΔΥΝΑΤΟ ΚΟΝΤΡΑ (+10)

### Favorite
- 🔷 Level 1:
  - ΦΑΒΟΡΙ ΤΖΙΡΟΥ 3X
  - ΦΑΒΟΡΙ SOFA+3X
  - ΤΖΙΡΟΣ ↑
  - ΦΑΒΟΡΙ 84+P60

- 💎 Level 2:
  - ΦΑΒΟΡΙ
  - ΦΑΒ 60+
  - ΦΑΒ 75+
  - ΦΑΒΟΡΙ ΠΤΩΣΗ 2%

- 👑 Level 3:
  - ΦΑΒΟΡΙ ΤΖΙΡΟΥ
  - ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ

- TEST / waiting:
  - ΔΥΝΑΤΟ ΦΑΒΟΡΙ

## Current benchmark snapshot used for the working mapping
Scope: Main + Λοιπά Ευρώπης only; America, Nationals and Super League 2 excluded.

Core family (priority-corrected):
- ΔΥΝΑΤΟ ΚΟΝΤΡΑ: 26/28 (92.9%), avg odds ~1.77
- ΔΥΝΑΤΟ ΚΟΝΤΡΑ (+10): 2/3 (66.7%), avg odds ~1.96 — TEST
- ΚΟΝΤΡΑ: 7/11 (63.6%), avg odds ~1.95
- ΔΥΝΑΤΟ ΦΑΒΟΡΙ: 6/6 (100%), avg odds ~1.27 — TEST because sample is too small
- ΦΑΒΟΡΙ: 9/12 (75.0%), avg odds ~1.44
- WATCH ΚΟΝΤΡΑ: 2/9 (22.2%), avg odds ~2.23 — Admin only
- WATCH ΦΑΒΟΡΙ: 19/34 (55.9%), avg odds ~1.64 — Admin only

Independent alerts:
- ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ: 14/18 (77.8%), avg odds ~2.12
- ΦΑΒΟΡΙ ΤΖΙΡΟΥ: 22/23 (95.7%), avg odds ~1.31
- ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ: 20/22 (90.9%), avg odds ~1.34
- ΦΑΒΟΡΙ ΠΤΩΣΗ 2%: 10/12 (83.3%), avg odds ~1.63
- ΦΑΒ 60+: 41/49 (83.7%), avg odds ~1.35
- ΦΑΒ 75+: 29/36 (80.6%), avg odds ~1.33
- ΤΖΙΡΟΣ ↑: 9/12 (75.0%), avg odds ~1.84
- ΦΑΒΟΡΙ 84+P60: 8/10 (80.0%), avg odds ~1.65
- ΦΑΒΟΡΙ ΤΖΙΡΟΥ 3X: 13/19 (68.4%), avg odds ~1.78
- ΦΑΒΟΡΙ SOFA+3X: 14/19 (73.7%), avg odds ~1.81

These are benchmark values, not permanent promises. Recompute from PINNACLE when re-evaluating.

The currently assigned symbols remain a working mapping until a review explicitly changes them. Correcting a historical calculation does not silently rewrite already-agreed/public levels.

## Public statistics launch rule
When the user explicitly says the customer-facing system is officially open:
- Public statistics for all six symbols start at 0/0.
- Historical internal results remain available for internal evaluation only.
- From launch onward, each published match increments only the highest public symbol that applied to that match.
- Do not backfill old internal history into the customer-visible symbol statistics.

## Procedure for any future new alert

1. Freeze the alert's exact rule.
2. Run that exact current rule retrospectively on the allowed PINNACLE scope.
3. Collect:
   - wins / total
   - raw hit rate
   - average odds
   - ROI
   - conservative adjusted hit rate
   - sample size
   - stability
4. Compare it with existing alerts of the SAME direction.
5. If sample is too small, keep it TEST / WAITING.
6. Assign Level 1 / 2 / 3 only after the data supports it.
7. If a match triggers multiple alerts, surface and count only the highest level.

This file is the single reference for future alert grading unless the method is explicitly changed later.
