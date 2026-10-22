# DraftBot Decision Log

The *why* behind choices that mattered. `STATUS.md` says where the project is, git history says what changed;
this says why we chose it and what we rejected.

**Add an entry only if** the decision (1) rejected a plausible alternative, (2) changed the results, or (3) you would
probably forget the reason in three months. Keep it to 3–5 lines: decision, reason with the number that justified it,
alternative rejected, pointer to the commit or test. Newest first. Do not log routine choices.

Standing rules (apply to every entry below):
- A feature is accepted only if it beats a 10-seed baseline *and* a random-noise control of the same size; anything
  within noise is dropped. Gaps under ~0.03 top-150 Spearman are not detectable with 5 test seasons.
- Ask before making a design decision that was not specified.

---

## 2026-10-21 — Fixed: playoff weeks in expected-points features; dead `passing_cpoe_delta` column
**Decision:** `build_xfp_features` keeps regular-season weeks only (<= 17 through 2020, <= 18 from 2021); `passing_cpoe_delta` is
dropped from the RB/WR/TE models. Found while explaining points-over-expected; the user asked to fix mistakes as they are found.
**Why / effect:** playoff rows were ~3% of `ff_opportunity`, so `xfp_ppr_prev`, `xfp_pg_prev` and `fp_over_exp_prev` were inflated for
playoff teams, inconsistent with every other (regular-season) feature. Full rebuild (pipeline, OOS, benchmark, predict, vor, export):
no measurable change (see STATUS.md). Unit test `test_xfp_features_ignore_playoff_weeks`; the integrity test now recomputes xfp on
regular-season weeks. **Not decided:** whether to build efficiency-rate / volume-sustainability features (see the Robinson case study
in STATUS.md); the user is only exploring.

## 2026-10-21 — 2025 investigation: the recommender's position rule, not the model, drives the big swings
**Decision:** treat the recommender's position step (scarcity = unfilled league slots / players in the best tier) as the thing
to replace in Phase 4; the model's player ranking is fine and roughly ADP-neutral.
**Why:** windowed lost 243 points to ADP in 2025 (1549 vs 1792). (1) The model was not worse that year: Spearman vs actual in the
top 150 was 0.451 model vs 0.379 ADP, edge-vs-market correlation +0.13, RMSE 78.8 vs ADP-curve 77.0 (same gap as 2022/2024).
(2) 2025 was a positional outlier: the first 12 RBs by ADP averaged 293 actual points (215-258 other years), 5 boomed; RB minus WR
was +72 (others -52 to +14); 4 of the top 12 WRs busted; early QBs fell 98 under the ADP curve. (3) With tiers this small every
position has one player in its best tier, so scarcity just picks the position with the most unfilled slots (WR, 3 slots), so
windowed drafts 2.7 RBs and 9.3 WRs per team (ADP: 5.4 and 6.6) and its rounds 1-3 average 174 actual points vs 262.
(4) Decomposition, mean starter points per season (2021..2025): ADP 1801/1747/1780/1846/1802; windowed 1813/1676/1833/1882/1556;
recommender chooses the position and ADP the player 1874/1595/1787/1931/1578; ADP chooses the position and the recommender the
player 1795/1793/1813/1792/1768 (mean 1792 vs ADP 1795). The position rule reproduces the swings; the player rule alone never
strays far from ADP. So the 5-season mean deficit is a high-variance WR-heavy bet that paid in 2021/2023/2024 and lost in 2022/2025.
**Model miss, smaller:** McCaffrey (ADP 8, flagged after a 4-game season) was projected 169 and scored 417, about 49 of the points.
**Caveat:** 5 seasons; the RB-WR gap and windowed's result agree in 4 of 5 years (2022 does not fit). **See:** `diagnose`,
`decompose` (`PickDiagnostics.cs`).

## 2026-10-21 — Reach control: soft penalty on ADP reach plus a far hard cap (provisional default l=0.3, cap 4 sigma)
**Decision:** the recommender gets an optional `ReachSettings`. A player whose ADP is later than the current pick is a reach of
z = (ADP - pick) / sigma(pick) with sigma = 2 + 0.16 x pick; the score loses lambda x z^2; players past `cap` sigma leave the
pool for BOTH the position step and the player step (a position with nobody left cannot be chosen). Slid players (ADP before the
pick) are never penalized. Added as a variant (`windowed`) beside the untouched baseline (`recommender`).
**Why:** the user saw the first pick recommend ADP 70-112 players at pick 6 (the `value_gap` term is itself a bonus for late
ADP) and wanted a window that widens later in the draft, but a hard border would rule out a player the model loves that sits just
outside it. The spread is measured: cross-platform SD of ADP (ESPN, Sleeper, NFL, RTSports... in the cached FantasyPros pages,
2021-2025) is 0.8 picks at ADP 1-6, 4.5 at 24-36, 14 at 84-120, 29 at 160-200, about 0.16 x ADP. That is a lower bound for the
spread inside one draft, which is a second reason for a soft penalty (a too-tight sigma costs little).
**Sweep (30 seeds x 12 slots x 5 seasons, noise x1, 30 arms):** baseline recommender 1547; the cap alone (lambda 0) 1672-1730;
cap plus penalty 1724-1760, best around lambda 0.1-0.3, cap 3-4, with or without the gap term; plain ADP 1792. A plateau, not a
peak. Leave-one-season-out gain over the baseline +154 +/- 69; still -90 +/- 48 vs ADP because the chosen arm changes by fold.
At the default (100 seeds, noise x0.5 / x1 / x2): windowed 1743 / 1755 / 1788 vs ADP 1772 / 1796 / 1853 (-28 / -41 / -66 +/- 3).
By season at noise x1 it beats ADP in 2021 (+23), 2023 (+52), 2024 (+39) and loses in 2022 (-75) and 2025 (-243).
**Rejected:** a hard band (cliff; the user's Barkley example), round-based steps, shrinking projections toward ADP (bigger change).
**Open:** it still does not beat ADP; 2025 is a large miss; the position step still loops (see the mock-draft entry). The
spread constants and the default are unvalidated. The simulator's opponent noise (1 + 0.1 x ADP) is below the measured
cross-platform spread (0.16 x ADP) and probably too tame. **See:** `ReachSettings`, `ReachTuning.cs`, `tune-reach`.

## 2026-10-21 — Mock draft tool; it exposed that the recommender drafts quarterbacks without end
**Decision:** added `draft` (interactive mock draft, past seasons only, simulated opponents, reasoning shown each turn). It
exposes the recommender's scarcity numbers and score components through `BaselineRecommender.ChoosePosition` and
`Candidate.RankTerm/GapTerm/Penalty`; behavior is unchanged (simulator result identical before and after).
**What it showed (2024, slot 6, always taking its #1):** the recommender takes 7 QBs (rounds 8, 9, 11, 13-16) and 2 TEs. The
simulator's cap of 2 QBs hid this by turning those picks into best-VOR fallbacks, so the simulated "recommender" is already
better than the raw one. At pick 6 every position has one player in its best tier, so "scarcity" is just unfilled league slots
per position and WR wins; it then takes an ADP-78 WR (K.Allen) over A.St. Brown (ADP 6) and Jefferson (VOR 124).
**See:** `csharp/src/DraftBot.Sim/MockDraft.cs`, `MockDraftTests.cs`.

## 2026-10-21 — Regret per round: hindsight mostly measures luck; foresight shows where strategies deviate
**Decision:** regret is reported three ways per pick, against the best LEGAL available player (roster rules respected): hindsight
actual points, hindsight over replacement (actual minus the position's actual-points replacement level, same FLEX rule), and
foresight projected VOR. Only the strategy's own picks count. CSV: `data/processed/sim_regret.csv`.
**Why / what it showed (noise x1, mean per draft):** hindsight regret is ~120-230 points per pick in every round, even round
16, because the best available player in hindsight is always some breakout; it separates the recommender (2751 total) from
ADP (2487) and VOR (2411) but not ADP from VOR, even though ADP scores 100 points more. Use it for early-round comparisons, not
as a headline. Foresight: VOR is 0 by construction, ADP gives up 38 VOR per pick (608 total), the recommender 259 total with
52 in round 1 and ~0 by round 14, so its damage is early reaching. **Rejected:** a single regret definition; foresight alone
(says nothing about outcomes), hindsight alone (luck).

## 2026-10-21 — Tier threshold k = 0.10 (was 0.20): gap-based tiers show no real cliff signal
**Decision:** default tier threshold is 0.10 x position RMSE (about 13 tiers per position, largest tier 34% of the pool).
**Why:** `tune-tiers` scores each k by adjusted R2 of actual points on tier labels MINUS the same score for equal-size tiers
of the same count (raw adjusted R2 just rises as tiers get finer, so it cannot pick k). Leave-one-season-out picks k = 0.03
(~26 tiers per position, about 1.5 players each), gain over 0.20 +0.13 +/- 0.08, negative in 2 of 5 held-out seasons, so not
a usable tier count. At usable counts (4-8 tiers, k 0.15-0.25) gap tiers do WORSE than equal-size tiers (k = 0.20: -0.12)
because they leave one giant tail tier (79% of players); only TE shows a consistent cliff signal (+0.06 at k 0.10-0.25). At
k = 0.10 the advantage is about zero (+0.014), and the recommender gains ~40 points over 0.20 (1547 vs 1511 at noise x1);
anything <= 0.10 gives the same gain, none closes the 250-point gap to ADP. User chose 0.10 over the procedure's 0.03.
**Rejected:** per-position k (more search space than 5 seasons support), 0.03, keeping 0.20.
**Open:** projection-gap tiers are not clearly better than quantile tiers; Phase 4 can test equal-size or capped-size tiers.

## 2026-10-21 — Phase 2 baseline: plain ADP beats pure VOR and the current recommender
**Decision:** Phase 4 must beat plain ADP drafting, not the old recommender (which is the floor, not the bar).
**Why:** 5 backtest seasons x 12 draft slots x 100 opponent seeds (6,000 drafts per strategy per noise level), same opponents
for every strategy. Mean starter points / mean league finish of 12 at opponent noise x1: ADP 1796 / 5.8, pure VOR 1694 / 7.7
(-102 +/- 3), current recommender 1547 / 10.3 (-249 +/- 3) (1511 / 10.9, -284, before the tier threshold moved to 0.10); the
order held at noise x0.5 and x2. VOR beat ADP in 2021 and 2022
but lost by 237 in 2023, so VOR vs ADP is season-dependent. The recommender's half-weight on ADP minus VOR rank rewards
reaching for players the model likes (traced: TE with ADP 257 in round 5). Python does the same: first recommendation on the live data is a TE
(H.Henry, ADP 162). This agrees with Phase 1: the model does not beat ADP, so disagreeing with ADP costs points.
**Caveats:** SEs treat drafts as independent; the opponent noise scale is a guess (hence the x0.5/x1/x2 sweep); lineups use
season totals, not weekly. **See:** `csharp/src/DraftBot.Sim`, `data/processed/sim_baseline.csv`.

## 2026-10-21 — Projection file: JSON, pure model, backtests share the live schema
**Decision:** C# reads `projections_<season>_v1.json` (header + players). `projected_ppr` is the pure model (or the ADP-curve
estimate for market rows). Each backtest season is exported in the same schema plus `actual_ppr`, with the ADP-curve rows
fit leaving that season out.
**Why:** JSON needs no NuGet package and carries file-level metadata (schema version, per-position RMSE); the roadmap
diagram already said JSON. Pure model first so the 50/50 model+curve blend (0.7-1.7% lower RMSE) can be tested in the
simulator as a clean change. Same schema means the simulator runs the code the app ships.
**Rejected:** Parquet via Parquet.Net, CSV, shipping the blend now, a separate backtest schema.
**Schema fixes made on the way:** the doc defined `injury_flag` as `games < 13 and games_delta < -5`, but the code's
`injury_flag` (used by the recommender) is a durability flag (average under 15 games over >= 2 qualifying seasons; 40-50% of
the pool carries it) and the doc's rule was the `availability_flag`. The file now carries the durability flag; C# derives
availability from `games` / `games_delta`. Backtest flags are recomputed point-in-time and match the live pipeline's flags
on all 256 modeled players. Teams with no club on file (pre-draft rookies `TBD`, unsigned `FA`, `-`) export as `FA`.

## 2026-10-21 — Backtest pool: ADP rank <= 300, zero-game players score 0
**Decision:** the backtest pool is the ADP-ranked skill players (~233-245 per season); rookies and unmodeled players are
included as `market_estimate` rows; a drafted player with no stats row (injured all year) scores 0 instead of being dropped.
**Why:** mirrors the live advisor table. Dropping zero-game players removes busts like Michael Thomas (ADP 75, 2021) and Joe
Mixon (ADP 76, 2025) and makes simulated rosters score higher than real ones (0-6 players per season). **Rejected:** the
Phase 1 benchmark's rule of excluding unscoreable players (right for ranking metrics, wrong for a drafter's roster).

## 2026-10-21 — Simulator design: per-opponent bias, noise sweep, season-total lineups
**Decision:** each opponent draws a fixed bias per player ~ N(0, 1 + 0.1 x ADP) once and picks the best ADP + bias among
legal players; every drafter has position caps (2 QB, 2 TE) and must fill open starter slots after round 10. Rosters are
scored by the best lineup from actual season PPR; strategies face identical opponents (seeded by seed and team).
**Why:** a personal bias models teams that like a player more than consensus, without per-pick randomness washing it out. We
have only mean ADP, so the spread cannot be calibrated; the experiment reruns at half and double the noise. Season totals
need only data we have. **Rejected:** per-pick Gaussian noise, fixed SD, weekly lineups (bye weeks and injuries, needs a
weekly export; can be added behind the same scorer).

## 2026-10-21 — Replacement level by greedy FLEX fill, tiers by RMSE-scaled dropoff
**Decision:** dedicated starters = teams x slots; the league's FLEX slots go to the best remaining RB/WR/TE by projection;
replacement is the first non-starter. Tiers are per position: a new tier starts where the projection drops by more than
0.2 x that position's RMSE (live file tier sizes: QB 5/18/16/2, RB 2/1/1/9/76, WR 2/2/1/118, TE 1/4/4/28/7/3). Later changed to 0.10, see
the tier-threshold entry above.
**Why:** adapts to any slot counts. For the default league it gives 12 QB / 30 RB / 42 WR / 12 TE starters, so replacement is
the 31st RB and 43rd WR, one deeper than the old hardcoded RB 30 / WR 42 (which treated the 30th RB as replacement while
QB 13 / TE 13 were first non-starters). The 0.2 was untuned and ended in one very large last tier at RB and WR. **Rejected:** fixed FLEX split, bench-aware replacement, anchored bands, Jenks natural breaks.
**Port notes:** the recommender keeps its Python quirks (FLEX counts as filled once the RB/WR/TE core slots fill; per-bench
count off by one until then); the only change is that no FLEX need appears when the league has no FLEX slot.

## 2026-10-21 — OL information is not worth modeling for model gains
**Decision:** do not build an offensive-line rating (plus-minus or otherwise); no OL features are in the model.
**Why:** continuity of last year's top-5 OL (returning starters, snap continuity, incoming starters) and prior-season
adjusted line yards / sack rate were null at every position (RB −0.002 to −0.009, QB −0.015 to +0.005), and did not
predict next-season team rush EPA, sack rate or pass EPA (t < 1.1, n = 288). An oracle using the line's actual
same-season result (which leaks, so flatters) moved RB top-150 by only +0.006 and QB by +0.017: if knowing the line's
result barely helps, forecasting it cannot.
**Rejected:** market/pedigree rating (contract value, draft pick) — the user's reasoning: OL is scarce, so contracts
measure a team's desperation, not the player. Scraping ESPN's pass/run block win rates — Disney terms prohibit
scraping and compiling datasets, no download exists. **See:** `src/features/advanced.py`, `tests/test_ol_*.py`.

## 2026-10-21 — Process features, wired per position
**Decision:** each position gets only the feature groups that passed ablation (`src/features/registry.py`). RB:
week-1 depth-chart tier + expected fantasy points. WR: depth tier + share of team pass/rush plays on the field. TE:
expected fantasy points + Next Gen Stats receiving. QB: none.
**Why:** RB depth + xfp +0.056 top-150 (0.482 → 0.538, RMSE 62.3 → 59.0); TE xfp + NGS +0.052 (0.360 → 0.411); WR
depth + role gains only +0.008 in the top-150 but +0.041 over all WRs and −4.7% RMSE, with no metric worse.
Team EPA/success rate was null as expected. **Rejected:** PFF grades (paid, license-restricted, not reproducible in a
public repo); PFR advanced stats (only 2018+, halves usable training rows); participation `route` (mostly empty,
approximated by on-field share).

## 2026-10-21 — QB depth-chart tier declined
**Decision:** the QB model does not use the week-1 depth chart.
**Why:** it improves starter-vs-backup AUC (0.818 → 0.857) and RMSE (−10%), but hurts the ordering of QBs who actually
started (0.443 → 0.426), the top-12 hit rate (0.587 → 0.553) and top-150 Spearman (0.310 → 0.261, 10 of 10 seeds worse).
The advisor mostly orders starters, so ordering wins. The user deferred to this recommendation.

## 2026-10-21 — Rookies: ADP-derived fallback, no pick-based model
**Decision:** anyone the model cannot score gets a projection from an isotonic curve of rank-within-position (by ADP)
to expected PPR, fit on 2021–2025, flagged `market_estimate`. Players without a GSIS ID get a synthetic `market:<name>` ID.
**Why:** draft pick alone is a noisy single signal and cannot beat ADP, which already prices pick, landing spot and camp
news; a real rookie model needs college data and is a separate later project (user decision). Leave-one-season-out
RMSE on the top-150: RB ~63, WR ~67, TE ~62 (QB 119 on 6 players); rookie bias was small and not significant.
**Why rank-within-position:** Underdog's top 100 holds ~60 WRs vs ~43 in FantasyPros, so overall-ADP curves mis-price
positions; rank within position agrees across sources. Same RMSE as model rows is used for ceiling/floor.
**Known bias:** the curve is fit on players with ≥4 games, so deep ranks run high. **See:** `src/draft/market_fallback.py`.

## 2026-10-21 — The model is not used to out-rank ADP among draftable players; point projections average model and ADP curve
**Decision:** for the draftable pool, ADP alone ranks as well as any blend, so the model is a source of calibrated
points, uncertainty and flags there. For point projections, averaging the model with the calibrated ADP curve is
better than either alone.
**Why (rerun on the FINAL model, after the process features; the first run predated them and said "adds nothing"):**
- ADP top-150, best model weight: RB 0.0 (+0.000), WR 0.1 (+0.000), TE 0.4 (+0.011, but −0.015 at 0.3), QB 0.4
  (+0.023; at 0.3 CI [−0.09, +0.11], better in 4 of 5 seasons). Nothing beats ADP alone with confidence.
- All modeled players with an ADP (deeper pool): WR +0.009 (CI [+0.001, +0.016], 4/5 seasons), TE +0.033 at weight
  0.6 (the model alone beats ADP there, 0.705 vs 0.686), RB and QB flat. The process features bought the model a
  small edge at depth for WR and TE only.
- RMSE on the top-150, model / ADP curve / average: QB 89.9 / 83.5 / 82.7, RB 76.5 / 72.2 / 71.7, WR 71.6 / 71.0 / 69.8,
  TE 52.0 / 52.8 / 51.2. The average wins at all four (0.7–1.7% better than the best single source).
**Caveat:** the ADP curve was fit leave-one-season-out, so it saw seasons after the one it predicts; the model is
walk-forward. That slightly favors the curve. **Not yet done:** the blend is not implemented in the advisor.

## 2026-10-21 — `implied_total` leaked the target season; now the prior season
**Decision:** `implied_total` is the team's PRIOR-season average total in training and prediction.
**Why:** the old value was the season's own average closing line, which reflects in-season results. Replacing it
dropped QB top-150 from 0.61 to 0.23 at the time (WR −0.03, RB/TE ~0); a model without the feature scored the same as
prior-season, so the whole benefit was leakage. The earlier "QB beats ADP" result was an artifact.
**Rejected:** keeping it (can't be known at draft time), blending with partial-2026 lines (user's first choice; made
QB projections swing ~100 PPR on one input), dropping the feature (same scores, but prior-season total is honest context).
**Guard:** `src/features/manifest.py` + `tests/test_data_integrity.py::test_prior_season_features_are_lagged_not_leaked`.

## 2026-10-21 — Data-integrity guardrails: fail on errors, warn on soft problems
**Decision:** `src/data/validate.py` raises on hard problems (null/duplicate keys, unknown team codes, a season losing
rows in a merge, out-of-range values, prediction rows that differ from training rows, duplicate advisor players) and
warns on soft ones (feature drift, column order). Plain assertions + pytest, no pandera.
**Why:** every serious bug this phase was silent (legacy team codes dropped ~80 rows, junk "Team" rows corrupted target
share for 12 team-seasons, stale 2025 age/team in 2026 prediction rows, duplicated advisor players). "Always warn" is how
silent bugs survive; "always fail" would block runs on benign drift. Also added: run manifest, freshness checks, tracked
`models/*_params`, pre-commit hook, CI workflow. **See:** README "Data Integrity Guardrails".

## 2026-10-21 — Benchmark design
**Decision:** per-position scores only, top-150 chosen by ADP among players the model projected, mean of 5 model seeds
with the spread, always shown next to a "last year's PPR" baseline. No pooled "ALL" row.
**Why:** ADP prices positional scarcity and raw PPR does not, so a pooled row flatters or punishes arbitrarily; single-seed
scores moved by ±0.03 (TE); players the model cannot project (rookies) are excluded from both sides so the comparison is
like-for-like. Unranked players enter the overall scope as the union of the top 50 by actual and by model, tied last.

## 2026-10-21 — Re-tune only when both metrics improve; training window stays expanding from 2015
**Decision:** a re-tuned parameter set replaces the old one only if top-150 Spearman *and* RMSE both improve over 10
seeds. Training uses all seasons from 2015 (expanding window).
**Why:** with 500–1,600 rows per position the tuner mostly fits noise; QB, RB and WR re-tunes never beat the old params
(only TE and one QB re-tune were adopted). Dropping older seasons hurt QB (0.608 → 0.481 starting 2018), WR and TE;
sliding windows lost at every position, so data volume beats recency here.

## 2026-10-20 — QB uses attempt share; the old QB gap was starter identification
**Decision:** QB model gets `qb_att_share_prev` (player's share of the roster QBs' prior attempts).
**Why:** ADP's edge at QB was knowing who starts (starter-vs-backup AUC 0.87 vs 0.79 for the model). The share lifted
QB top-150 from 0.230 to 0.310; expected-starter and proven-competitor flags were redundant, rookie-competitor fired on
25 rows. A first-round rookie overrides as QB1 (72% of 39 such rookies were their team's top-attempt QB).
**Same logic at RB did not work:** carry-share features were null once vacated-volume features were in, because RBs share work.

## 2026-10-20 — Historical ADP: FantasyPros consensus via Wayback, day before the opener
**Decision:** scrape FantasyPros PPR consensus ADP from Wayback Machine snapshots closest to (not after) the day before
each opener, 2021–2025, one CSV per season (user decision).
**Why:** a snapshot after the opener can reflect Week 1. Snapshots used: Sep 7 2021, Aug 31 2022, Sep 6 2023, Sep 2 2024,
Aug 26 2025 (2022 and 2025 are 6–8 days early; user accepted). **Rejected:** Fantasy Football Calculator's public API
(user: its ADP is not good), expert consensus rankings (user chose ADP), nflverse ECR.

## 2026-10-20 — Prediction rows use prediction-season inputs
**Decision:** 2026 prediction rows take age, experience, team and team total from the 2026 roster, not the 2025 row.
**Why:** otherwise every projection saw players a year younger and on last year's team. Training rows describe the season
being predicted, so prediction rows must too. Players missing from the roster get age/experience advanced by one.

## Deferred, not decided
- **Week 1 line as a preseason team-strength signal** (user may try later): the Week 1 spread/total, already in the
  schedule data, is the closest legitimate preseason market number (the old full-season average leaked). Test it for
  QB first. Expected value is low for RB/WR/TE: even the leaky in-season total was worth only +0.007 to +0.027
  there (QB: 0.61 leaky vs 0.23 prior-season). Preseason win totals would need a new data source (not in nflverse)
  and overlap with what ADP already prices. Rank it below coaching tendencies.
- **Coaching tendencies** (head-coach pass-over-expected, pace, 4th-down aggression, using the coach's prior team's
  tendency when the HC changes): the user wants to scope it carefully before any work. Only head coaches are public.
