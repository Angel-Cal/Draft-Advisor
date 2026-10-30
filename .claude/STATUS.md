# DraftBot — Project Status

**Last updated:** 2026-10-28
**Active branch:** `app-build` (the app, from `main` at `0e0800a`; `main` and `origin/main` hold everything up to the mockup, Phases 0-4 included)
**Phase:** Phases 0, 1 and 2 complete; Phase 4 (recommender v2) is essentially done: single score, reach control, roster need, bench value and the cost-of-waiting bonus are in, the league-finish metric exists, and the other ideas were tested and rejected (see "Hand-off" at the bottom). Next: Phase 5 (the reasoning strings and the live training fix are done). Phase 3 (model v2) waits for the 2026 season to end.
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
dotnet run -c Release --project src/DraftBot.Sim -- tune-rollout --seeds 20 --samples 10 --candidates 4 [--metric ...]   # rollout policy improvement (rejected; very slow: 1,200 drafts took 2 h, 300 drafts 11 min)
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

- **2026 evaluation is frozen (2026-10-28):** rules in `.claude/PREREGISTRATION_2026.md`, snapshot in `.claude/snapshots/`. After the season (Jan 2027): refresh the raw stats to include 2026, run `preseason_eval.py score --season 2026 --actuals <file> --exclude 00-0038117`, record the result in `LOG.md`. The first clean freeze is the first week of August 2027 (`snapshot --season 2027`, then record its hash in the doc).
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

### Session handoff, 2026-10-28 evening (updated 2026-10-29): the app is being built; the reach-cost experiment and the short-season fix are done (DONE lines below)

**Repo state.** Branch `app-build` (pushed to `origin`), created from `main` after the mockup was merged and pushed. Tests: 230 xUnit, 160 pytest, all passing (2026-10-30). `.claude/settings.local.json` is the user's own and is never committed by Claude.
Read `APP_SCOPE.md` (what version 1 is, milestones, how to run), `APP_DESIGN.md` (every visual rule and what it obliges the engine to do) and the LOG entries dated 2026-10-28 headed "App".

**Built this session.** Milestone 1: `DraftAdvisor.Advise` (Core) returns everything the draft screen shows. Milestone 2: `DraftBot.App` (Razor class library) and `DraftBot.Desktop` (WPF + BlazorWebView) play a practice draft from slot 5 of 12
against the simulator's bots; run it with `dotnet run --project csharp/src/DraftBot.Desktop` (it needs `data/processed/projections_2026_v1.json` or `DRAFTBOT_PROJECTIONS`). Close the app before rebuilding or the build fails on locked files.
After the user tried it: Pause/Resume beside the clock; reaches (reach cost of 25 points or more, `Explainer.IsReach`; the first pick of reach is free since 2026-10-29) are kept out of the recommendations and listed under "Past the wall"; the headline says "Close call" when the top two picks at different positions score within 5%;
amber and the "Recommended" tag only go to what the advice backs; the top pick is always tagged "Recommended"; the bargain tag is solid white; card stats are a 2 x 2 grid. Still to build: milestone 3 (Players, Board, Settings gear, first-run), then Sleeper (milestone 4).

**DONE 2026-10-29: the survival-aware reach cost was tested and NOT adopted** (S-scaled lambda 1000: +12 points / +2.7 pp title odds over the adopted advisor in-sample, but the held-out points check is -9 +/- 30 and 2025 loses; numbers in the LOG entry of that date; `ReachSettings.SurvivalPower`, `tune-reach-survival`; default 0 = unchanged). Follow-up 2026-10-29: a free-zone reach cost and a fresh-seed retest of the survival-scaled cost were also not adopted (LOG entry of that date; pick 5 can flip RB/WR on a 0.4-pick ADP gap, by design of the wall). Still open: the UI line for "early pick" (1 sigma on cards vs 0.25 in the sentence), and the user's request to list each player's bye week in the app (needs a 2026 bye source; live files have none).
**DONE 2026-10-30 (modeling session): the advisor's 2026 edge is pre-registered** (`PREREGISTRATION_2026.md`, section "Advisor edge": frozen commit `aba9db8`, projections and ADP hashes, title-odds edge expected +4.5 pp with range -3 to +12, pooled eighth-season rule; scoring procedure for January 2027; `src/evaluation/frozen_file_outcomes.py` attaches outcomes to the frozen file, tested on 2025). Do not change the advisor's Core defaults before it is scored without treating the result as a 2027 hypothesis.
**DONE 2026-10-30 (modeling session): the simulated league (1QB/2RB/3WR/1TE/1FLEX) is the user's, not the standard one: about half of the points edge is that mismatch** (+40.7 -> +19.1 points, title +4.5 -> +2.7 pp in a 2-WR league on the validated files; live-recipe +40.0 -> +25.0). Every Sim command now takes `--wr/--rb/--qb/--te/--flex/--bench/--teams`. The tuned settings were then re-run in the 2-WR league and transfer (large effects keep sign and size; option value over the waiver level is the only league-dependent term, worth ~6 points in 3 WR and nothing in 2 WR); rounds 7+ still lose 8 points per draft there, which no arm recovers; nothing changed.
**DONE 2026-10-29 (modeling session): where the edge comes from** (`calibrate-deviations`, LOG first entry): the model is NOT better calibrated where the advisor acts (slope 0.23 vs 0.3 overall; rounds 1-2 anti-calibrated, -0.76), almost all of the edge is rounds 3-6 (+42.6 of +40.4 points per draft), and ~85% of that is cross-position choices, chiefly WR-over-RB swaps whose payoff flips by season (-0.64 correlation with the season's RB-minus-WR residual; 7 seasons). The WR-over-RB swaps are paid by the RBs the market takes in rounds 3-6 busting in 2020-23 (passed RB below replacement every year) and lose in RB-boom years (2024: -97); over 2015-25 RBs and WRs in that range did equally well against ADP (-2.6 vs -5.4), so do not expect that component to repeat. The RB busts are injuries (83% of busts missed 4+ games, healthy RBs beat the curve in every era; `rb_availability.py`): the lean is a bet on the RB injury rate. The lean itself is partly structural (a market-neutral ADP curve still gives 1395 WR-over-RB against 545 RB-over-WR swaps in the 3-WR league), is flipped by RB-friendly valuations (408 / 1371), and the model is milder than neutral (1278 / 880): it does not learn the lean from RB busts. The edge is largely positional allocation; it is NOT position-level outcome luck (a position-neutral world, `position_neutral.py`, leaves it unchanged: +40.7 -> +40.3 in 3 WR).
**DONE 2026-10-29 (modeling session): "train on what ADP misses" tested and REJECTED** (`adp_residual.py`; LOG, first entry; ADP exports for 2015-2018 added): residual target gives the accuracy of the ADP curve (RMSE 74 -> 70) but the advisor edge falls from +40.7 to +22.4 points and title +4.5 -> +0.8 pp; ADP as an input is neutral (+43.3); training on draftable rows only is neutral (+39.6). Untested follow-up: scale the model's gap to the curve UP (k > 1).
**DONE 2026-10-29 (modeling session): two more backtest seasons, 2019 and 2020** (ADP from Wayback with source dates checked; projections walk-forward from 2019; files `projections_2019/2020_v1.json` in `data/processed` and `routed/{current,routed}`; LOG, first entry). The advisor's edge over ADP is about +3 in those two seasons (seven seed blocks of 100: +6.2, -9.8, +8.7, +9.5, +0.7, +3.5, +1.3) against +54 in 2021-2025 (all seven +40.5 at x1). The Sim's paired SE is now clustered by (season, seed), because the 12 slots of a seed share opponent biases (3.8 -> 5.3 here); older LOG numbers keep the smaller SE. **(CORRECTED 2026-10-30: the collapse was staleness of the window, not its size; recent windows of 3-6 seasons match all-history within ~1.5 RMSE points; the cause of the small 2019-2020 edge is open, see LOG.)** Original wording: **cause found: those folds train on 3-4 seasons.** The same test applied to 2021-2023 (train 2015-2017) takes the edge from +78 to +9 (`thin_training_check.py`); structure alone is about +13 a season in every era; the edge is the model's information and needs a long training window. The collapse is seed-proof (+9.3 vs +10.0 with other model seeds). Rolling 4- or 6-season windows do not beat all earlier seasons (2022-25 mean +30.5 / +59.5 vs +46.5, inside the +/-18 that single seasons' dependence on training data allows), so training stays on all seasons; the 2024-25 dip (+45, -7) is treated as noise. The big structural effects hold on the new seasons; plateau-sized ones do not. `--seasons 2019-2025` runs the Sim on them; `world_sweep.py` still covers 2021-2025 only.
**DONE 2026-10-29 (modeling session): the settings tuned on the validated files were re-tested in ten worlds** (`src/evaluation/world_sweep.py`; LOG, first entry): the waiting bonus (+8 points, +1.1 pp title over plain `need`, ahead in 9 and 10 of 10 worlds), weight 4 (plateau 2-4), lambda 1000 (300 loses; 3000 is +2.6 inside noise), cap 4 sigma and the free first pick all hold; nothing changed. About +9 points of the advisor's edge survive when outcomes are shuffled among ADP neighbours (the structural part); the rest depends on the projections. Bench structure and the tier threshold were re-tested in the same ten worlds too: the structural bench weights and the option value hold (flat bench -16 to -24 in every world), q 0.23 stays (0.10-0.15 is +1.7, inside noise), the starter option and bye cover rejections stand, and the tier threshold has NO effect on the adopted advisor (tiers are read only by the old baseline recommender). Only the narrow rejections (rollout) were not re-run.
**DONE 2026-10-29 (modeling session): reach cost at the top of the draft.** The pick-5 flip (McCaffrey over Smith-Njigba) was a 102-point reach-cost swing from a 0.4-pick ADP gap; one early decision in five changed with a one-pick ADP nudge. **Adopted: the first pick of reach is free (`ReachSettings.FreePicks` 1, in `DefaultReach`)** and the advice now reports confidence (`RankedPick.TopShare`, 30 ADP-nudged re-rankings; a second position with >= 20% makes the call close); the screen's reach line is `Explainer.IsReach` (cost >= 25 points). **The survival-scaled cost (option C) was implemented and REVERSED:** it lost 25-35 points at every noise level in the live-recipe world (`data/processed/routed/routed`) although it was best on the validated files; `SurvivalPower` stays in the code at 0. New tools: `trace-reach`, `stability-reach`, `case-reach`, `tune-reach-picks`. Judge sweeps on the live-recipe files too. Details: LOG 2026-10-29 (first entry).
**DONE 2026-10-29 (modeling session): the short-season under-projection is confirmed (+34 points, 60 draftable rows, QB and RB only) but NOT fixed: per-game features, a per-game target and pulling short-season players toward the ADP curve all fail or tie in the simulator; numbers in the LOG entry of that date, scripts `short_season_{check,fixes,curve}.py`. Second pass, ADOPTED: the gap is an elite-player (ADP <= 80) effect carried by season-total inputs; `src/models/short_season.py` projects players with prior games <= 9 from a rate view of the features (wired into `predict.refit_position`, live file rebuilt). Walk-forward with the live recipe: short-season residual 36.9 -> 24.6, no change for others; simulator `need+wait` edge +36.4 -> +42.1 at noise x1 (+31.3 -> +34.4, +20.0 -> +22.8 at x0.5 / x2). **Live cases repaired: Nabers WR27 -> 13, Burrow QB25 -> 8 (165 -> 272, ADP QB4; the QB rate view also drops `qb_att_share_prev`, the user's suggestion, which the backup's attempts had contaminated). Daniels (195) and Murray (165) stay well below ADP; B.Cook fell 123 -> 84 (watch). The QB evidence is 4 elite rows.** Accepted by the user (2026-10-29): dropping the share can lift a true backup from waiver level to the roster edge (backtest: 4 short-season QBs above replacement, all 2024, one pure backup, Flacco 217 projected vs 99 actual; live: only Burrow and Purdy are above replacement); no ADP gate built. Open: the app label for the QB cases (app session). Numbers: LOG 2026-10-29.
**(Original) NEXT MODELING TASK: the model under-projects players coming off an injury-shortened season.**
*Found 2026-10-29 in the app.* J.Burrow (CIN QB, ADP 53.2, QB4 by ADP) is projected 165 PPR (QB25 by projection; 8 games last season, `games_delta` -9, `injury_flag` true) against a replacement QB of 248, so his lineup gain is 0, his raw value is -83 and the card says "Not a starter" while the user has no QB. D.Maye (285) is fine. The tag is the engine working as designed; the input is the problem.
*Same pattern in the live 2026 file, ADP top 150, by position rank (ADP vs projection):* Burrow QB4 vs QB25, J.Daniels QB6 vs 28 (7 games), M.Nabers WR12 vs 27 (4 games), G.Wilson WR17 vs 35 (7 games), T.McLaurin WR25 vs 48, T.Kraft TE6 vs 16, M.Evans WR30 vs 53, K.Murray QB17 vs 33 (5 games), J.Reed WR47 vs 62. 58 players inside ADP 150 carry the injury flag.
*Backtest evidence (2021-2025, ADP <= 150, `actual_ppr` minus `projected_ppr`, my quick check, not a saved script):* prior-season games <= 9: n=42, mean residual **+34 points (SE 12)**; games drop >= 5 and games <= 12: n=52, +34 (SE 11); everyone else: n=525, +4.7 (SE 3). By position for games <= 9: QB +58 (n=6, SE 22), RB +63 (n=13, SE 23), WR +13 (n=20, SE 18), TE +6 (n=3). The `injury_flag` (durability) adds nothing beyond the games count (flagged +34, unflagged +40, n=5). So the model reads a short season as a lower-talent season and carries it forward. Assumes `games` in a backtest file means the season before the projected one (verify first).
*What the project already says.* `project_pitfalls` (memory): raw totals and `games` penalize injured players "by design"; Nabers WR37 was called legitimate; a planned fix "in the draft logic layer: blend toward career average for players under X games, or flag them" was never built. LOG 2026-10-28 (role-context study): "the biggest misses overall are injury seasons (R.Rice 2024, Aiyuk 2024, Evans and Godwin 2025)". The per-game WR rank variants tied the plain rank (LOG 2026-10-28, `wr_target_rank.py`), but they only test ranking among WRs, not the level of a short-season player's projection.
*Suggested approach.* (1) Save the check above as a script in `src/evaluation/` with a noise control and the leave-one-season-out view; add the comparison to ADP (does the market price these players better than the model? the ADP-curve residual for the same rows). (2) Candidate fixes, each judged by the project's rule (top-150 Spearman and RMSE against a same-size random-noise control, then the simulator for the recommender): per-game rate features (`ppg_prev`, games-missed share) so a short season is not read as low talent; a games-adjusted target (train on per-game points x expected games); blending toward the prior-two-season average when last season had <= 9 games. (3) Rebuild the live file (`predict` -> `vor` -> `export_projections`) and re-check the table above; Burrow should land near his ADP QB rank. Expect a market-shared view here: ADP already has Burrow QB4, so this is the model catching up, not a new edge; keep the simulator's "compare projection files only when plain ADP scores the same in both worlds" rule.
*The user's framing (2026-10-29), to test explicitly:* the engine trusts ADP over the model on the like side (the reach wall keeps out players the model likes past their ADP, even ones with an ~80% chance of being gone) but trusts the model fully on the fade side (Burrow is faded on a projection that is known to be biased for short seasons, though ADP has him QB4). Is that inconsistent? What the project knows: shrinking all or some disagreements toward ADP improved ranking accuracy but cut the simulator edge (LOG 2026-10-27: +52 -> +7 points for a uniform blend; RB-fades-only gained nothing), but the simulator's opponents follow ADP by construction, so it cannot reward trusting ADP; in that study the RBs who missed 5+ games had slope -0.77 (n 25-36, one of ~55 cells, not a finding). Questions: does the model-minus-ADP gap carry information for players off short seasons (QB, RB especially)? Is a projection fix (the approach above) better than shrinking toward ADP for that class? Also retest the survival-scaled reach cost (LOG 2026-10-29, +12 points in-sample, held-out -9 +/- 30) on a fresh seed set once the projections are fixed.
*Do not* patch it in the app. The app-side label change ("Below a free QB" instead of "Not a starter" when the slot is open) is a separate small task kept in the app session.
*(Original plan, kept for reference:)* **test a survival-aware reach cost.**
*Why.* At pick 20 (practice seed 15351, then draft B.Robinson at pick 5) the screen recommended D.London (WR) although waiting costs far more at QB (15.4 points) and TE (13.2) than at WR (3.6). Cause: the reach cost (lambda 1000 x z^2, sigma = 2 + 0.16 x pick)
charged 379 points for taking J.Allen (ADP 23.2, 3 picks past the pick) and 290 for B.Bowers, against waiting bonuses of 62 and 53; without the reach cost Allen scores 113 against London's 83. The wall only lets through players less than about one pick past ADP, and it ignores
whether the player will last: Allen has about an 82% chance of being gone by the next pick (#29), so "he would be there later" is false. The user's view: reach protection should stop wild picks, not force a pick.
*What the old tests say.* Lowering lambda was worse in the simulator (lambda 0: -17 to -31 points and title odds swinging 3% to 29% between seasons; lambda 100 unstable; lambda 400 and up a plateau, 1000 best; LOG 2026-10-21 to 2026-10-25), but all of that
was the same quadratic charge at other strengths, never one that depends on survival. The simulator's opponents follow ADP plus noise by construction, so it cannot reward exploiting a run. The waiting weight of 4 is still unexplained (LOG).
*Idea.* Scale the reach cost by S = P(player still available at my next pick) (S = 1 with no next pick): penalty = lambda x z^2 x S (also try S squared). A wild reach of a player who would last anyway stays blocked; a player who is about to go can be taken.
*Where.* The penalty is `var penalty = reach.Lambda * sigmas * sigmas` in `ScoreWith` inside `ValueRecommender.Rank` (ValueRecommender.cs, about line 300); survival is `WaitSettings.Survival(player, nextPick, reach, spreadScale)` (normal around ADP with sd 2 + 0.16 x ADP; `SurvivalSampler` is the simulated version) and the next pick is
`state.NextPick(teamIndex)`; the pool cap (4 sigma) is `BaselineRecommender.RecommendablePool`. Add the option with the adopted behavior as the default, so nothing changes until an arm wins.
*How to test.* Copy the `tune-reach-wait` pattern (`Program.cs` case "tune-reach-wait", `ReachTuning.ReportReachWait`; options `--seeds`, `--noise`, `--metric points|wins|playoffs|title`; `ArmSweep` does the leave-one-season-out check). Arms: the adopted advisor as control, S-scaled lambda 1000, S-scaled lambda 3000, S squared.
60 seeds, noise x1 (x0.5 and x2 as a check), points and title odds; formula arms are fast (the slow runs in this repo are the rollouts).
*Adoption rule (the project's).* Adopt only if it beats the adopted `need+wait` on points and title odds and the held-out check agrees; otherwise keep the wall, log the numbers in `LOG.md` and do not re-run. Either way, record the result and update `APP_DESIGN.md`.
*Then the UI question that depends on it.* The cards use a 1 sigma line for "early pick" while the sentence explaining a costly position uses 0.25 sigma (APP_DESIGN, "Open"); pick one line. If the new cost is adopted, re-check the pick-20 state; recommended: cards only for players you can take without a reach, the rest under "Past the wall".
*How the screens were checked (not in the repo, rebuild if needed).* A console project referencing `DraftBot.App` renders `Root` to HTML with `HtmlRenderer` (`RenderComponentAsync`), and headless Edge screenshots the page (`--headless=new --screenshot`); `PracticeDraft(file, league, 4, seed)` reproduces any draw, and `Draft(id)` plays the user's pick.

**Known gaps.** Players and Board are greyed-out tabs and there is no gear or Settings yet; the practice slot is fixed at 5; window size and display scaling are untuned; the pick clock only counts down (nothing forced at zero).

### Session handoff, 2026-10-28 (earlier; the older hand-off text below is still accurate for the recommender)

**Repo state.** Branch `role-caution-and-2026-freeze` is 1 commit (`8350dbe`) ahead of `main`. `main` holds 3 commits that are not on `origin/main` (`0e86b76`, `f73ba37`, `df6e229`). Nothing from this session after the pandas merge (`3cda9ea`, pushed) is pushed.
Uncommitted: the FantasyPros rewire (see DONE below) and its docs. `.claude/settings.local.json` is the user's own permissions edit and is deliberately never committed by Claude.
Last test run: 150 pytest, 199 xUnit. User preferences: no commit question after each action, commit/push/merge only on request, one reminder when uncommitted work piles up is welcome (memory `feedback_dont_ask_about_commits`).

**What this session produced** (details: `LOG.md` entries dated 2026-10-28). pandas 2.3.3 and CI on Python 3.12; the five recommender ideas (bye cover, slot weight, simulated survival, rollout, reachable alternatives) all rejected; WR case studies of K.Allen and W.Robinson with the tools
`target_competition.py [--profile|--role]`, `wr_case_studies.py quality|attribute|gaps` and `preseason_eval.py snapshot|score`; `src/features/role_context.py` and three optional WR-only fields in the projection files (`absence_share_prev`, `team_changed`, `rookie_r1_teammate`);
the text-only role caution in `Explainer`; the `rookie_comp` feature group (no gain, unused by the model); the 2026 freeze (`.claude/PREREGISTRATION_2026.md`, `.claude/snapshots/projections_2026_preseason.csv`, SHA-256 `e258935710f031495e34bf35b5ee93437b1896137612528bfede2c85751d21d3`).
Decided or rejected: no user-override/news feature (priced into ADP); the caution never changes a score; run detection waits for real mock drafts (Aug 2027); a market-shared error does not disqualify a finding (the model's job is what the market misses).

**DONE 2026-10-28: one ADP source (FantasyPros) for backtests and live** (user's decision; LOG entry of that date has the diff). The live ADP is the final pre-season export (dated 2026-09-07) saved to `data/external/FantasyPros_2026_Overall_ADP_Rankings.csv`; `python src/data/adp_scraper.py 2026` reads it (no network), fills the rookie ids from `data/raw/roster_2026.parquet` by name and position (80 of 83; the other 3 are at ADP 392+) and writes `data/external/adp_2026.csv`.
`vor.add_adp` reads that file (`processed/adp_table.csv` is still its output), the legacy `underdog` column is `adp` everywhere, the live `adp_source` is `"fantasypros"`, and the live file is capped at the 300 best-ADP players like the backtests. Rebuilt (`vor.py`, `export_projections.py`); pytest 150, xUnit 199.
The frozen March snapshot stays primary; the sensitivity snapshot is `.claude/snapshots/projections_2026_preseason_fp_adp.csv` (hash in `PREREGISTRATION_2026.md`; `preseason_eval.py snapshot --output` writes it). Result: the WR offset is unchanged (-21), the veterans' gaps shrank (Diggs +55 -> -3, K.Allen +46 -> +13), role-caution flags 4 -> 6.
Cautions: the Wayback Machine blocked this machine (HTTP 429) on 2026-10-28; do not hit it again soon (the 2026 path uses the local CSV). The live FantasyPros page has no player rows in its static HTML; use the CSV export. `pipeline.load_predictions` still reads `4for4-adp-table.csv` but nothing calls it (dead code, left alone).

**Next candidates.** (a) DONE, REJECTED 2026-10-28: the WR1/WR2 split by prior-season targets (three rank variants, `wr_target_rank.py`) is within noise of the control; see `LOG.md`. (b) Phase 5 app, logging every pick for later run detection and opponent-style learning. (c) Half-PPR and standard targets.
(d) January 2027: refresh the raw 2026 stats (the scraper ranges stop at 2025), run `preseason_eval.py score --season 2026 --actuals <file> --exclude 00-0038117` and record the verdict under the rules. (e) First week of August 2027: the clean freeze (`snapshot --season 2027`, hash recorded in a new pre-registration). (f) Phase 3 retrain after the 2026 season.

**Where the project is (2026-10-27).** Python research side and the C# product core both work and are tested (140 pytest, 162 xUnit; code map current). The model
still does not beat ADP at ranking players (Phase 1). The recommender, however, beats plain ADP in the simulator, both on starter points and in a head-to-head league season (13 weeks, 6-team playoff, odds averaged over
200 random schedules): `need` (lineup gain + position-specific bench value, minus an ADP-reach cost) is +42 +/- 2 starter points (title odds 14.4% vs ADP's 11.4%); the **default advisor `need+wait`** (adds the cost-of-waiting bonus,
raw weight 4, `draft --recommender need`) is +53 +/- 2 points, 65.2% playoff and 16.3% title odds (tables above, reasoning in `LOG.md`). The old Python recommender is the worst strategy (about -318 vs ADP).

**DONE 2026-10-27: the live projections now use the refit recipe** (`Model.refit_predict` in `train.py`, called by `predict.py`; per seed 0-4 early-stop on the newest season, refit on all seasons at `best_iteration_`, average; no tree-count scaling, the user had us try both and they tied). `projections_2026_v1.json` was regenerated (predict -> vor -> export), pytest 140 / xUnit 162 pass.
Walk-forward check (`src/evaluation/refit_oos.py`): RMSE 84.4 / 61.4 / 54.7 / 40.5 for QB / RB / WR / TE, as good as validated (84.5 / 61.7 / 55.0 / 40.1) and clearly better than live-style (87.1 / 63.5 / 56.2 / 42.5). **But the simulator edge only partly came back:** `need+wait` over ADP at the calibrated noise is +42.6 points / +4.1 pp title odds with the refit files
(validated +52.9 / +4.8 pp, live-style +40.7 / +4.2 pp); at double noise +19.5 (validated +30.6, live-style +11.1). The shortfall is in 2021 and 2025 and is unexplained (see the 2026-10-27 LOG entry); plan on about +40 points, not +53.
Follow-up done (`src/evaluation/seed_spread.py`, LOG entry "The validated-vs-refit simulator gap is real but small"): over three seed sets the validated recipe averages +48.5 and the refit +40.0 at x1 (so the +52.9 was a high draw); the gap is not seeds, not the header RMSE rescaling and not contrarianism, is about half QB, and does not show in title odds (+4.1 to +4.4 pp for both). Cause not identified; plan on about +40 points for the live file.

**Code map.**
- Python: `src/data/export_projections.py` writes `data/processed/projections_<season>_v1.json` (live 2026 + backtests 2021-2025 with `actual_ppr`
  and `weekly_ppr`); `src/data/ffc_scraper.py` pulls real pick-spread data used to calibrate the simulator. Contract: `.claude/projection_schema_v1.md`.
- C# (`csharp/`, net9.0): `DraftBot.Core` = projection loader, league settings, replacement/VOR/tiers, rosters, snake draft state, the ported old
  recommender (`BaselineRecommender`), `ValueRecommender` + `NeedSettings` (the new one), `LineupValue` (lineup gain, replacement, waiver level);
  `DraftBot.Sim` = opponent bots, roster rules, weekly lineup scorer, strategies, experiments and the CLI; `DraftBot.Tests`.
- CLI (`dotnet run -c Release --project csharp/src/DraftBot.Sim -- <command>`): `backtest`, `draft` (interactive mock draft; `--recommender
  need|value|position`), `diagnose`, `decompose`, `describe`, `calibrate-noise`, `fit-noise`, `tune-tiers`, `tune-reach`, `tune-value`, `tune-need`,
  `tune-bench`, plus the 2026-10-25/27 additions: `tune-wait`, `tune-spread`, `tune-reach-wait`, `tune-horizon`, `tune-where`, `tune-scarce`, `tune-standardized`, `tune-starter`, `tune-bye`, `tune-slot`, `tune-survival`, `tune-reachable`, `tune-rollout` (very slow), `tune-lookahead` (slow),
  `calibrate-survival`, `diagnose-scales`. The `draft` advisor options are `need` (= need + waiting bonus, the default), `need-only`, `value`, `position`, `bench`, `option`. The `tune-*` sweeps take `--metric points|wins|playoffs|title`
  and report a paired difference against the headline arm and a leave-one-season-out check. Options worth knowing: `--seeds N`, `--noise X`, `--unrestricted true` (lifts the sim's roster rules for the drafter only),
  `--season-totals true` (old scoring).

**Settled decisions (details and numbers in `LOG.md`).** Tier threshold 0.10 x position RMSE; ADP-reach cost lambda 1000 with a 4-sigma cap; opponent
bias SD 1 + 0.12 x ADP (calibrated to FFC mock drafts); weekly hindsight-optimal lineup scoring; bench value = structural k-th-backup weights (q = 0.23)
x option value over the waiver level, with dead picks (3rd QB/TE) ranked last; the position-first step was dropped because it caused the 2025 loss
(it favors WR by unfilled slots). Settled 2026-10-25/27: opponents' random draws are taken in player-id order, not pool order (so comparisons between projection files are valid); the cost-of-waiting bonus (survival to my next pick from the ADP model, same-position
alternatives, raw weight 4, horizon 1) is the default and its weight is a mixing weight (about 1.4 in standardized units, earned at RB and TE in rounds 1-4); the league-finish metric is the second judge next to starter points.

**App design.** The app mockup is settled (user: "pretty happy"); `.claude/APP_DESIGN.md` records every visual rule and the engine work it implies, `mockup/` holds the source (branch `app-mockup`). Still the mockup phase: do not build the app until the user scopes it.

**After the next task (candidates).** Reasoning strings are done (2026-10-28: `Explainer`, see `LOG.md`; its alternative to waiting is now the bonus's own `WaitFallback`, and `DefaultWait` counts only alternatives inside the reach cap). Next:
Phase 5 (WPF + BlazorWebView app, Sleeper sync) and the Phase 3 retrain after the 2026 season (half-PPR/standard targets too). Recommender work is at diminishing returns. Tested and rejected, with numbers in `LOG.md` (do not redo): two-step lookahead,
multi-pick horizon, variance-aware starter value, spread-normalized bonus, RB+TE-only bonus (ties the global one), handcuff logic (the absorber of a lead back's work is not identifiable preseason), prior-season weekly volatility as a risk score or a model feature,
the 50/50 model + ADP-curve blend as the recommender's input (-12 points), and shrinking only some disagreements by player type (position, gap sign, RB fades; each loses edge, 2026-10-27). Bye-week cover (weekly lineups with each team's bye, as points in the score) changes nothing (-3 to +2 points, title odds equal; 2026-10-27). A slot-dependent waiting weight (the edge itself ranges from +18 to +91 points by draft slot) does not hold up leave-one-season-out (-1.9 +/- 1.8 points; 2026-10-27). Survival estimated by simulating the other drafters' picks with their rosters, caps and forced fills (17% better Brier) gives the same picks' worth (0 +/- 1 points) and the same best weight, 4 (2026-10-27). Counting only alternatives the recommender could take at the later pick (inside the reach cap there) ties the adopted bonus (-1 +/- 2 points, -0.1 pp title odds); also applying the reach cost destroys it (-124 points), since lambda 1000 is a wall, not a price (2026-10-28). Rollout policy improvement (play the draft forward with sampled opponents for the top 4 candidates) gains +15 +/- 6 points over the adopted advisor but loses 55 in 2023, is optimistic (uses the simulator's own opponents) and costs minutes per draft (2026-10-28). Untested: a lighter blend weight (for example 25% ADP curve), a first-principles derivation of the bonus weight (the survival model that knows opponents' position caps is done: no gain). Position safety and
run detection use the same survival signal and cannot be validated without real pick-by-pick draft data (the FFC data is aggregate per player).

**Open questions / unvalidated.** How representative FFC hobbyist mock drafts are of the user's league; the option-value bench term assumes normal
projection errors and a crude waiver level; weekly lineups are hindsight-optimal; the live ADP is now FantasyPros like the backtests (2026-10-28); the
simulator's QB/TE caps for opponents are an assumption; hindsight regret is mostly luck (foresight regret is the informative one).

**Known issue FIXED 2026-10-27: the live projections were not from the validated model (bug sweep, 2026-10-25).** `predict.py` used to train the live models at the 1000-tree cap with no early stopping and one seed, while the validated files are early-stopped and 5-seed averaged;
it now uses the refit recipe (see DONE above). Cost of the old recipe, measured with `src/evaluation/live_style_oos.py`: `need+wait` edge over ADP +53 -> +41 points at calibrated noise and +31 -> +11 at double noise. Nothing was drafted from the 2026 file; the Phase 3 retrain should reuse `refit_predict`.

**Working agreements with the user.** Ask before any design decision that was not specified (memory: `feedback_ask_design_decisions`); fix mistakes as
they are found, even while exploring (`feedback_fix_mistakes_when_found`); commit and push only when asked; log decisions that rejected an
alternative or changed results in `LOG.md`. Evaluation protocol that worked: 100 seeds, judge on title odds and starter points, paired against the adopted arm, always with the leave-one-season-out line; the noise floor on title odds is about
+/- 0.3-0.5 pp, a weight picked on the same seeds is in-sample, and a new variant is adopted only when it beats the adopted one on both metrics, held out and at half and double noise. Compare projection files only when plain ADP scores the same in both worlds.

**Housekeeping.**
- **Committed on 2026-10-27, pushed 2026-10-28 together with the later session work (`e601368`, `c21dd61`, `78a0f5c`):** three commits on `phase-2-csharp` after `0ce7f32`: `40c3caa` (C# recommender, simulator and tests: waiting bonus, league-finish metric, opponent-draw fix, sweeps), `0b05ca7` (Python studies `src/evaluation/{blend_test,handcuff_study,live_style_oos,risk_predictability}.py`
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
