# DraftBot — Project Status

**Last updated:** 2026-11-05
**Active branch:** `refactor` (from `app-build` at `15f5baa`; `app-build` holds the app milestones 1-2, `main` everything up to the mockup)
**Phase:** Phases 0, 1, 2 and 4 complete; Phase 5 (the app) in progress; Phase 3 (model v2) waits for the 2026 season to end. Current state: "Hand-off" at the bottom.
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
python src/models/predict.py                     # 2026 projections -> *_predictions.parquet (close the CSVs in Excel first); short-season players are routed (src/models/short_season.py)
python src/data/advisor_table.py                 # advisor table -> predictions_table.parquet (adds ADP fallback rows)
python src/data/major_injuries.py --print        # lists season-ending injuries not yet in data/external/major_injuries.csv; check each against a news report and add a row (major = true only for a torn knee ligament or Achilles)
python src/data/export_projections.py            # projections_<season>_v1.json: live 2026 + backtests 2021-2025 (C# reads these)
python src/data/adp_scraper.py                   # only to refresh historical ADP (Wayback Machine, cached in data/raw/adp_html)
python src/data/ffc_scraper.py                   # real pick-spread data from FFC mock drafts (cached in data/raw/ffc); used to calibrate the simulator
```

C# (needs the exported JSON files; .NET 9 SDK). `Program.cs` lists every command and option at its top:

```bash
cd csharp
dotnet test                                                          # 190 tests
dotnet run -c Release --project src/DraftBot.Sim -- backtest --seeds 100   # baselines + regret -> sim_baseline.csv, sim_regret.csv in data/processed/experiments/sims when the data is the live folder (the default), else in the --data folder; --out overrides
dotnet run --project src/DraftBot.Sim -- draft --season 2024 --slot 6 [--seed 0] [--reveal true] [--window true] [--recommender need|need-only|value|position|bench|option]   # interactive mock draft
dotnet run -c Release --project src/DraftBot.Sim -- world-sweep --data DIR --arms reach|need|ladder|tiers|qb|cards --seeds 100   # an arm set against the adopted advisor; python src/evaluation/world_sweep.py runs it over the worlds
dotnet run -c Release --project src/DraftBot.Sim -- calibrate-deviations --seeds 30   # model calibration on the decisions where the advisor departs from ADP (pre-registered for the 2026 scoring)
dotnet run -c Release --project src/DraftBot.Sim -- pick-log --data ../data/processed/experiments/worlds/routed/routed --seeds 100 --out ../data/processed/experiments/sims/pick_log_live.csv   # every own pick of ADP and need+wait
dotnet run --project src/DraftBot.Sim -- case-reach --file projections_2026_v1.json --drafted "J.Gibbs,B.Robinson" --team 5   # one draft state: the advisor's ranking, two reach references and the app's advice
dotnet run -c Release --project src/DraftBot.Sim -- calibrate-noise   # simulated vs real (FFC) pick spread by ADP bucket; fit-noise grid-fits the opponent noise formula
dotnet run --project src/DraftBot.Sim -- describe [--tier-gap 0.2]  # starters, replacement and tier sizes of the live file
```

The concluded sweeps (`tune-*`, `diagnose`, `decompose`, `trace-reach`, `stability-reach`, `calibrate-survival`, `diagnose-scales`) are in `archive/csharp/Sim`; `archive/README.md` says how to rerun one.

Tests: `pytest -q` (119 tests; the data-integrity and export-file tests skip when `data/` is absent). A git pre-commit hook (`.githooks/pre-commit`, enabled with `git config core.hooksPath .githooks`) runs them before every commit.

`data/raw`, `data/processed`, `data/external` are gitignored. `models/*_params` (tuned hyperparameters) **are tracked**.
Layout of `data/processed` (constants in `src/paths.py`): `live/` = the C# contract (`projections_<season>_v1.json`, `run_manifest.json`; the Sim's default `--data` and the app's file); `pipeline/` = training/prediction data, per-position predictions, `predictions_table`, `adp_table.csv`, and `oos/season_<year>.parquet`; `experiments/` = `ablations/` (result tables), `oos/` (experiment OOS predictions), `sims/` (simulator logs, world sweeps), `worlds/` (alternative backtest file sets for `--data`), `short_season/`, `scoring/` (graded frozen files).

---

## Data Integrity (read before changing the pipeline)

Silent data bugs were the main source of wrong results. Guardrails now in place:

- `src/data/validate.py` runs inside `pipeline.py`, `predict.py` and `advisor_table.py`: errors stop the run (null/duplicate keys, unknown team codes, a season losing rows in a merge, out-of-range values, prediction rows that differ from training rows or carry last season's age, duplicate players in the advisor table); soft problems warn.
- `src/features/manifest.py` must classify every training column as `prior_season` or `preseason_known`; an undeclared column fails `tests/test_data_integrity.py`.
- `tests/test_data_integrity.py` recomputes lagged features from raw files and fails if a column matches the target season; also checks train/serve parity, per-position feature isolation, ADP coverage, OOS files, pinned packages, and that the `RMSE` constants in `export_projections.py` (the files' `position_rmse`) match the current walk-forward error (within 5%).
- `data/processed/live/run_manifest.json` logs commit, timestamp, row counts and params checksums per run; stale outputs raise or warn.
- Benchmark standard: per-position only (no pooled "ALL" row — ADP prices positional scarcity), 5-seed mean with spread, always next to the last-year-PPR baseline.

**Bugs found and fixed this phase** (so they are not reintroduced):
1. `implied_total` used the target season's own average closing line (leak). Now the team's prior-season total, in training and prediction. QB top-150 fell 0.61 -> ~0.21 before later fixes; the earlier "QB beats ADP" was an artifact.
2. Legacy team codes (OAK, SD, ARZ...) silently dropped ~80 rows from 2015 (and so ~90 from 2016); `schedule` loading started at 2015. Fixed via `TEAM_MAP` and loading 2014 schedules.
3. Junk "Team" rows (null `player_id`, `games` 256–272) corrupted target share for 12 team-seasons. Dropped at load.
4. Prediction rows carried 2025 age/experience/team/total for a 2026 prediction. Now advanced to the prediction season.
5. LightGBM predicts positionally: prediction columns are aligned to training columns by name in `predict.py`.
6. `vor.py` (now `src/data/advisor_table.py`) read its own previous output, matched ADP players on name only (Harrison Jr. and Pittman appeared 8 times each, shifting the WR replacement baseline), and overwrote `predict.py`'s outputs. Fixed.

---

## Rookies and unmodeled players

Decision: **no rookie model** in this project (a pick/age/size model cannot beat ADP; a real one needs college data and is a separate later side project). Anyone the model cannot score gets an ADP-derived projection (`src/data/market_fallback.py`): an isotonic curve per position from rank-within-position (by ADP) to expected PPR, fit on 2021–2025. `advisor_table.py` adds those rows to `predictions_table` flagged `market_estimate=True`; players with no GSIS ID get synthetic `market:<name>` IDs. Leave-one-season-out RMSE on the top-150: RB ~63, WR ~67, TE ~62 (QB/TE samples are tiny). Caveats: deep ranks are biased upward (curve fit on players with >=4 games); curve is fit on FantasyPros ADP but applied to Underdog ADP (rank-within-position input mitigates the pricing difference).

---

## What Was Tested and Did NOT Help (don't re-run without a new idea)

All tested with the standing protocol: 10-seed ablation + random-noise control, drop anything within noise.

- Re-tuning params (100–400 Optuna trials): the TE and (first) QB re-tunes were adopted; RB, WR and the second QB re-tune (after `qb_att_share_prev`) never beat the existing params. More tuning is mostly fitting noise (500–1,600 rows per position).
- WR: vacated/competing targets, QB change/quality (first-round rookie override), draft-capital x youth, two-year-history idea (declined on reasoning).
- Team pass rate/pace/points per game, team EPA/success rate, depth ranks within team, team-change flag, `seasons_since_last`.
- QB: per-game PPR features, per-game target, smaller feature set, simpler/ridge models, depth-chart tier (improves starter-vs-backup AUC and RMSE but hurts ranking among actual starters; **declined**).
- RB depth-chart competition (carry share, expected lead, proven/rookie competitor): null once vacated features are in.
- Early vs late QB (2026-11-04, `qb_cliff.py`, `qb_opportunity_cost.py`): the realized cliff is after QB2 (QB3 = QB4-7), but each tier returns about what the RBs/WRs at its picks return (QB1-2 -2, QB3-7 -8, QB8-12 +6 points; strategy differences inside noise). Lead: the mid tier (QB3-7) is the worst buy in both eras. The adopted advisor's first QB (`pick-log` + `advisor_qb_timing.py`): elite 8%, mid tier 33% (rounds 4-5), late 59%. "No QB before round 6-9" and a barbell arm (`world-sweep --arms qb`) were REJECTED: ahead pooled in every world (+1 to +8 points), but the gain is 2025 alone and the held-out check is negative in all seven worlds.
- Regression candidates by the model's reason for liking a player (2026-11-04, `gap_attribution.py`): about 40% of bullish calls (model 20+ above the ADP curve) end below it whatever the driver; stat-line-driven likes fail slightly LESS often (-7 pp, p 0.84 for the predicted direction). Lead only: trend-driven likes (n 9-10) 67-70% below; recheck in the 2026 grading.
- QB interceptions as positive game-script signal (2026-11-04, `int_game_script.py`, evidence only): a first-half INT returns +0.4 second-half points against a -3.0 full-game cost; prior-season INT rate predicts nothing beyond the other rates (small job-loss risk) and the ADP curve does not misprice it.
- ADP source disagreement (2026-11-03, `adp_dispersion.py`): weighting the model's gap to the ADP curve by how much ESPN/Sleeper/CBS/... disagree. No slope difference (permutation p 0.53-0.69, sign flips by season), worse held out than a uniform weight, and no link to outcome spread; no simulator run. Team-volume coherence (teammates' projections summing too high): -21 PPR per doubling, interval across 0, not built.
- Offensive line: continuity (returning starters, snap continuity, incoming starters), prior-season adjusted line yards / sack rate, and interactions — all null, and even the line's actual same-season ALY/ASR as an oracle moved RB top-150 by only +0.006 (QB +0.017). Don't build an OL rating for model gains.

## Open / Deferred

- **2026 evaluation is frozen (2026-10-28):** rules in `.claude/PREREGISTRATION_2026.md`, snapshot in `.claude/snapshots/`. After the season (Jan 2027): refresh the raw stats to include 2026, run `preseason_eval.py score --season 2026 --actuals <file> --exclude 00-0038117`, record the result in `LOG.md`. Also run the registered trend-driven-likes check (`PREREGISTRATION_2026.md`, "Trend-driven likes"; `gap_attribution.py` on 2026, report only, no change until 20 out-of-sample calls). The first clean freeze is the first week of August 2027 (`snapshot --season 2027`, then record its hash in the doc).
- **ADP freshness (user's catch, 2026-10-28):** the live ADP table is from 2026-03-31, before the NFL draft and camp (rookies listed with team TBD, 33 of 44 market rows teamless). Model projections do not use ADP, but the pool, rookie rows, curve, gaps and the recommender's reach and survival do. Decision (user, 2026-10-28): move the live ADP to FantasyPros too, one source for backtests and live. The live page `fantasypros.com/nfl/adp/ppr-overall.php` has no date on the ADP itself, but its source list is dated (ESPN 9/07, CBS Sports 9/07, RTSports 9/06, Fantrax 9/07, Sleeper 9/07), so it is the final pre-season ADP, unchanged since the 2026-09-09 opener. The page's static HTML holds no player rows (loaded by script), so the table has to be saved from a browser or exported; Wayback blocked this machine (429) after the scraper's retries. Done the same day, see the hand-off.
- **Tested 2026-10-28, no gain (see `LOG.md`):** a WR1/WR2 split by last season's targets instead of the depth chart. `target_rank_now` (rank among the new roster's receivers by prior-season targets) exists in `team_context.py` but is not in the WR model or the WR ablation (which covered vacated, competing and incoming targets only).
- **Run detection (deferred by the user 2026-10-28 to early draft season, Aug 2027; nothing built).** Not implemented in any form: the waiting bonus reads ADP only, and `SurvivalSampler` models drafter needs, not observed picks. Two reasons to wait: (1) the simulator's opponents draw independent noise, so they produce no runs and a detector could only be shown to do no harm there; (2) it is not even clear which way to play a run: leaning into it (take the position before it dries up) versus profiting from the players who fall because of it. Real pick-by-pick data decides that, and we have none (FFC is aggregate per player). Plan: use the early-season mock drafts against real drafters (Underdog / Sleeper) to log picks, check whether runs happen and what the fallers cost, then test a detector on that. Position safety shares the same blocker.
- **Target-competition hypothesis (user, 2026-10-28; deferred, no work started): the model cannot tell when a player's prior volume will not carry over because the set of players competing with him changed.** Two cases, one mechanism. Keenan Allen 2023 -> 2024: his main target competition at LAC was a RB; at CHI he met an established WR1 (D.Moore) and a rookie WR taken in the top 10 (R.Odunze), so his volume should have fallen and the model (235 projected, 184 actual) kept it. Wan'Dale Robinson 2025 -> 2026: his 2025 volume came from the WRs around him being injured (see his entry below), so 2025 overstates what he sees with a healthy room, and the model projects his 2025 total again. Common thread: last year's targets are treated as the player's own, when they are a share conditional on who else was available.
  What exists today (`src/features/team_context.py`): `competing_pass_targets` = last season's targets of the other WR/TE on the new roster, `incoming_pass_targets` = the part of that from players who arrived from other teams, `vacated_target_share`. WR vacated/competing targets were tested null. Why that test may not cover these cases (unchecked guesses): it is a level, not a change from the player's old room; RBs are not counted, so a RB-led old room (Allen at LAC) is invisible; a rookie has no prior targets, so a top-10 pick adds nothing to the competing volume; all competing targets count the same whoever earned them; and nothing looks at which of last year's targets were earned while a teammate was out. Candidate measurements, all derivable from existing data: change in total pass-catcher volume (incl. RB) between his old and new room; an incoming-rookie flag by draft pick; the share of his prior targets earned in games where the team's WR1 was inactive (weekly data, participation). First step when picked up: stratify the walk-forward OOS over-projection (2021-2025) by these measures and see whether the residual follows them, before building any feature; if it does, shrinking projections toward the ADP curve for flagged players may be a safer use than a new input (shrinking by player type lost edge before, LOG 2026-10-27). Checked in `data/raw` on 2026-10-28 (single players, not a test). Correction to "what exists today": the WR competition columns are built in `team_context.py` but are NOT in the WR model (`POSITION_FEATURES["WR"]` = depth tier + on-field share only); the WR model has no teammate-competition input at all. **Allen:** targets per game 9.8 (2021), 8.9 (2022), 11.5 (2023), 8.1 (2024); M.Williams played 13 games in 2022 and 3 in 2023, so Allen's best volume came in the year the WR2 was out. His 2024 volume fell about 30% per game: team RB/WR/TE targets 613 -> 523 and his per-game share roughly 32% -> 26% (season share is 24% -> 23% only because he missed games in 2023; approximate), with D.Moore 27% and R.Odunze 19% of CHI's targets. The model projected 235 PPR in 13 games (18.1 per game), he scored 12.3 per game (21.5 in 2023). The hypothesis fits. **Robinson: it only partly fits.** He had 140 targets in both 2024 (17 games, Nabers healthy, 25% share) and 2025 (16 games, Nabers played 4, 28% share): the absence raised his share but team targets fell 566 -> 506, so his volume did not rise; the 6.8 vs 9.4 targets per game with and without Nabers is from a 4-game sample. His PPR rose 182.7 -> 217.9 on the same 140 targets (1.30 -> 1.56 per target), so the 2025 excess is mostly per-target production, not volume (FPOE not flagging him is consistent with the opportunities being good). His 2026 situation (new team) is a separate unknown. Measure per-game share (games played), not season share, in any diagnostic. **Quality of targets (2026-10-28, `wr_case_studies.py quality`, LOG.md):** Robinson's target count was flat but their value moved: depth 4.7 -> 8.5, air-yards share 17% -> 28%, deep targets 4 -> 21, yards per target 4.99 -> 7.24 (red-zone targets fell 18 -> 13); it was already there in weeks 1-4 with Nabers healthy, so it is an offense-wide shift, not a forced promotion; Allen's 2024 drop was volume, not quality. A walk-forward test of whether big jumps in target depth, air-yards share or expected points per target predict over-projection (`--role`) found nothing (intervals across 0), so Robinson's role jump is not a detectable pattern. Model-side check of the rookie flag (`rookie_comp`, LOG.md): adding it as an input does not help (WR top-150 -0.0005 vs +0.0021 for noise; flagged rows' over-projection +27.4 -> +25.4); a WR1-vs-WR2 depth split cannot be built for pre-2025 charts. The remaining option is an after-the-fact adjustment, not tested.
  **Diagnostic run 2026-10-28 (`src/evaluation/target_competition.py [--profile]`, LOG.md):** room strength and teammate-absence share (Allen 0.74) show nothing detectable; a first-round rookie WR/TE on the new roster goes with +28 PPR over-projection (33 rows) but it falls to +10 (interval -5 to +24) among 12+ game players and the ADP curve over-projects the same rows by +23. Travis Hunter (listed WR, plays defense) is excluded from the competitor set. Profile search (a new situation AND 50%+ of last year's targets earned with the top rival out): 11 healthy matches over-projected by +24 PPR against -5 for the rest (interval -6 to +59), each half alone near 0 to +6; the ADP curve is also +21.5 on them. Among the 32 WR seasons the model rated 30+ PPR above the curve the mean over-projection was +33 (62% over by 20+), and the live 2026 list (Diggs, Samuel, Robinson, Allen, Tucker, Bateman, Wicks) is worth a manual look before drafting. W.Robinson 2026 (a profile match) is reported by the user as a big miss. A lead, not an edge; the advisor now shows it as a text-only caution on profile matches (`Explainer`, LOG.md "Role caution"), the score is unchanged; revisit after the 2026 season
- **Case study: Keenan Allen, 2024 (new situation; deferred by the user 2026-10-28, no work started).** The model had him at 235 projected PPR (ADP 78.4, injury flag set, team CHI after the move from LAC), the market was far lower, and he scored 184 actual: a miss of about 51 points, and the model's biggest disagreement with ADP at a position the recommender then has to ignore (it is past the reach cap at the picks where he matters; see the `tune-reachable` entry in `LOG.md`). The user's hypothesis, untested: the model handles players in new situations (team change, new QB or offense) poorly, so its confident calls on movers are the least trustworthy. Where to start when picked up: split the walk-forward OOS errors (2021-2025) into team changers and stayers, per position, and check the sign and size of the bias; look at what the lagged team-context features do for a mover (they are joined on the current team, so they describe the new team while his own history describes the old); compare against the other big 2024 movers. Related: `project_team_context_features` in memory (the "situation change" residuals).
- **Coaching tendencies** (head-coach pass-over-expected, pace, 4th-down aggression; coach's prior-team tendency when the HC changes): deliberately deferred by the user — "requires more nuance before touching". Only head coaches are in public data (schedules).
- **Week 1 line as a preseason team-strength feature** (user may try later): test the Week 1 spread/total as the legitimate version of the leaked implied total, QB first (see LOG.md "Deferred"). Low expected value for RB/WR/TE.
- **PFR advanced stats** skipped (only 2018+, would halve usable training rows). Participation `route` is only the targeted receiver's route (one value per play, blank otherwise), so per-player routes run do not exist and route participation is approximated by on-field share.
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
- **Case study for the efficiency idea (also the target-competition hypothesis above): Wan'Dale Robinson (2026 WR, now TEN).** FPOE does NOT flag him: 2025 +0.9 (rank 57 of 133 WRs)
  because his chances were plentiful (expected 217 PPR, 13th) and he converted them as expected. His regression risk is in the volume:
  Nabers played only weeks 1-4; Robinson saw 9.4 targets / 14.3 expected PPR per game without him vs 6.8 / 11.5 with him. The model
  projects 219 (= his 2025 total) vs an ADP-curve 147 (ADP 102, WR47): his edge over the market is the largest of all 123 WRs.
  FPOE measures conversion efficiency, not volume sustainability; a volume-sustainability signal (expected points vs his own prior
  seasons, vs teammates available, team change) is what the idea needs. WR vacated/competing targets were tested null earlier. (2026-10-28 check against the 2024 season: his volume did not depend on Nabers' absence, see the target-competition entry above; the regression risk here is in per-target production more than in volume.)
- **Per-opponent style learning (deferred 2026-10-27, Phase 5 feature):** real friends have team-level habits (a QB-hungry owner, a rookie lover, someone who always reaches for name players). Estimating each opponent's tendencies online from the picks already made (position shares vs ADP expectation, reach size) would sharpen the survival estimate behind the waiting bonus in a real league, probably more than any tuning left in the simulator.
  It cannot be validated here: `OpponentBot` biases are independent per player (fixed per seed and team, but no team-level trait such as a position preference), so there is nothing to learn, and the FFC data is aggregate per player, not per drafter. A test would need a team-level style written into the simulator by hand, which makes the result an assumption, not evidence. Build it with the live Sleeper-synced draft state (Phase 5), show it as an explained label, and treat it as unvalidated.
- **WR-lean investigation BENCHED until the 2026 season is graded (user decision 2026-10-30).** State: the lean is structural (plain VOR against ADP's RB premium; not the projections, the training target or RB stability), its direction is probably genuine (RB premium not paid back in realized value in 10 of 11 seasons, about -25 season-VOR points at equal ADP, weekly structure recovers about a quarter), but its payoff is weakly established (swap payoff +30 +/- 24 per swap over 7 seasons; the whole edge is about 2.8 SE at season level, not the simulator's printed +/-4) and the premium looks smaller recently (about -39 in 2015-18, -19 in 2019-25). Everything is in LOG.md under 2026-10-30 (entries on the lean attribution, the RB premium, the ladder and title odds, opponent styles, the noise collapse, the games prior). **When 2026 is graded:** run the pre-registered "Advisor edge" test (`PREREGISTRATION_2026.md`, builder `frozen_file_outcomes.py`), rerun `src/evaluation/rb_premium.py` and `rb_wr_stability.py` with 2026 added, and check whether the RB premium keeps shrinking. Not worth more work before then: more seasons of history are the only thing that moves the conclusion.
- **In-draft league-noise estimate with an ADP fall-back (logged 2026-10-30, not built):** the adopted advisor beats ADP only up to about x2 of the calibrated opponent noise (+3 points at x2, -80 at x3, -124 at x4; calibration x1 rests on aggregate FFC mocks, no friend league is measured), and telling the advisor the true spread does not repair it (LOG 2026-10-30, "Why the advisor falls far below ADP once opponents are 3x as noisy"). The advisor sees every opponent pick during a draft, so it can estimate the scatter of picks around ADP (observed pick minus ADP, scaled by the expected SD at that ADP) and shrink toward ADP, or switch to it, once the estimate passes about x2.
  Unlike per-opponent styles this one CAN be validated in the simulator, because noise is a single scalar the sim already varies (`world-sweep --noise`): success = at x2-x3 the guarded advisor is no worse than ADP and at x1 it loses nothing (x1 is where the +34 points and +4.5 pp are earned). Open points: the estimate is noisy in the first rounds (few picks, small ADP spread early), and the cause of the collapse is unknown (loss sits in rounds 7+ and in picks far below the best remaining ADP), so a cap on how far below the best remaining ADP the advisor may pick is the alternative or companion fix.
- **Half-PPR / standard targets** not built (Phase 3 item).
- Roadmap Phase 3 "team-context features" were largely done and tested in Phase 1 (see lists above); only features that survived are in the model. Phase 3 still needs: 2026 data retrain after the season ends, grading 2026 projections, half/standard targets.
- Model-vs-ADP gaps remain QB −0.10, RB −0.05, WR −0.06, TE −0.01 (top-150). Remaining gap is likely information the data lacks (camp news, injuries, depth-chart changes). Untested ideas are in the memory file `project_feature_ideas.md`.

---

## Hand-off (read this first in a new session)

One current-state section; the history behind every line is in `LOG.md` (the older dated hand-offs that used to stack here were folded in on 2026-11-05).

**Repo state (2026-11-05).** Branch `refactor`, cut from `app-build` at `15f5baa`. Tests: 119 pytest, 190 xUnit; code map current. The 2026-11-05 cleanup (LOG, "Refactor: concluded experiments archived") moved the concluded experiments and the old Python advisor to `archive/` (see `archive/README.md`), cut the rejected options out of the advisor's Core types, and left every simulator output and every exported projection file byte-identical. `.claude/settings.local.json` is the user's own and is never committed by Claude.

**Freeze: do not change the advisor before the 2026 season is scored.** Core defaults: reach cost lambda 1000 with a 4-sigma cap and the first pick of reach free (`ValueRecommender.DefaultReach`), waiting bonus weight 4 with alternatives inside the reach cap (`DefaultWait`), `NeedSettings.Default` (structural bench weights at q = 0.23 times option value over the waiver level, dead picks last). Pre-registered in `PREREGISTRATION_2026.md` (frozen commit `aba9db8`); the frozen file is `.claude/snapshots/projections_2026_v1_frozen.json` (SHA-256 `ebe202...`, rebuilt byte for byte in `a871a26`; the live export path is not a safe place for a frozen file). Any advisor change before then is a 2027 hypothesis.

**Calendar.**
- January 2027: refresh the raw stats through 2026 (extend the ranges in `src/data/scraper.py`); score the advisor edge (`frozen_file_outcomes.py`, then `backtest` and `calibrate-deviations` on the built folder, commands in `PREREGISTRATION_2026.md`); `preseason_eval.py score --season 2026 --actuals <file> --exclude 00-0038117`; the trend-driven-likes check (`gap_attribution.py`, report only); rerun `rb_premium.py` and `rb_wr_stability.py` with 2026 (the benched WR-lean question); if the QB rule is revisited, `world-sweep --arms qb --seasons 2019-2026` under the same rule. Record verdicts in `LOG.md`.
- After the season: Phase 3 retrain (reuse `Model.refit_predict` and the short-season routing), half-PPR and standard targets.
- First week of August 2027: the clean freeze (`preseason_eval.py snapshot --season 2027`, hash in a new pre-registration); run detection and opponent-style learning wait for logged mock drafts against real drafters then.

**The app (Phase 5).** Scope in `APP_SCOPE.md`, every visual rule in `APP_DESIGN.md`. Milestones 1-2 are done: `DraftAdvisor.Advise` (Core) returns everything the draft screen shows; `DraftBot.App` (Razor library) and `DraftBot.Desktop` (WPF + BlazorWebView) play a practice draft from slot 5 of 12 against the simulator's bots (`dotnet run --project csharp/src/DraftBot.Desktop`; needs `data/processed/live/projections_2026_v1.json` or `DRAFTBOT_PROJECTIONS`; close the app before rebuilding). What the cards do now: reaches (reach cost 25+ points, `Explainer.IsReach`) and dead picks never become cards, reaches are listed under "Past the wall"; "Close call" when the best pick at another position is within 5% or first in 20%+ of the ADP-nudged re-rankings; a "Toss-up with X" note replaced the confidence level; cards 2-3 say what they give up against card 1 in real points, or "Too early for this pick"; "Fills a spot" for an open starting spot filled at replacement level; the price reads Bargain at half a sigma past ADP; the injury tag is 4+ missed games a season over 3 seasons or a confirmed major injury (`data/external/major_injuries.csv`, reviewed by hand), with the history in its tooltip.
Still to build: milestone 3 (Players, Board, Settings gear, first-run), then milestone 4 (Sleeper). Known gaps: Players and Board are greyed out, no Settings, the practice slot is fixed at 5, window size and scaling untuned, the clock only counts down. Open UI items: one line for "early pick" (1 sigma on cards vs 0.25 in the sentence), bye weeks per player (needs a 2026 bye source).

**What to quote as the edge.** The adopted advisor (`need+wait`) over plain ADP in the user's 1QB/2RB/3WR/1TE/1FLEX league: about +40 points and +4.5 pp title odds on the live-recipe files over 2021-2025, about +3 points in 2019-2020; roughly half the points edge comes from the 3-WR lineup (2-WR league: +19 points, +2.7 pp). It is positional allocation in rounds 3-6, mostly WR-over-RB swaps that pay when the market's RBs bust (largely injuries), so expect it to swing by season. A user who picks a random card keeps under half of it; always taking card 1 keeps nearly all. The advisor beats ADP only up to about twice the calibrated opponent noise.

**Designed, not implemented (2027 hypotheses, LOG 2026-11-04):** the reach wall and early second TEs; the upgrade-from-waiting penalty for slot planning. Both start with a `pick-log` diagnostic, then 7 worlds x 100 seeds with the held-out rule.

**Next candidates.** App milestones 3-4. Half-PPR and standard targets. After the January 2027 scoring: move the helpers `preseason_eval.py` and `gap_attribution.py` import (from `gap_reliability`, `blend_test`, `target_competition`, `refit_oos`, `live_style_oos`) into one library module and archive those study scripts; they were left in place during the freeze so the pre-registered scoring code stays untouched.

**Settled decisions (numbers in `LOG.md`).** Tier threshold 0.10 x position RMSE (tiers only feed the old baseline recommender); opponent bias SD 1 + 0.12 x ADP (calibrated to FFC mock drafts), random draws in player-id order; weekly hindsight-optimal lineup scoring, with head-to-head title odds as the second judge next to starter points; the position-first step was dropped (it caused the 2025 loss); the reach cost, bench value and waiting bonus as in the freeze above; live projections use the refit recipe (early-stop on the newest season, refit on all, 5 seeds) with short-season players projected from a rate view (`src/models/short_season.py`); one ADP source, FantasyPros, for live and backtests; training uses every earlier season (rolling windows did not beat it).

**Rejected, do not redo without a new idea** (numbers in `LOG.md` and "What Was Tested" above): two-step lookahead, multi-pick horizon, starter option premium, spread-normalized bonus, RB+TE-only bonus, slot-dependent weight, simulated survival, reach cost on the alternatives, bye-week cover, rollout, survival-scaled reach cost, a free zone in sigmas, the 50/50 model + ADP-curve blend as input, shrinking disagreements by player type, training on what ADP misses, QB timing rules, weighting gaps by ADP-source disagreement, handcuff logic, weekly volatility as risk. Their code is in `archive/`.

**Open questions / unvalidated.** How representative FFC hobbyist mock drafts are of the user's league; the option-value bench term assumes normal projection errors and a crude waiver level; weekly lineups are hindsight-optimal; the simulator's QB/TE caps for opponents are an assumption; hindsight regret is mostly luck (foresight regret is the informative one); why the advisor collapses at 3x noise is unexplained.

**Working agreements with the user.** Implement directly but push back on bad decisions; fix mistakes as they are found and rerun what they touch; do not ask to commit after each action (the user says when; every commit is also pushed, per `CLAUDE.md`); log decisions that rejected an alternative or changed results in `LOG.md`. Evaluation protocol: state the mechanism and what each outcome would mean before running a test; 100 seeds, judge on title odds and starter points, paired against the adopted arm, with the leave-one-season-out line; adopt only when a variant beats the adopted one on both metrics, held out and at half and double noise; compare projection files only when plain ADP scores the same in both worlds.

**Housekeeping.**
- The pre-commit hook (`.githooks/pre-commit`, enabled with `git config core.hooksPath .githooks`) runs pytest and `tools/gen_codemap.py --check`. CI (`.github/workflows/tests.yml`) runs both test suites, not yet exercised on GitHub. `pytest.ini` keeps pytest to `tests/`.
- `.claude/settings.local.json` denies Claude reads of `data/raw/**`, `data/processed/experiments/sims/sim_baseline.csv`, `output.log` and `archive/**` (a user rule; analysis scripts read `data/raw` themselves).
- The Wayback Machine blocked this machine (HTTP 429) on 2026-10-28; the 2026 ADP path uses the local FantasyPros CSV export (`python src/data/adp_scraper.py 2026`).
- Tooling gotchas: piping `dotnet run ... | head` can leave a `DraftBot.Sim` process holding the build output (kill it before rebuilding); do not build or test while a sweep runs; a full 100-seed backtest takes about 100 s.
- Mobile push is enabled (`agentPushNotifEnabled`); Remote Control must be connected for it to reach the phone.
