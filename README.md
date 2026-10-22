# Fantasy Football Draft Advisor

An ML-powered fantasy football draft assistant. Python models project player points; a C# core turns those
projections into draft recommendations (points over replacement, roster need, position-specific bench value, and an
ADP-reach cost) and a simulator measures them against ADP-following opponents with real results.

## Project Status

- **Projection models**: Complete — position-specific LightGBM models trained on
  NFL data from 2015-2025
- **Prediction pipeline**: Complete — generates 2026 season projections for all
  active players
- **Draft recommender (C#)**: Working in the simulator: the `need` recommender is +48 starter points over plain ADP
  (weekly lineups, calibrated opponents, 2021-2025 backtests). Interactive mock drafts run on past seasons.
- **Desktop app / live draft sync**: Not started (roadmap Phase 5)

The projections do not beat ADP at ranking players; the edge comes from how the recommender uses them. See
`.claude/STATUS.md` (current state and hand-off), `.claude/LOG.md` (why each choice was made) and `.claude/ROADMAP.md`.

## Model Performance (Walk-Forward Validation, test seasons 2021-2025)

| Position | Mean per-season R² | RMSE (5-seed mean) | Top-150 Spearman: model | Top-150 Spearman: ADP |
|----------|--------------------|--------------------|-------------------------|-----------------------|
| QB       | 0.47               | 84.28              | 0.305                   | 0.401                 |
| RB       | 0.59               | 58.86              | 0.532                   | 0.589                 |
| WR       | 0.61               | 53.48              | 0.511                   | 0.569                 |
| TE       | 0.60               | 38.69              | 0.406                   | 0.418                 |

An earlier version of this table reported higher R² from a leaked feature (see `.claude/STATUS.md`, Data Integrity).

## How It Works

### 1. Data Pipeline (`src/data/`)

- Pulls historical NFL data (2015-2025) via nflreadpy: seasonal stats, play-by-play,
  rosters, snap counts, player IDs
- Cleans and merges datasets, derives age from birth date
- Computes Vegas implied team totals (from schedule spread/total lines) as offensive
  context features; recomputes target share and air yards share as per-game rates

### 2. Feature Engineering (`src/features/build_features.py`)

- Per-game volume stats (passing, rushing, receiving)
- EPA and efficiency metrics (passing_cpoe, pacr, racr, wopr)
- Air yards and yards after catch per game
- Surge features: late-season target share and snap share trajectories
- Year-over-year delta features to capture player trajectory
- All features are lagged by one season to prevent data leakage

### 3. Projection Models (`src/models/`)

- Separate LightGBM models per position (QB, RB, WR, TE)
- Irrelevant features dropped per position (e.g. passing stats for WRs)
- Walk-forward validation across 10 folds (2015-2025)
- Hyperparameters tuned with Optuna (100 trials, Bayesian optimization)
  using walk-forward RMSE as the objective
- Final models trained on all historical data (2015-2025) for 2026 projections

### 4. Draft Recommender (`csharp/`)

- One score across all positions: points over replacement (greedy FLEX-adjusted replacement levels from the league settings), measured as
  the gain to your best lineup so redundant players are worth nothing
- Position-specific bench value: the k-th backup at a position is worth the chance enough starters are out the same week, times his upside
  over a free agent; a third QB or TE is never recommended
- ADP-reach cost that grows with the draft position (ADP is less predictive later); ADP: Underdog CSV via 4for4 (live), FantasyPros (backtests)
- Ceiling/floor bands from position-level walk-forward RMSE; per-position tiers by value dropoff
- A simulator drafts against ADP-plus-noise opponents calibrated to real mock drafts and scores rosters by weekly lineups with actual results
- Not yet built: tier-cliff cost of waiting, position safety, run detection, plain-language reasoning (roadmap Phase 4)
- The earlier Python advisor in `src/draft/` is superseded by the C# core

## Project Structure

```
DraftBot/
├── data/
│   ├── raw/                  # nflreadpy parquet files
│   └── processed/            # Processed training data and projections
├── models/                   # Saved tuned hyperparameters (JSON per position)
├── notebooks/                # Exploratory data analysis
├── src/
│   ├── data/
│   │   ├── scraper.py        # Pulls and saves raw data via nflreadpy
│   │   ├── pipeline.py       # Cleans, merges, and saves processed data
│   │   ├── validate.py       # Data-integrity checks that stop a run on silent problems
│   │   ├── adp_scraper.py    # Historical ADP (FantasyPros via the Wayback Machine)
│   │   ├── ffc_scraper.py    # Real pick-spread data (FFC mock drafts) for simulator calibration
│   │   └── export_projections.py  # projections_<season>_v1.json for the C# side
│   ├── features/
│   │   └── build_features.py # Feature engineering and prediction features
│   ├── models/
│   │   ├── train.py          # Model training, walk-forward validation, Optuna tuning
│   │   └── predict.py        # Generates 2026 projections from trained models
│   └── draft/
│       ├── vor.py            # VOR calculation, ceiling/floor, tiers, ADP integration
│       ├── roster.py         # Per-team roster needs and flex/bench tracking
│       ├── draft_state.py    # Snake draft order and 12-team player pool
│       ├── recommender.py    # Position + player scoring and recommendation (superseded by csharp/)
│       └── advisor.py        # Interactive CLI draft assistant (superseded by csharp/)
├── csharp/                   # DraftBot.Core (draft logic), DraftBot.Sim (simulator + CLI), DraftBot.Tests (xUnit)
├── .claude/                  # STATUS.md (hand-off), LOG.md (decision log), ROADMAP.md, projection schema
├── plan.txt                  # Draft advisor design spec
├── requirements.txt
└── README.md
```

## Installation

```bash
git clone https://github.com/Angel-Cal/Draft-Bot.git
cd DraftBot

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

## Running the Pipeline

```bash
# 1. Pull raw data
python src/data/scraper.py

# 2. Process data and build features
python src/data/pipeline.py

# 3. Tune hyperparameters and train models (writes output to output.log)
python src/models/train.py

# 4. Generate 2026 projections
python src/models/predict.py

# 5. Build the draft advisor's player table (adds ADP-derived projections for rookies/unmodeled players)
python src/draft/vor.py

# 6. Export the projection files the C# side reads (live season + 2021-2025 backtests)
python src/data/export_projections.py
```

## C# Core and Simulator (`csharp/`)

The draft-time logic (league settings, replacement level, VOR, tiers, draft state, recommender) and the draft simulator
live in .NET 9. They read only the exported `projections_<season>_v1.json` files (contract:
`.claude/projection_schema_v1.md`).

```bash
cd csharp
dotnet test                                                         # unit tests
dotnet run -c Release --project src/DraftBot.Sim -- backtest        # ADP / VOR / recommender baselines + regret per round
dotnet run --project src/DraftBot.Sim -- draft --season 2024 --slot 6   # interactive mock draft with the recommender's reasoning (--window true adds the reach control, --recommender value|need uses the single-score recommender; need adds roster need and position-specific bench value)
dotnet run --project src/DraftBot.Sim -- tune-reach                 # sweep the recommender's ADP-reach penalty and cap
dotnet run --project src/DraftBot.Sim -- tune-value                 # lambda sweep for the single-score recommender
dotnet run --project src/DraftBot.Sim -- tune-bench                 # bench value: flat fractions vs the structural k-th-backup rule (weekly lineup scoring)
dotnet run --project src/DraftBot.Sim -- tune-need                  # roster-need sweep (bench fraction x lambda; --unrestricted true lifts the sim's roster rules)
dotnet run --project src/DraftBot.Sim -- calibrate-noise            # compare simulated opponents' pick spread with real mock drafts (needs python src/data/ffc_scraper.py)
dotnet run --project src/DraftBot.Sim -- diagnose --season 2025     # why one strategy trails another in a season (players, positions)
dotnet run --project src/DraftBot.Sim -- decompose                  # recommender split into position rule vs player rule
dotnet run --project src/DraftBot.Sim -- tune-tiers                 # tier threshold sweep (leave-one-season-out)
dotnet run --project src/DraftBot.Sim -- describe                   # replacement levels and tiers of the live file
```

## League Settings

- 12-team snake draft
- PPR scoring
- Roster: 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX (RB/WR/TE)
- DST/K not modeled

## Testing

```bash
pytest tests/ -v
```

Unit tests cover all pure functions in the draft advisor (VOR calculation,
need scoring, run detection, position safety, tier detection).

## Data Integrity Guardrails

Silent data bugs (dropped rows, leaked features, stale prediction inputs) have been the main source of wrong
results, so the pipeline checks itself:

- **`src/data/validate.py`** runs inside `pipeline.py` and `predict.py`. Errors stop the run (null/duplicate keys,
  unknown team codes, a season losing rows in a merge, out-of-range values, prediction rows that differ from
  training rows or carry last season's age); soft problems (feature drift, column order) warn.
- **`src/features/manifest.py`** classifies every training column as `prior_season` or `preseason_known`. A new
  column that is not declared there fails `tests/test_data_integrity.py`.
- **`tests/test_data_integrity.py`** recomputes lagged features from the raw files and fails if any column matches
  the target season; it also checks train/serve parity, ADP coverage, out-of-sample files and pinned packages.
  It skips when `data/` is absent (CI).
- **`data/processed/run_manifest.json`** records the commit, timestamp, row counts and params checksums of each
  pipeline, predict and benchmark run. Stale outputs (older than their inputs) raise or warn.
- **Benchmark standard** (`src/evaluation/benchmark.py`): per-position only, scores averaged over 5 model seeds
  with their spread, and always shown next to the "last year's PPR" baseline.
- **Automation:** `.githooks/pre-commit` runs the tests before each commit (`git config core.hooksPath .githooks`),
  and `.github/workflows/tests.yml` runs them on push.

---

Built as a machine learning portfolio project demonstrating:

- End-to-end data engineering with real sports data
- Feature engineering with leakage prevention for time-series prediction
- Position-specific LightGBM models with walk-forward validation
- Bayesian hyperparameter optimization with Optuna
- Sequential decision-making under uncertainty (draft advisor)
