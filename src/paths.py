"""Folder layout of data/processed: live contract files, pipeline intermediates and experiment outputs.

live/         projections_<season>_v1.json and run_manifest.json (what the C# side reads)
pipeline/     training/prediction data, per-position predictions, advisor tables, adp_table.csv; oos/ holds season_<year>.parquet
experiments/  ablations/ (result tables), oos/ (experiment OOS predictions), sims/ (simulator logs and sweeps),
              worlds/ (backtest projection sets for `backtest --data`), short_season/, scoring/ (graded frozen files)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
LIVE = PROCESSED / "live"
PIPELINE = PROCESSED / "pipeline"
OOS = PIPELINE / "oos"
EXPERIMENTS = PROCESSED / "experiments"
ABLATIONS = EXPERIMENTS / "ablations"
EXPERIMENT_OOS = EXPERIMENTS / "oos"
SIMS = EXPERIMENTS / "sims"
WORLDS = EXPERIMENTS / "worlds"
SHORT_SEASON = EXPERIMENTS / "short_season"
SCORING = EXPERIMENTS / "scoring"

for _folder in (LIVE, OOS, ABLATIONS, EXPERIMENT_OOS, SIMS, WORLDS, SHORT_SEASON, SCORING):
    _folder.mkdir(parents=True, exist_ok=True)      # data/processed is gitignored, so a fresh clone has none of these
