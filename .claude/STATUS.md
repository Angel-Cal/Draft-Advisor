# DraftBot — Project Status

**Last updated:** 2026-10-21
**Active branch:** `phase-2-csharp` (Phase 2 work, committed, not merged to `main`; `main` has Phases 0-1 and is not pushed to `origin`)
**Phase:** Phases 0, 1 and 2 complete (ROADMAP.md is updated). Next: Phase 3 (model v2, after the 2026 season) or Phase 4 (recommender v2, which Phase 2's simulator now lets us evaluate).
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
level), opponents draft by ADP + a personal bias per player, rosters scored by the best lineup from actual season PPR.
Same opponents face every strategy, so differences are paired. Opponent noise is a guess, so it is swept (x0.5 / x1 / x2).

| Strategy (noise x1) | Starter points | Mean finish (of 12) | Top 3 | 1st | vs ADP (paired, +/- 1 SE) |
|---|---|---|---|---|---|
| Plain ADP | 1796 | 5.8 | 31% | 10% | |
| Pure VOR | 1694 | 7.7 | 10% | 1% | -102 +/- 3 |
| Current recommender (ported) | 1547 | 10.3 | 1% | 0% | -249 +/- 3 |
| Recommender + reach control (`windowed`) | 1755 | 6.4 | 24% | 6% | -41 +/- 3 |

The order is the same at x0.5 and x2. **The bar for Phase 4 is plain ADP, not the old recommender.** VOR beats ADP in 2021
and 2022 but loses by 237 points in 2023, so it is season-dependent. The recommender reaches for model-vs-ADP disagreements
(its `value_gap` term), and the model does not beat ADP. Caveats: SEs assume independent drafts; lineups use season totals
(no byes or weekly moves); `injury_flag` marks 40-50% of the pool, which makes the recommender's risk penalty blunt.
Decisions behind all of this are in `LOG.md`.

**Reach control** (`ReachSettings`, default lambda 0.3 / cap 4 sigma, provisional): the baseline recommended ADP 70-112 players
at pick 6; the windowed variant stays near the pick (Jefferson, St. Brown, Chase). It recovers about 210 of the 249 points lost
to ADP, beats ADP in 2021, 2023 and 2024 and loses in 2022 and 2025 (-243). Still below plain ADP overall. Mock draft: `--window true`.
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
```

C# (needs the exported JSON files; .NET 9 SDK):

```bash
cd csharp
dotnet test                                                          # 81 tests
dotnet run -c Release --project src/DraftBot.Sim -- backtest --seeds 100   # baselines + regret -> data/processed/sim_baseline.csv, sim_regret.csv
dotnet run --project src/DraftBot.Sim -- draft --season 2024 --slot 6 [--seed 0] [--reveal true] [--window true]   # interactive mock draft
dotnet run -c Release --project src/DraftBot.Sim -- tune-reach --seeds 30   # reach penalty / cap sweep, leave-one-season-out
dotnet run -c Release --project src/DraftBot.Sim -- diagnose --season 2025 --a adp --b windowed   # which players/positions explain a gap
dotnet run -c Release --project src/DraftBot.Sim -- decompose --seeds 50   # recommender split into position rule vs player rule
dotnet run --project src/DraftBot.Sim -- tune-tiers                  # tier threshold sweep, leave-one-season-out
dotnet run --project src/DraftBot.Sim -- describe [--tier-gap 0.2]  # starters, replacement and tier sizes of the live file
```

Tests: `pytest -q` (133 tests; the data-integrity and export-file tests skip when `data/` is absent). A git pre-commit hook (`.githooks/pre-commit`, enabled with `git config core.hooksPath .githooks`) runs them before every commit.

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
  seasons, vs teammates available, team change) is what the idea needs. WR vacated/competing targets were tested null earlier.- **Half-PPR / standard targets** not built (Phase 3 item).
- Roadmap Phase 3 "team-context features" were largely done and tested in Phase 1 (see lists above); only features that survived are in the model. Phase 3 still needs: 2026 data retrain after the season ends, grading 2026 projections, half/standard targets.
- Model-vs-ADP gaps remain QB −0.10, RB −0.05, WR −0.06, TE −0.01 (top-150). Remaining gap is likely information the data lacks (camp news, injuries, depth-chart changes). Untested ideas are in the memory file `project_feature_ideas.md`.

---

## Hand-off after Phase 2

**What exists.** `csharp/DraftBot.sln`: `DraftBot.Core` (projection loader, league settings, replacement level, VOR,
ceiling/floor, per-position tiers, rosters, snake draft state, ported baseline recommender), `DraftBot.Sim` (opponent bots,
roster rules, lineup scorer, ADP/VOR/recommender strategies, experiment runner, CLI) and `DraftBot.Tests` (xUnit). Python
writes `data/processed/projections_<season>_v1.json` (live 2026 and backtests 2021-2025); the contract is
`.claude/projection_schema_v1.md`. Everything in `csharp/` reads only those files.

**Things the next phase should know:**
- The Python advisor (`src/draft/recommender.py`, `roster.py`, `draft_state.py`, `advisor.py`, and the VOR/tier code in
  `vor.py`) is now superseded by C#. `vor.py` is still needed to build `predictions_table.parquet`, which the exporter reads.
  Nothing was archived yet.
- Half-PPR and standard columns are `null` (Phase 3). The 50/50 model + ADP-curve blend is not implemented; testing it in the
  simulator is a clean next experiment. The live ADP is Underdog and the backtest ADP is FantasyPros (they price positions
  differently), so live recommendations have no backtest equivalent for ADP-sensitive logic.
- Opponent noise (1 + 0.1 x ADP) is an unvalidated guess. The tier threshold (0.10 x RMSE) was tuned but gap-based tiers did
  not beat equal-size tiers at usable counts; Phase 4 can try equal-size or capped-size tiers.
- Phase 4 should keep the ported recommender as a baseline in the simulator and judge changes on starter points vs ADP first;
  hindsight regret is noisy.
- The `csharp/` tests are not in the pre-commit hook; CI runs them (`.github/workflows/tests.yml`).

**Housekeeping:**
- Phase 2 work is on branch `phase-2-csharp`, committed (3 commits) but not yet merged to `main`. `main` is merged locally but **not pushed** to `origin`
  (`Angel-Cal/Draft-Advisor`). The `Model_v2`, `Model_v3`, `draft_logic` and `phase-1-evaluation` branches are fully merged
  and can be deleted.
- `src/app/cli.py`, `src/draft/vbd.py`, `src/draft/simulator.py` live in `archive/`.
- `README.md` documents the pipeline steps and the guardrails.
