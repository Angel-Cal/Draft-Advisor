# DraftBot — Project Status

**Last updated:** 2026-10-27
**Active branch:** `phase-2-csharp` (Phase 2 plus Phase 4; pushed to `origin` up to 2026-10-22, with the later work uncommitted; not merged to `main`; `main` has Phases 0-1)
**Phase:** Phases 0, 1 and 2 complete; Phase 4 (recommender v2) is essentially done: single score, reach control, roster need, bench value and the cost-of-waiting bonus are in, the league-finish metric exists, and the other ideas were tested and rejected (see "Hand-off" at the bottom). Next: fix the live training recipe, then reasoning strings and Phase 5. Phase 3 (model v2) waits for the 2026 season to end.
**Why we chose things:** see `LOG.md` (decision log). Add an entry when a task produces a decision that rejected an alternative or changed results.

---

## What It Is

ML-powered fantasy football draft assistant. Predicts next-season PPR fantasy points per player with position-specific LightGBM models trained on 2015–2025 NFL data, benchmarks them against ADP on held-out seasons, and feeds the projections to a draft advisor.

League settings: 12-team snake, PPR, 1 QB / 2 RB / 3 WR / 1 TE / 1 FLEX / 8 bench.

---

## Where Things Stand

**Honest result: the model does not beat ADP, but it is close.** After finding and fixing a target-season leak in `implied_total` (see Data Integrity), the benchmark is:

Spearman vs actual season PPR, walk-forward test seasons 2021–2025, mean of 5 model seeds. "Top-150" = the 150 best by ADP among players the model projected (~22 QB / 47 RB / 60 WR / 21 TE per season). "All" = every projected player.

| Position | Top-150 model | Top-150 ADP | Last-year PPR | All players model | All players ADP |
|----------|---------------|-------------|---------------|-------------------|-----------------|
| QB       | 0.305         | 0.401       | 0.228         | 0.676             | 0.765           |
| RB       | 0.532         | 0.589       | 0.367         | 0.746             | 0.750           |
| WR       | 0.511         | 0.569       | 0.464         | 0.746             | 0.750           |
| TE       | 0.406         | 0.418       | 0.304         | 0.699             | 0.688           |

- The model beats the naive "last year's PPR" baseline at every position.
- Seed spread on top-150 scores is ~0.01–0.03 (TE largest); treat gaps under ~0.03 as noise. Each test season has only ~20–60 players per position.
- Blend test (rerun on the final model; see LOG.md): among draftable players (ADP top-150), ADP alone ranks as well as any model/ADP blend (QB +0.023 at 40% model weight, CI includes 0; RB/WR +0.000). Over the deeper pool the model adds a little for WR (+0.009) and TE (+0.033). A 50/50 average of the model and the ADP-derived curve has the lowest RMSE at all four positions (0.7–1.7% better than the best single source). **The blend is not implemented in the advisor yet** — a candidate Phase 2/3 item.
- Walk-forward RMSE (2021–2025, 5-seed mean): QB 84.28, RB 58.86, WR 53.48, TE 38.69. Mean per-season R²: QB 0.47, RB 0.59, WR 0.61, TE 0.60.

**Features each position's model uses** (single source of truth: `src/features/registry.py`):
- All: lagged per-game/total stats, EPA, surge, year-over-year deltas, age/draft/size, `implied_total` (team's PRIOR-season average total).
- QB: + `qb_att_share_prev` (share of the roster QBs' prior attempts).
- RB: + vacated/competing volume (`competing_rb_carries` drives it), week-1 depth-chart tier, expected fantasy points (3 cols).
- WR: + week-1 depth-chart tier, on-field share of team pass/rush plays.
- TE: + expected fantasy points, Next Gen Stats receiving metrics.

**Training data:** 4,137 rows (2015–2025). Expanding window from 2015 was best or equal for every position (recency windows lost).

---

## Phase 2 result: the simulator's baselines

Backtest seasons 2021-2025, 12 teams, 12 draft slots x 100 opponent seeds per season (6,000 drafts per strategy per noise
level), opponents draft by ADP + a personal bias per player, rosters scored by the best lineup EACH WEEK from actual weekly PPR (weeks 1-18,
chosen with hindsight; byes and injuries cost points, so depth is worth something). Until 2026-10-22 rosters were scored on season totals;
`--season-totals true` reproduces that (the season-total numbers are in `LOG.md`).
Same opponents face every strategy, so differences are paired. Opponent noise is calibrated to real mock drafts (x1 = bias SD 1 + 0.12 x ADP,
see `LOG.md`); x0.5 and x2 are run as a check.

| Strategy (noise x1) | Starter points | Mean finish (of 12) | Top 3 | 1st | vs ADP (paired, +/- 1 SE) |
|---|---|---|---|---|---|
| Plain ADP | 2158 | 5.7 | 32% | 12% | |
| Pure VOR | 2049 | 7.5 | 9% | 1% | -109 +/- 3 |
| Current recommender (ported) | 1840 | 10.5 | 1% | 0% | -318 +/- 3 |
| Recommender + reach control (`windowed`) | 2129 | 6.0 | 28% | 8% | -28 +/- 3 |
| Single-score recommender (`value`, lambda 1000) | 2178 | 5.4 | 37% | 14% | +20 +/- 2 |
| Single-score + roster need and bench value (`need`) | 2199 | 5.1 | 41% | 16% | +42 +/- 2 |
| `need` + cost of waiting, weight 4 (`need+wait`, the default advisor) | 2211 | 4.8 | 44% | 17% | +53 +/- 2 |

(100 seeds, 2021-2025. Re-run 2026-10-25 after the opponents' random draws were made independent of pool order; the earlier run, +34 / +48 over ADP 2164, used the old
draw order. The ranking and the sign of every edge are unchanged; `need` is ahead of ADP in all five seasons, `value` is +28 behind it.)

**League finish (added 2026-10-25).** Each draft's weekly lineup scores are replayed as a head-to-head season: 13 regular-season weeks (random round-robin),
top 6 by wins (tiebreak points for) make the playoffs, seeds 1-2 get byes, three single-elimination rounds in weeks 14-16, odds averaged over 200 random
schedules (the same schedules for every strategy). Same 100-seed run, noise x1 (differences are paired, percentage points, +/- 1 SE over drafts):

| Strategy | Win % | Playoffs | Title | Playoffs vs ADP | Title vs ADP |
|---|---|---|---|---|---|
| Plain ADP | 53.1% | 57.8% | 11.4% | | |
| Pure VOR | 44.5% | 37.2% | 7.7% | -20.6 +/- 0.6 | -3.7 +/- 0.3 |
| Current recommender (ported) | 29.3% | 8.0% | 0.6% | -49.8 +/- 0.5 | -10.9 +/- 0.3 |
| `windowed` | 52.8% | 57.9% | 11.4% | +0.1 +/- 0.6 | -0.0 +/- 0.4 |
| `value` | 54.4% | 60.7% | 13.0% | +2.9 +/- 0.5 | +1.5 +/- 0.3 |
| `need` | 55.6% | 63.5% | 14.4% | +5.7 +/- 0.5 | +3.0 +/- 0.3 |
| `need+wait` (weight 4) | 56.1% | 65.2% | 16.3% | +7.4 +/- 0.5 | +4.8 +/- 0.3 |

`need+wait` vs `need` at noise x0.5 / x1 / x2: points +2 / +11 / +15; title odds +0.5 / +1.9 / +2.8 pp. The weight (4, best of 0.1-8) was picked on these same
100 seeds, so the x1 line is in-sample; the leave-one-season-out gain over `need` is +1.2 +/- 0.6 pp title and +9 +/- 8 points, and the checks at other noise levels
and with the roster rules lifted are in `LOG.md`.

Same order as the points metric. `need` raises title odds by about 26% relative (11.4% -> 14.4%); at x0.5 noise +2.9 pp, at x2 it is level with ADP (+0.3 +/- 0.5),
matching the points break-even. `windowed` ties ADP here although it is 28 points behind: the league metric saturates, so a big points loss in one season
counts no more than a small one. An average team's title odds are 8.3% by construction; ADP is above that because the opponents are noisy-ADP bots.
Caveats: no waiver wire (an injured starter just costs points), hindsight-optimal weekly lineups, SEs treat drafts as independent. Weeks 17-18 count in
the points metric but not in the season (weeks 1-16). Command: `backtest` prints this table for every strategy.

The order is the same at x0.5 and x2. **The bar for Phase 4 is plain ADP, not the old recommender.** VOR beats ADP in 2021
and 2022 but loses by 237 points in 2023, so it is season-dependent. The recommender reaches for model-vs-ADP disagreements
(its `value_gap` term), and the model does not beat ADP. Weekly scoring left every conclusion unchanged (same order, edges a little larger).
Caveats: SEs assume independent drafts (drafts in one seed share opponents, so the true SE is somewhat larger, about 3 instead of 2 for `value`); weekly lineups are hindsight-optimal; `injury_flag` marks 40-50% of the pool, which makes the recommender's risk penalty blunt.
Decisions behind all of this are in `LOG.md`.

**Reach control** (`ReachSettings`, default lambda 0.3 / cap 4 sigma, provisional): the baseline recommended ADP 70-112 players
at pick 6; the windowed variant stays near the pick (Jefferson, St. Brown, Chase). It recovers about 210 of the 249 points lost
to ADP, beats ADP in 2021, 2023 and 2024 and loses in 2022 and 2025 (-243). Still below plain ADP overall. Mock draft: `--window true`.
**Single-score recommender (`value`, Phase 4 step 1):** one score across positions, VOR minus a reach cost in points, no roster need yet.
At the calibrated opponent noise it is +27 over plain ADP (+29 at x0.5, -19 at x2), winning 4 of 5 seasons (2025 is -10) and ~+320 over
the old recommender. The edge fades as opponents get noisier and breaks even at about 1.65x the calibrated noise; the lambda plateau is
wide (400 and up all gain 16-23). The reach cost at the best setting is very high (a player one pick past his ADP loses ~100 points).
**Roster need and bench value (`need`, Phase 4 step 2, now the recommended recommender):** a player's value is the points he adds to the team's
best lineup (open slots = replacement-level ghosts) plus position-specific BENCH value. The k-th backup at a position is worth P(at least k of
its S starter slots out in the same week) (q = 0.23, measured: draftable players miss ~3.1 of 17 games at every position, plus one bye; S = QB 1,
TE 1, RB 2 + FLEX, WR 3 + FLEX) times his option value above the waiver level, E[max(0, X - waiver)] with X normal around his projection (spread =
the position RMSE) and waiver = the best undrafted player at the position. A player who can never start and, at his position, can never be needed
as cover (a 3rd QB or TE) is a dead pick and ranks below everything useful. This builds sane rosters without any caps (about 2 QBs and 2 TEs;
ADP drafts 3.8 QBs) and beats no-bench-value in every configuration tried (rules on/off, weekly or season-total scoring, noise x0.5 to x3),
and wins all five seasons with the rules lifted. Flat bench fractions do not help; the position-specific weights and the dead-pick exclusion do
the work (option value on top of the structural weights adds only ~3 points). Edge over ADP stays positive until opponent noise reaches ~2.5x
the calibrated level. Scoring is weekly lineups since 2026-10-22. See `LOG.md`.

The opponent noise itself is now calibrated against real mock drafts (FFC pick spread); the remaining uncertainty is how well hobbyist mock
drafts represent your league. See `LOG.md`.

**Why 2025 is the bad year (investigated):** not the model (it out-ranked ADP that year). 2025 was an RB-premium season (first 12
RBs by ADP averaged 293 vs 215-258 elsewhere) and the recommender's position rule always favors WR (most unfilled slots), so it
drafts 2.7 RBs per team vs ADP's 5.4. The position rule alone reproduces the season-to-season swings (+73/-152/+9/+85/-224 vs
ADP); letting the recommender choose only the player at ADP's position scores 1792 vs ADP 1795 with no bad season. The position
step is also what keeps drafting QBs and TEs in an unconstrained mock draft (5 TEs and 5 QBs in one run; the simulator's caps hide it).
**Next:** replace the position step (roadmap Phase 4: one score across all players); the player ranking can stay. See `LOG.md`.

**Tier threshold** is now 0.10 x position RMSE (was 0.20; the recommender gained ~36 points). `tune-tiers` found that gap-based
tiers show no clear cliff signal beyond equal-size tiers except at TE, so this is a usable-count compromise, not an optimum.

**Regret per round** (noise x1, mean per draft; `sim_regret.csv` has every season and round): hindsight regret is 120-230
points per pick in every round (the best available player in hindsight is always a breakout), so it mostly measures luck:
total 2487 ADP / 2411 VOR / 2751 recommender. Foresight regret (projected VOR) is 0 for VOR, 608 for ADP and 259 for the
recommender, which gives up 52 VOR in round 1 and ~0 from round 14, i.e. its damage is early reaching.

## Mock draft (studying what the recommender does)

`draft` runs an interactive draft on a past season (2021-2025): you pick for one slot, seeded bots pick for the other 11 (same
bots as the experiment, so a seed replays the same opponents). Each turn shows the recommender's position scarcity numbers, its
top 5 with every score component, and what pure ADP and pure VOR would take. Enter takes its #1, `1-5` an alternative, `a` / `v`
the ADP / VOR pick, any name fragment a specific player, `q` quits. Actual results stay hidden until the end (`--reveal true`
shows them after each pick); the end shows your picks with actual points and regret, your lineup score and finish, and what
each strategy would have scored from the same slot against the same opponents. Your own picks are not restricted by the roster
rules; suggestions the simulator would block are marked.

## Pipeline: how to rebuild everything

Run in this order (each step's outputs feed the next; the freshness checks fail if you skip one):

```bash
python src/data/scraper.py                       # raw nflverse files (+ roster_2026, + advanced sources)
python src/data/pipeline.py                      # clean, features, validation  -> training_data / prediction_data
python src/models/train.py                       # OPTIONAL: Optuna re-tune (writes models/*_params)
python src/evaluation/oos_predictions.py         # walk-forward predictions, 5 seeds -> season_<year>.parquet
python src/evaluation/benchmark.py               # model vs ADP vs last-year -> benchmark_v1.csv
python src/models/predict.py                     # 2026 projections -> *_predictions.parquet (close the CSVs in Excel first)
python src/draft/vor.py                          # advisor table -> predictions_table.parquet (adds ADP fallback rows)
python src/data/export_projections.py            # projections_<season>_v1.json: live 2026 + backtests 2021-2025 (C# reads these)
python src/data/adp_scraper.py                   # only to refresh historical ADP (Wayback Machine, cached in data/raw/adp_html)
python src/data/ffc_scraper.py                   # real pick-spread data from FFC mock drafts (cached in data/raw/ffc); used to calibrate the simulator
```

C# (needs the exported JSON files; .NET 9 SDK):

```bash
cd csharp
dotnet test                                                          # 162 tests
dotnet run -c Release --project src/DraftBot.Sim -- backtest --seeds 100   # baselines + regret -> data/processed/sim_baseline.csv, sim_regret.csv
dotnet run --project src/DraftBot.Sim -- draft --season 2024 --slot 6 [--seed 0] [--reveal true] [--window true] [--recommender value|need|bench|option]   # interactive mock draft
dotnet run -c Release --project src/DraftBot.Sim -- tune-reach --seeds 30   # reach penalty / cap sweep, leave-one-season-out
dotnet run -c Release --project src/DraftBot.Sim -- tune-value --seeds 60 [--noise 2]   # lambda sweep for the single-score recommender
dotnet run -c Release --project src/DraftBot.Sim -- tune-bench --seeds 40 [--unrestricted true] [--season-totals true]   # bench value: flat vs structural
dotnet run -c Release --project src/DraftBot.Sim -- tune-need --seeds 40 [--unrestricted true] [--noise 1]   # roster-need sweep (bench fraction x lambda)
dotnet run -c Release --project src/DraftBot.Sim -- tune-wait|tune-spread|tune-reach-wait|tune-starter --seeds 60 [--metric points|wins|playoffs|title]   # waiting bonus: weight / survival spread / reach cost x weight / starter option
dotnet run -c Release --project src/DraftBot.Sim -- tune-where|tune-scarce|tune-standardized --seeds 100 [--metric ...]   # where the waiting bonus earns its gain (rounds/positions), RB+TE only, and the spread-normalized version (none better than the raw weight of 4)
dotnet run -c Release --project src/DraftBot.Sim -- diagnose-scales --seeds 30   # spread of value vs shortfall among the best candidates, by round (value is ~2.9x the shortfall: why a raw 4 is about equal importance)
dotnet run -c Release --project src/DraftBot.Sim -- tune-horizon --seeds 60 [--metric ...]   # waiting bonus summed over my next 1-3 picks (rejected: behaves like a rescaled weight)
dotnet run -c Release --project src/DraftBot.Sim -- tune-lookahead --seeds 60 [--metric ...]   # two-step lookahead (rejected; slow: the title sweep took hours, use few seeds)
dotnet run -c Release --project src/DraftBot.Sim -- calibrate-survival --seeds 30 [--scales 0.4,0.55,0.7,0.85,1,1.25]   # reliability of the survival model behind the waiting bonus
dotnet run -c Release --project src/DraftBot.Sim -- calibrate-noise   # simulated vs real (FFC) pick spread by ADP bucket
dotnet run -c Release --project src/DraftBot.Sim -- fit-noise         # grid-fit the opponent noise formula to the real spread
dotnet run -c Release --project src/DraftBot.Sim -- diagnose --season 2025 --a adp --b windowed   # which players/positions explain a gap
dotnet run -c Release --project src/DraftBot.Sim -- decompose --seeds 50   # recommender split into position rule vs player rule
dotnet run --project src/DraftBot.Sim -- tune-tiers                  # tier threshold sweep, leave-one-season-out
dotnet run --project src/DraftBot.Sim -- describe [--tier-gap 0.2]  # starters, replacement and tier sizes of the live file
```

Tests: `pytest -q` (137 tests; the data-integrity and export-file tests skip when `data/` is absent). A git pre-commit hook (`.githooks/pre-commit`, enabled with `git config core.hooksPath .githooks`) runs them before every commit.

`data/raw`, `data/processed`, `data/external` are gitignored. `models/*_params` (tuned hyperparameters) **are tracked**.

---

## Data Integrity (read before changing the pipeline)

Silent data bugs were the main source of wrong results. Guardrails now in place:

- `src/data/validate.py` runs inside `pipeline.py`, `predict.py` and `vor.py`: errors stop the run (null/duplicate keys, unknown team codes, a season losing rows in a merge, out-of-range values, prediction rows that differ from training rows or carry last season's age, duplicate players in the advisor table); soft problems warn.
- `src/features/manifest.py` must classify every training column as `prior_season` or `preseason_known`; an undeclared column fails `tests/test_data_integrity.py`.
- `tests/test_data_integrity.py` recomputes lagged features from raw files and fails if a column matches the target season; also checks train/serve parity, per-position feature isolation, ADP coverage, OOS files, pinned packages, and that the advisor's `RMSE` constants in `vor.py` match the current walk-forward error (within 5%).
- `data/processed/run_manifest.json` logs commit, timestamp, row counts and params checksums per run; stale outputs raise or warn.
- Benchmark standard: per-position only (no pooled "ALL" row — ADP prices positional scarcity), 5-seed mean with spread, always next to the last-year-PPR baseline.

**Bugs found and fixed this phase** (so they are not reintroduced):
1. `implied_total` used the target season's own average closing line (leak). Now the team's prior-season total, in training and prediction. QB top-150 fell 0.61 -> ~0.21 before later fixes; the earlier "QB beats ADP" was an artifact.
2. Legacy team codes (OAK, SD, ARZ...) silently dropped ~80 rows from 2015 (and so ~90 from 2016); `schedule` loading started at 2015. Fixed via `TEAM_MAP` and loading 2014 schedules.
3. Junk "Team" rows (null `player_id`, `games` 256–272) corrupted target share for 12 team-seasons. Dropped at load.
4. Prediction rows carried 2025 age/experience/team/total for a 2026 prediction. Now advanced to the prediction season.
5. LightGBM predicts positionally: prediction columns are aligned to training columns by name in `predict.py`.
6. `vor.py` read its own previous output, matched ADP players on name only (Harrison Jr. and Pittman appeared 8 times each, shifting the WR replacement baseline), and overwrote `predict.py`'s outputs. Fixed; debugging copies are now `*_with_adp`.

---

## Rookies and unmodeled players

Decision: **no rookie model** in this project (a pick/age/size model cannot beat ADP; a real one needs college data and is a separate later side project). Anyone the model cannot score gets an ADP-derived projection (`src/draft/market_fallback.py`): an isotonic curve per position from rank-within-position (by ADP) to expected PPR, fit on 2021–2025. `vor.py` adds those rows to `predictions_table` flagged `market_estimate=True`; players with no GSIS ID get synthetic `market:<name>` IDs. Leave-one-season-out RMSE on the top-150: RB ~63, WR ~67, TE ~62 (QB/TE samples are tiny). Caveats: deep ranks are biased upward (curve fit on players with >=4 games); curve is fit on FantasyPros ADP but applied to Underdog ADP (rank-within-position input mitigates the pricing difference).

---

## What Was Tested and Did NOT Help (don't re-run without a new idea)

All tested with the standing protocol: 10-seed ablation + random-noise control, drop anything within noise.

- Re-tuning params (100–400 Optuna trials): the TE and (first) QB re-tunes were adopted; RB, WR and the second QB re-tune (after `qb_att_share_prev`) never beat the existing params. More tuning is mostly fitting noise (500–1,600 rows per position).
- WR: vacated/competing targets, QB change/quality (first-round rookie override), draft-capital x youth, two-year-history idea (declined on reasoning).
- Team pass rate/pace/points per game, team EPA/success rate, depth ranks within team, team-change flag, `seasons_since_last`.
- QB: per-game PPR features, per-game target, smaller feature set, simpler/ridge models, depth-chart tier (improves starter-vs-backup AUC and RMSE but hurts ranking among actual starters; **declined**).
- RB depth-chart competition (carry share, expected lead, proven/rookie competitor): null once vacated features are in.
- Offensive line: continuity (returning starters, snap continuity, incoming starters), prior-season adjusted line yards / sack rate, and interactions — all null, and even the line's actual same-season ALY/ASR as an oracle moved RB top-150 by only +0.006 (QB +0.017). Don't build an OL rating for model gains.

## Open / Deferred

- **Coaching tendencies** (head-coach pass-over-expected, pace, 4th-down aggression; coach's prior-team tendency when the HC changes): deliberately deferred by the user — "requires more nuance before touching". Only head coaches are in public data (schedules).
- **Week 1 line as a preseason team-strength feature** (user may try later): test the Week 1 spread/total as the legitimate version of the leaked implied total, QB first (see LOG.md "Deferred"). Low expected value for RB/WR/TE.
- **PFR advanced stats** skipped (only 2018+, would halve usable training rows). Participation `route` field is mostly empty, so route participation is approximated by on-field share.
- **ESPN pass/run block win rates** (best public OL measure) are not collected: ESPN/Disney terms of use prohibit scraping and compiling datasets, and there is no download/API. Investigation closed.
- **Efficiency features, noted not built (2026-10-21):** the model sees efficiency only as season totals/levels (EPA, pacr/racr, YAC, cpoe),
  never per-opportunity rates (yards per carry/target, catch rate, TD rate, EPA per touch), their year-over-year change, or
  volume-change x efficiency interactions. A residual check found no interaction signal (all |t| < 1.1), one weak lead: draftable RBs
  whose carries/game rose are over-projected ~10-15 pts (t = -2.4, one of ~24 tests), so the RB model may over-weight volume deltas.
  If pursued: standing protocol (10-seed ablation + noise control). Also: `passing_cpoe_delta` (a QB stat) is a near-constant dead
  column in the RB/WR/TE models.
- **Fixed 2026-10-21 (expected-points features):** `build_xfp_features` summed playoff weeks (19-22; 18-21 before 2021) while the
  other features were regular-season only; it now keeps regular-season weeks (<= 17 through 2020, <= 18 after). Rebuilt everything
  downstream: no measurable change (RB top-150 old 0.526 vs new 0.524, TE 0.404 vs 0.403, seed sd ~0.006-0.02; xfp still adds RB
  +0.012, 9/10 seeds, and TE +0.010, 8/10 seeds, with a null noise control). Benchmark table updated (RB 0.539 -> 0.532, TE 0.407 -> 0.406).
  Also fixed: `passing_cpoe_delta` (QB-only, 98-99.6% zeros elsewhere) is now dropped from the RB/WR/TE models.
- **Case study for the efficiency idea: Wan'Dale Robinson (2026 WR, now TEN).** FPOE does NOT flag him: 2025 +0.9 (rank 57 of 133 WRs)
  because his chances were plentiful (expected 217 PPR, 13th) and he converted them as expected. His regression risk is in the volume:
  Nabers played only weeks 1-4; Robinson saw 9.4 targets / 14.3 expected PPR per game without him vs 6.8 / 11.5 with him. The model
  projects 219 (= his 2025 total) vs an ADP-curve 147 (ADP 102, WR47): his edge over the market is the largest of all 123 WRs.
  FPOE measures conversion efficiency, not volume sustainability; a volume-sustainability signal (expected points vs his own prior
  seasons, vs teammates available, team change) is what the idea needs. WR vacated/competing targets were tested null earlier.
- **Half-PPR / standard targets** not built (Phase 3 item).
- Roadmap Phase 3 "team-context features" were largely done and tested in Phase 1 (see lists above); only features that survived are in the model. Phase 3 still needs: 2026 data retrain after the season ends, grading 2026 projections, half/standard targets.
- Model-vs-ADP gaps remain QB −0.10, RB −0.05, WR −0.06, TE −0.01 (top-150). Remaining gap is likely information the data lacks (camp news, injuries, depth-chart changes). Untested ideas are in the memory file `project_feature_ideas.md`.

---

## Hand-off (read this first in a new session)

**Where the project is (2026-10-27).** Python research side and the C# product core both work and are tested (138 pytest, 162 xUnit; code map current). The model
still does not beat ADP at ranking players (Phase 1). The recommender, however, beats plain ADP in the simulator, both on starter points and in a head-to-head league season (13 weeks, 6-team playoff, odds averaged over
200 random schedules): `need` (lineup gain + position-specific bench value, minus an ADP-reach cost) is +42 +/- 2 starter points (title odds 14.4% vs ADP's 11.4%); the **default advisor `need+wait`** (adds the cost-of-waiting bonus,
raw weight 4, `draft --recommender need`) is +53 +/- 2 points, 65.2% playoff and 16.3% title odds (tables above, reasoning in `LOG.md`). The old Python recommender is the worst strategy (about -318 vs ADP).

**NEXT TASK (the user chose this on 2026-10-27, to be done in a new session): make the live projections use the validated training recipe ("option 2").**
1. In `src/models/train.py` add a refit routine. For one position and seed: fit on all seasons except the newest with `lgb.early_stopping(50)` evaluated on the newest season, read `best_iteration_`; then refit on all seasons through the newest with
   `n_estimators = best_iteration_` (the user has not decided whether to scale this by the data-size ratio, about 1.1; ask, and log the choice). Repeat for seeds 0-4 (the validated files average `N_SEEDS = 5` seeds) and average the predictions. Keep `n_estimators: 1000` in
   `models/*_params` as the cap.
2. Use it in `src/models/predict.py` in place of `train_final_model` for QB, RB, WR and TE.
3. Validate before regenerating anything: reproduce the procedure on the walk-forward folds (for test season s: early-stop on s-1 using seasons before s-1, refit on seasons before s, 5 seeds) and compare with the validated `season_<year>.parquet` and with
   `data/processed/live_style_oos.parquet` (RMSE and top-150 Spearman, 2021-2025). Targets: close to validated (RMSE QB 84.5, RB 61.7, WR 55.0, TE 40.1; top-150 rho QB 0.310, RB 0.537, WR 0.512, TE 0.383) and clearly better than live-style (RMSE 87.1 / 63.5 / 56.2 / 42.5; rho 0.251 / 0.496 / 0.489 / 0.395).
4. Optional but recommended: swap the new walk-forward predictions into the comparison in `src/evaluation/live_style_oos.py` (it has the JSON writer; run `backtest --data <dir> --seasons 2021-2025 --seeds 100`) to show the simulator gap closes.
   Reference: validated `need+wait` +52.9 points / 16.3% title odds at noise x1; live-style +40.7 / 15.7%.
5. Regenerate the live file in pipeline order (see "Pipeline: how to rebuild everything" above): `predict.py` -> `vor.py` (builds `predictions_table.parquet`) -> `export_projections.py`; add a unit test for the refit routine; run pytest and `dotnet test`;
   update README / this file / `LOG.md`; regenerate the code map (`venv/Scripts/python tools/gen_codemap.py`). Then update the memory note `project_live_model_tree_count` and the index line (mark fixed).

**Code map.**
- Python: `src/data/export_projections.py` writes `data/processed/projections_<season>_v1.json` (live 2026 + backtests 2021-2025 with `actual_ppr`
  and `weekly_ppr`); `src/data/ffc_scraper.py` pulls real pick-spread data used to calibrate the simulator. Contract: `.claude/projection_schema_v1.md`.
- C# (`csharp/`, net9.0): `DraftBot.Core` = projection loader, league settings, replacement/VOR/tiers, rosters, snake draft state, the ported old
  recommender (`BaselineRecommender`), `ValueRecommender` + `NeedSettings` (the new one), `LineupValue` (lineup gain, replacement, waiver level);
  `DraftBot.Sim` = opponent bots, roster rules, weekly lineup scorer, strategies, experiments and the CLI; `DraftBot.Tests`.
- CLI (`dotnet run -c Release --project csharp/src/DraftBot.Sim -- <command>`): `backtest`, `draft` (interactive mock draft; `--recommender
  need|value|position`), `diagnose`, `decompose`, `describe`, `calibrate-noise`, `fit-noise`, `tune-tiers`, `tune-reach`, `tune-value`, `tune-need`,
  `tune-bench`, plus the 2026-10-25/27 additions: `tune-wait`, `tune-spread`, `tune-reach-wait`, `tune-horizon`, `tune-where`, `tune-scarce`, `tune-standardized`, `tune-starter`, `tune-lookahead` (slow),
  `calibrate-survival`, `diagnose-scales`. The `draft` advisor options are `need` (= need + waiting bonus, the default), `need-only`, `value`, `position`, `bench`, `option`. The `tune-*` sweeps take `--metric points|wins|playoffs|title`
  and report a paired difference against the headline arm and a leave-one-season-out check. Options worth knowing: `--seeds N`, `--noise X`, `--unrestricted true` (lifts the sim's roster rules for the drafter only),
  `--season-totals true` (old scoring).

**Settled decisions (details and numbers in `LOG.md`).** Tier threshold 0.10 x position RMSE; ADP-reach cost lambda 1000 with a 4-sigma cap; opponent
bias SD 1 + 0.12 x ADP (calibrated to FFC mock drafts); weekly hindsight-optimal lineup scoring; bench value = structural k-th-backup weights (q = 0.23)
x option value over the waiver level, with dead picks (3rd QB/TE) ranked last; the position-first step was dropped because it caused the 2025 loss
(it favors WR by unfilled slots). Settled 2026-10-25/27: opponents' random draws are taken in player-id order, not pool order (so comparisons between projection files are valid); the cost-of-waiting bonus (survival to my next pick from the ADP model, same-position
alternatives, raw weight 4, horizon 1) is the default and its weight is a mixing weight (about 1.4 in standardized units, earned at RB and TE in rounds 1-4); the league-finish metric is the second judge next to starter points.

**After the next task (candidates).** Plain-language reasoning strings for beginners (the user saved them for last; probably the most valuable for the "friends and beginners" goal; risk and "backup to your RB1" can appear as labels, not score terms), then
Phase 5 (WPF + BlazorWebView app, Sleeper sync) and the Phase 3 retrain after the 2026 season (half-PPR/standard targets too). Recommender work is at diminishing returns. Tested and rejected, with numbers in `LOG.md` (do not redo): two-step lookahead,
multi-pick horizon, variance-aware starter value, spread-normalized bonus, RB+TE-only bonus (ties the global one), handcuff logic (the absorber of a lead back's work is not identifiable preseason), prior-season weekly volatility as a risk score or a model feature,
the 50/50 model + ADP-curve blend as the recommender's input (-12 points). Untested: a lighter blend weight (for example 25% ADP curve), a survival model that knows opponents' position caps, a first-principles derivation of the bonus weight. Position safety and
run detection use the same survival signal and cannot be validated without real pick-by-pick draft data (the FFC data is aggregate per player).

**Open questions / unvalidated.** How representative FFC hobbyist mock drafts are of the user's league; the option-value bench term assumes normal
projection errors and a crude waiver level; weekly lineups are hindsight-optimal; the live ADP is Underdog but backtests use FantasyPros; the
simulator's QB/TE caps for opponents are an assumption; hindsight regret is mostly luck (foresight regret is the informative one).

**Known issue, OPEN: the live projections are not from the validated model (found by a bug sweep, 2026-10-25).** `src/models/predict.py` (`train_final_model`) trains the
live 2026 models with the 1000-tree cap from `models/*_params` and no early stopping, from a single seed (`random_state` 42). Everything we validated (benchmark, `season_<year>.parquet`,
every C# backtest) uses `oos_predictions.py`: early-stopped on the prior season (best iteration about 200-360 trees) and averaged over 5 seeds. On the five walk-forward folds
the live-style model is worse: RMSE QB 86.4 vs 84.2, RB 60.5 vs 59.1, WR 54.2 vs 53.2, TE 40.7 vs 38.7; Spearman TE 0.734 vs 0.767. **Backtest and simulator results are NOT
affected**; `projections_2026_v1.json` (the live file) is. **Stakes measured 2026-10-27** (`src/evaluation/live_style_oos.py`, see `LOG.md`): training the backtests the live way costs `need+wait` about 13 starter points and 0.6 pp of title odds at the calibrated noise
(edge over ADP +53 -> +41 points, +4.8 -> +4.2 pp) and about 19 points at double noise (+31 -> +11); the edge survives at every noise level. Fix DECIDED 2026-10-27 (option 2, see NEXT TASK above); the alternatives that were considered: a fixed tree count per position (median best iteration of the
other folds: QB ~251, RB ~253, WR ~342, TE ~209) trained on all data, or early-stopping on the newest season only. Then rerun predict -> vor -> export_projections. Not urgent (nothing is drafted from
the 2026 file; it is replaced in the Phase 3 retrain) but fix it before Phase 5 so the app never ships the overfit models. Possible interaction, unmeasured: an overfit model makes
larger model-vs-ADP disagreements, which the recommender's edge is built on. Detail: memory note `project_live_model_tree_count`.

**Working agreements with the user.** Ask before any design decision that was not specified (memory: `feedback_ask_design_decisions`); fix mistakes as
they are found, even while exploring (`feedback_fix_mistakes_when_found`); commit and push only when asked; log decisions that rejected an
alternative or changed results in `LOG.md`. Evaluation protocol that worked: 100 seeds, judge on title odds and starter points, paired against the adopted arm, always with the leave-one-season-out line; the noise floor on title odds is about
+/- 0.3-0.5 pp, a weight picked on the same seeds is in-sample, and a new variant is adopted only when it beats the adopted one on both metrics, held out and at half and double noise. Compare projection files only when plain ADP scores the same in both worlds.

**Housekeeping.**
- **Committed on 2026-10-27, not pushed:** three commits on `phase-2-csharp` after `0ce7f32`: `40c3caa` (C# recommender, simulator and tests: waiting bonus, league-finish metric, opponent-draw fix, sweeps), `0b05ca7` (Python studies `src/evaluation/{blend_test,handcuff_study,live_style_oos,risk_predictability}.py`
  and the unused `volatility` feature group in `src/features/advanced.py`), `a44f025` (docs, `.claude/CODEMAP.md`, `.claude/CLAUDE.md`, `tools/`, the pre-commit hook that also checks the code map, and `.claude/settings.local.json`), plus a small follow-up that corrects this note. `origin` is still at the 2026-10-22 state.
  The pre-commit hook runs pytest and `tools/gen_codemap.py --check`; regenerate the map after adding or renaming code. `.claude/settings.local.json` denies Claude reads of `data/raw/**`, `data/processed/sim_baseline.csv`, `output.log` and `archive/**` (a user rule; analysis scripts do read `data/raw` themselves).
  Generated, gitignored artifacts: `data/processed/{blend,live_style}/`, `live_style_oos.parquet`, `handcuff_events.csv`, `risk_predictability.csv`, `sim_baseline.csv`. Sweep outputs lived in the session temp directory and are not in the repo (the numbers are in `LOG.md`).
- The user enabled mobile push (`agentPushNotifEnabled` in `~/.claude/settings.json`); Remote Control must be connected for it to reach the phone.
- Branches: `phase-2-csharp` is the working branch (pushed up to 2026-10-22). `main` (Phases 0-1) is pushed too. `Model_v2`, `Model_v3`, `draft_logic` and
  `phase-1-evaluation` are fully merged history and can be deleted. Merge `phase-2-csharp` into `main` when the user decides.
- `src/app/cli.py`, `src/draft/vbd.py`, `src/draft/simulator.py` live in `archive/`. The Python advisor in `src/draft/` (recommender, roster,
  draft_state, advisor) is superseded by C#; `vor.py` is still needed to build `predictions_table.parquet`, which the exporter reads.
- `data/raw`, `data/processed`, `data/external` are gitignored; rebuild with the pipeline above (`ffc_scraper.py` and the exporter are the newest steps).
- Tooling gotchas: piping `dotnet run ... | head` can leave a `DraftBot.Sim` process holding the build output (kill it before rebuilding); do not build or run tests while a sweep is running (it locks the binaries); long
  multi-line shell heredocs containing apostrophes can fail in this harness, so write files with the file tool; the auto-mode classifier once denied a read-only inline Python command that an identical retry then ran (do not work around a denial, retry once or ask).
  A full 100-seed backtest takes about 100 s; `tune-lookahead` took hours, so use few seeds for anything that re-values many players per pick.
- `README.md` documents the pipeline steps and the guardrails; CI runs pytest and `dotnet test` (`.github/workflows/tests.yml`, not yet exercised on GitHub).
