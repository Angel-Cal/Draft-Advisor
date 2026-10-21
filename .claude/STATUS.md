# DraftBot — Project Status

**Last updated:** 2026-10-20
**Active branch:** `draft_logic`
**Main branch:** `main`

---

## What It Is

ML-powered fantasy football draft assistant. Predicts 2026 PPR fantasy points for each player using position-specific LightGBM models trained on 2015–2025 NFL data, then uses those projections to drive a real-time draft advisor.

League settings: 12-team snake, PPR, 1 QB / 2 RB / 3 WR / 1 TE / 1 FLEX / 8 bench.

---

## Model Performance (Walk-Forward Validation, 2015–2025)

| Position | R²    | RMSE  |
|----------|-------|-------|
| QB       | 0.539 | 78.68 |
| RB       | 0.543 | 62.10 |
| WR       | 0.585 | 54.87 |
| TE       | 0.591 | 39.25 |

Models are tuned with Optuna (100 trials, Bayesian) and trained on all historical data for final 2026 projections.

---

## Module Status

### Complete

| Module | File | Notes |
|--------|------|-------|
| Data scraper | `src/data/scraper.py` | Pulls raw nflreadpy parquet files |
| Data pipeline | `src/data/pipeline.py` | Cleans, merges, derives age, computes team stats |
| Feature engineering | `src/features/build_features.py` | Per-game stats, EPA, surge, delta, lag (leakage-free) |
| Model training | `src/models/train.py` | Position-specific LightGBM + Optuna tuning |
| Projections | `src/models/predict.py` | Generates `*_predictions.parquet` for 2026 |
| VOR pipeline | `src/draft/vor.py` | Computes VOR, ceiling/floor, value gap, tiers |
| Roster tracking | `src/draft/roster.py` | `Roster` class: starter/flex/bench needs |
| Draft state | `src/draft/draft_state.py` | `DraftState`: snake order, 12-team rosters, player pool |
| Recommender | `src/draft/recommender.py` | Position + player scoring (scarcity, VOR, value gap, risk) |
| Draft advisor CLI | `src/draft/advisor.py` | Interactive draft loop entry point |
| Test suite | `tests/` | 53 tests, all passing — see below |

### Dead Weight (not wired into real pipeline)

| File | Status |
|------|--------|
| `src/draft/vbd.py` | Old scaffold `ValueBasedDrafter` class — unused, keep for reference |
| `src/draft/simulator.py` | Old scaffold `DraftSimulator` — unused, keep for reference |
| `src/app/cli.py` | Old Click CLI scaffold — imports stubs that don't match real modules |

`src/draft/__init__.py` was importing `DraftRecommender` from the old scaffold (broken import); cleaned up to a single docstring.

---

## Test Coverage

53 unit tests across 4 files — no disk I/O required (parquet reads mocked).

| File | Tests | What's covered |
|------|-------|---------------|
| `tests/test_vor.py` | 13 | `normalize_names`, `compute_vor`, `compute_ceiling_floor`, `compute_value_gap`, `compute_tiers` |
| `tests/test_roster.py` | 12 | `Roster` init, `add_player`, `get_needs` (FLEX logic, bench tracking), `get_picks` |
| `tests/test_recommender.py` | 15 | `normalize_col`, `get_pick_gap`, `calculate_risk_penalty`, `player_select`, `pos_select` |
| `tests/test_draft_state.py` | 10 | `get_current_pick` (snake math), `draft_player` (all code paths) |

Run with: `pytest tests/ -v`

---

## Known Limitations

**Injury distortion**: Players with fewer than ~13 games show suppressed raw totals. `compute_ceiling_floor` scales their ceiling upward (availability_flag), but raw PPR and game count still penalise them by design. Draft logic can flag these players; projections themselves are intentionally conservative.

**Veteran QB pedigree**: `draft_number` is the 5th most important QB feature and never decays. Former top picks get a permanent boost. Ablation confirmed it's net positive for QB R² (+0.046), so accepted.

**Situation changes**: The model's biggest misses are players whose team/role changed between seasons (Darnold +220, Barkley +172, Chase Brown +186). Individual player features can't capture this. No fix planned at model layer — see Future Work.

**nflverse early-season NaN**: `target_share`/`air_yards_share`/`wopr` are unreliable before ~2018. LightGBM handles NaN natively; no action needed.

---

## Future Work

### High Priority
- **Team context features** (addresses situation-change residuals):
  - Target/rush/snap rank within team (depth chart proxy)
  - QB quality mapped onto receivers (lagged EPA/play merged by team+season)
  - Team pass rate and pace (pass%, plays/game, points/game)
  - Rule: all must be lagged; no same-season team totals
- **Injury handling in draft logic**: blend projections toward career average for players flagged with fewer than X games in most recent season

### Deferred
- Team clustering (KMeans on pace/efficiency) — signal likely captured by aggregates
- Vegas implied points — powerful but external data dependency
- V2 draft advisor improvements: z-score value gap, archetype RMSE splits, regret metric, bulk draft input
- Reconcile / replace `src/app/cli.py` with a real CLI wired to actual modules
