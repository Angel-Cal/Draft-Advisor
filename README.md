# Fantasy Football Draft Advisor

An ML-powered fantasy football draft assistant that predicts player performance
and provides real-time draft recommendations based on value-based drafting,
positional scarcity, opponent roster tracking, and draft run detection.

## Project Status

- **Projection models**: Complete — position-specific LightGBM models trained on
  NFL data from 2015-2025
- **Prediction pipeline**: Complete — generates 2026 season projections for all
  active players
- **Draft advisor**: In development

## Model Performance (Walk-Forward Validation, 2015-2025)

| Position | R²    | RMSE  |
|----------|-------|-------|
| QB       | 0.539 | 78.68 |
| RB       | 0.543 | 62.10 |
| WR       | 0.585 | 54.87 |
| TE       | 0.591 | 39.25 |

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

### 4. Draft Advisor (`src/draft/`) — In Development

- Value Over Replacement (VOR) with FLEX-adjusted replacement levels
- ADP integration: Underdog ADP CSV (via 4for4)
- Ceiling/floor bands derived from position-level walk-forward RMSE
- Adaptive risk profiling by round and roster composition
- Positional run detection (continuous intensity, not boolean)
- Opponent roster tracking across all 12 teams
- Probabilistic position safety estimation
- VOR tier detection with crossing-penalty
- Additive weighted scoring model for final recommendations

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
│   │   └── pipeline.py       # Cleans, merges, and saves processed data
│   ├── features/
│   │   └── build_features.py # Feature engineering and prediction features
│   ├── models/
│   │   ├── train.py          # Model training, walk-forward validation, Optuna tuning
│   │   └── predict.py        # Generates 2026 projections from trained models
│   └── draft/
│       ├── vor.py            # VOR calculation, ceiling/floor, tiers, ADP integration
│       ├── roster.py         # Per-team roster needs and flex/bench tracking
│       ├── draft_state.py    # Snake draft order and 12-team player pool
│       ├── recommender.py    # Position + player scoring and recommendation
│       └── advisor.py        # Interactive CLI draft assistant
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

---

Built as a machine learning portfolio project demonstrating:

- End-to-end data engineering with real sports data
- Feature engineering with leakage prevention for time-series prediction
- Position-specific LightGBM models with walk-forward validation
- Bayesian hyperparameter optimization with Optuna
- Sequential decision-making under uncertainty (draft advisor)
