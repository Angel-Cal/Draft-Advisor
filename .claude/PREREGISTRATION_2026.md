# 2026 evaluation: rules fixed before the results are in our data

Written 2026-10-28. The point is to stop the choices (who counts, which threshold, which comparison) from being shaped by how the season turns out. Do not edit the
rules below after the 2026 results are loaded; a change is a new hypothesis for 2027.

## What is frozen

- **Snapshot:** `.claude/snapshots/projections_2026_preseason.csv` (300 players: projection, ADP, the ADP-curve expectation, the gap, the three role-context fields and the
  role-caution flag). Made by `python src/evaluation/preseason_eval.py snapshot --season 2026`.
- **SHA-256 of the snapshot:** `e258935710f031495e34bf35b5ee93437b1896137612528bfede2c85751d21d3` (LF line endings; remove carriage returns before hashing if git converted them).
- **Source file:** `projections_2026_v1.json`. First generated 2026-10-27 21:25 UTC (git commit `54ac694`, SHA-256 `1ddaf4981be57bb2d717d953e7d1703fd010d66e39d37a8636703967b056e3b4`), re-exported
  2026-10-28 20:21 UTC (commit `df6e229`, SHA-256 `01612b4f97c75d3f0758a702a674735f51bf5a56390ebda74606a388cccfbc57`) to add the role-context fields. Every pre-existing field is identical between the two.
- **Scorer:** `python src/evaluation/preseason_eval.py score --season 2026 --actuals <seasonal stats parquet with 2026> --exclude 00-0038117`

## Why this is not a clean pre-season test (known limits)

- The projections were last regenerated on 2026-10-27, after the 2026 season began (opener 2026-09-09). Their inputs hold no 2026 game results (the weekly and seasonal files end with 2025;
  the depth chart used is the last snapshot before the opener).
- The 2026 rosters were scraped 2026-10-21, about seven weeks into the season, so `team_changed` and `rookie_r1_teammate` reflect those rosters, not the pre-season ones.
- The ADP file is from 2026-03-25 (before camp), so the gap to the ADP curve is measured against an early ADP.
- The user had already seen W.Robinson's early-season result ("a massive miss so far") when these rules were written. His id, `00-0038117`, is reported with and without.
- No other 2026 results are in this project's data. The first clean test is the 2027 pre-season freeze (see the end).

## Population

WRs in the snapshot that were modeled (not `market_estimate`), within the top 150 by ADP among modeled players (`in_top_adp`), with 9 or more games played in 2026 (regular season, all teams
summed). Two-way players are excluded from the competitor set (`TWO_WAY_PLAYERS`). The outcome is the player's 2026 regular-season PPR. Over-projection = projected PPR minus actual PPR.
The 2022-2025 rows come from the same definitions (`load_rows`, healthy seasons only). Draftable in the snapshot: 58 WRs; flagged and draftable: G.Wilson, J.Waddle, W.Robinson (E.Ayomanor is flagged but outside the top 150).

## Hypotheses and decision rules

**H1, the role caution.** WRs flagged by the rule (`absence_share_prev` >= 0.5 AND (changed teams OR a first-round rookie WR/TE on the roster)) are over-projected more than the other WRs.
Measure: the difference in mean over-projection, flagged minus rest, with a 90% bootstrap interval resampling players; reported for 2026 alone, pooled with 2022-2025, and each without `00-0038117`.
Rule, on the pooled estimate: **supported** if the interval's lower bound is above 0 (then test a score adjustment leave-one-season-out before touching the recommender); **not supported** if the
lower bound is at or below 0 and the 2026 difference alone is at or below 0 (then reconsider keeping the caution); **inconclusive** otherwise (keep the text caution as it is and wait for 2027).
For reference, 2022-2025 alone: 11 flagged, +24.3 PPR over-projected against -4.7 for the rest, difference +29.0 (-5 to +59); the ADP curve over-projected the flagged rows by +21.5.

**H2, how far to trust big gaps.** Among WRs whose gap to the ADP curve was 30+ PPR (the likes) and -30 or lower (the fades), the slope of (actual - curve) on (model - curve): 1 means the model's gap was
right, 0 means the curve was. Reported alone and pooled, with 90% intervals. No decision attached; the reference is the pooled 2022-2025 healthy-season slopes, likes 0.56 (0.12 to 1.01) and fades 0.51 (0.17 to 0.83).

**H3, the named players.** Every modeled WR with a gap of 30+ (Diggs, Samuel, Robinson, K.Allen, Tucker, Bateman, Wicks as of the snapshot): their projections against their results. Descriptive only.

## What may not change

The thresholds (absence share 0.5, gap 30, 9 healthy games, top 150), the definition of a new situation, the exclusion list above, the metrics and the pooling. Players are dropped only for fewer than 9 games.
Nothing new gets tested on these 2026 results and called pre-registered; any idea that comes out of looking at them is a 2027 hypothesis.

## Procedure

1. After the 2026 regular season (January 2027), refresh the raw seasonal stats to include 2026 (`src/data/scraper.py` loads seasons 2014-2025 today; extend the ranges to 2026).
2. Run the scorer command above, with `--actuals` pointing at the refreshed file.
3. Record the results and the decision under the rules above in `LOG.md`.

## 2027: the clean version

In the first week of August 2027, before the draft, regenerate the projections, rosters and ADP, run `snapshot --season 2027`, record its SHA-256 here, and score it after the season with the same
rules (pooled with 2022-2026). That freeze is the first one with fresh rosters and a current ADP.
