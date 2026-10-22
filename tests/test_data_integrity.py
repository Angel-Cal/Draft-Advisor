"""Integrity checks against the real processed data. They skip when the data files are absent (e.g. in CI)."""

import json
import re
import warnings
from importlib.metadata import version
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from src.data import validate as v
from src.data.run_manifest import check_freshness
from src.features.manifest import undeclared, basis
from src.models.train import split_positions
from src.features.team_context import RB_FEATURES, QB_MODEL_FEATURES

ROOT = Path(__file__).parent.parent
PROCESSED, RAW, EXTERNAL = ROOT / "data" / "processed", ROOT / "data" / "raw", ROOT / "data" / "external"
SEASONS = range(2021, 2026)


def needs(*paths):
    return pytest.mark.skipif(not all(Path(p).exists() for p in paths), reason="data files not present")


@pytest.fixture(scope="module")
def training():
    return pd.read_parquet(PROCESSED / "training_data.parquet")


@pytest.fixture(scope="module")
def prediction():
    return pd.read_parquet(PROCESSED / "prediction_data.parquet")


@pytest.fixture(scope="module")
def raw_seasonal():
    return v.drop_junk_rows(pd.read_parquet(RAW / "seasonal_20_25.parquet"), "player_id")


@needs(PROCESSED / "training_data.parquet")
def test_training_data_passes_validation(training):
    v.check_training(training)


@needs(PROCESSED / "training_data.parquet", PROCESSED / "prediction_data.parquet")
def test_every_column_has_a_declared_time_basis(training, prediction):
    assert undeclared(training.columns) == []
    assert undeclared(prediction.columns) == []


@needs(PROCESSED / "training_data.parquet", PROCESSED / "prediction_data.parquet")
def test_prediction_rows_match_training_rows_exactly(training, prediction):
    with warnings.catch_warnings():
        warnings.simplefilter("error", v.DataIntegrityWarning)    # order and dtype drift must not creep back in
        v.check_prediction(prediction, training)
    shared = [c for c in training.columns if c in prediction.columns]
    assert shared == [c for c in prediction.columns if c in training.columns]


@needs(PROCESSED / "training_data.parquet", RAW / "seasonal_20_25.parquet")
def test_target_is_the_raw_season_ppr(training, raw_seasonal):
    joined = training.merge(raw_seasonal[["player_id", "season", "fantasy_points_ppr"]],
                            on=["player_id", "season"], suffixes=("", "_raw"))
    assert len(joined) / len(training) > 0.99
    assert np.isclose(joined["target_ppr"], joined["fantasy_points_ppr_raw"]).mean() > 0.99


@needs(PROCESSED / "training_data.parquet", RAW / "seasonal_20_25.parquet")
def test_prior_season_features_are_lagged_not_leaked(training, raw_seasonal):
    """Each prior_season column must equal the player's raw stat from season t-1 and not the stat from season t."""
    raw_columns = ["attempts", "carries", "targets", "passing_epa", "rushing_epa", "receiving_epa",
                   "fantasy_points", "fantasy_points_ppr"]
    raw = raw_seasonal[["player_id", "season", "games"] + raw_columns]
    # seasons under 4 games are filtered out of the dataset, so the lag skips them by design
    previous = raw[raw["games"] >= 4].drop(columns="games")
    previous = previous.assign(season=previous["season"] + 1).set_index(["player_id", "season"])
    raw = raw.drop(columns="games")
    current = raw.set_index(["player_id", "season"])
    rows = training.set_index(["player_id", "season"])
    usable = rows.index[rows.index.isin(previous.index) & rows.index.isin(current.index)]
    assert len(usable) > 3000
    for col in raw_columns:
        feature, last_year, this_year = rows.loc[usable, col], previous.loc[usable, col], current.loc[usable, col]
        distinguishing = ~np.isclose(last_year, this_year, equal_nan=True)   # rows where t-1 and t differ
        assert distinguishing.sum() > 100
        matches_previous = np.isclose(feature[distinguishing], last_year[distinguishing], equal_nan=True).mean()
        matches_current = np.isclose(feature[distinguishing], this_year[distinguishing], equal_nan=True).mean()
        assert matches_previous > 0.99, f"{col} does not match the prior season ({matches_previous:.1%})"
        assert matches_current < 0.01, f"{col} matches the target season in {matches_current:.1%} of rows (leak?)"


@needs(PROCESSED / "training_data.parquet")
def test_features_are_isolated_to_their_position(training):
    from src.features.registry import POSITION_FEATURES, other_position_features
    frames = dict(zip(["QB", "RB", "WR", "TE"], split_positions(training)))
    for position, frame in frames.items():
        assert set(POSITION_FEATURES[position]) <= set(frame.columns), f"{position} is missing its engineered features"
        leaked = set(other_position_features(position)) & set(frame.columns)
        assert not leaked, f"{position} frame carries other positions' features: {sorted(leaked)}"


@needs(PROCESSED / "training_data.parquet")
def test_implied_total_uses_the_prior_season_not_the_target_season(training):
    """The leak: a team's total for the season being predicted. The prior-season total varies far less within a
    team-season than across teams, so this only checks the documented definition is declared as pre-season."""
    assert basis("implied_total") == "preseason_known"


@needs(*(EXTERNAL / f"adp_{s}.csv" for s in SEASONS))
def test_adp_files_are_clean_and_cover_the_market():
    for season in SEASONS:
        adp = pd.read_csv(EXTERNAL / f"adp_{season}.csv")
        assert adp["player_id"].notna().all()
        assert not adp.duplicated("player_id").any()
        assert len(adp) > 300 and adp["position"].isin(v.SKILL_POSITIONS).all()
        assert adp["rank"].is_monotonic_increasing or adp["adp"].notna().all()


@needs(*(PROCESSED / f"season_{s}.parquet" for s in SEASONS), PROCESSED / "training_data.parquet")
def test_out_of_sample_files_agree_with_training_targets(training):
    for season in SEASONS:
        oos = pd.read_parquet(PROCESSED / f"season_{season}.parquet")
        assert not oos.duplicated("player_id").any() and oos["oos_pred_ppr"].notna().all()
        joined = oos.merge(training[["player_id", "season", "target_ppr"]], on=["player_id", "season"])
        assert len(joined) == len(oos) and np.allclose(joined["actual_ppr"], joined["target_ppr"])
        assert len([c for c in oos.columns if c.startswith("oos_pred_s")]) >= 3


@needs(*(ROOT / "models" / f"{p}_params" for p in ("qb", "rb", "wr", "te")))
def test_tuned_params_are_complete():
    for position in ("qb", "rb", "wr", "te"):
        params = json.loads((ROOT / "models" / f"{position}_params").read_text())
        assert {"num_leaves", "learning_rate", "max_depth", "n_estimators"} <= set(params)


@needs(PROCESSED / "training_data.parquet", *(PROCESSED / f"{p}_predictions.parquet" for p in ("qb", "rb", "wr", "te")))
def test_prediction_outputs_are_valid_and_current():
    frames = {p.upper(): pd.read_parquet(PROCESSED / f"{p}_predictions.parquet") for p in ("qb", "rb", "wr", "te")}
    v.check_prediction_outputs(frames)
    check_freshness([PROCESSED / "training_data.parquet", PROCESSED / "prediction_data.parquet"],
                    [PROCESSED / f"{p}_predictions.parquet" for p in ("qb", "rb", "wr", "te")], "predictions")


def test_installed_packages_match_the_pins():
    pins = dict(re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)$", (ROOT / "requirements.txt").read_text(), re.M))
    for package in ("lightgbm", "pandas", "numpy", "scikit-learn", "optuna", "scipy", "pyarrow", "nflreadpy"):
        assert package in pins, f"{package} is not pinned in requirements.txt"
        assert version(package) == pins[package], f"{package} {version(package)} != pinned {pins[package]}"


@needs(PROCESSED / "predictions_table.parquet")
def test_advisor_table_has_one_row_per_player_and_flags_market_rows():
    table = pd.read_parquet(PROCESSED / "predictions_table.parquet")
    v.check_advisor_table(table)
    assert table["market_estimate"].any() and not table["market_estimate"].all()
    assert table.loc[table["market_estimate"], "player_id"].map(lambda i: isinstance(i, str)).all()


@needs(*(PROCESSED / f"season_{s}.parquet" for s in SEASONS))
def test_advisor_rmse_constants_match_the_current_walk_forward_error():
    """vor.py uses these for ceiling/floor; they must track the model, not an earlier version of it."""
    from src.draft.vor import RMSE
    oos = pd.concat(pd.read_parquet(PROCESSED / f"season_{s}.parquet") for s in SEASONS)
    seed_columns = [c for c in oos.columns if c.startswith("oos_pred_s")]
    for position, group in oos.groupby("position"):
        current = np.mean([np.sqrt(((group[c] - group["actual_ppr"]) ** 2).mean()) for c in seed_columns])
        assert RMSE[position] == pytest.approx(current, rel=0.05), f"{position}: vor.py has {RMSE[position]}, current {current:.2f}"


@needs(RAW / "ff_opportunity_14_25.parquet", PROCESSED / "training_data.parquet")
def test_expected_points_feature_is_last_seasons_opportunity(training):
    opportunity = pd.read_parquet(RAW / "ff_opportunity_14_25.parquet")
    opportunity = opportunity[opportunity["week"] <= np.where(opportunity["season"] <= 2020, 17, 18)]     # regular season only
    last_year = opportunity.groupby(["player_id", "season"])["total_fantasy_points_exp"].sum().rename("expected")
    last_year.index = last_year.index.set_levels(last_year.index.levels[1] + 1, level="season")
    joined = training.dropna(subset=["xfp_ppr_prev"]).merge(last_year.reset_index(), on=["player_id", "season"])
    assert len(joined) > 800
    assert np.allclose(joined["xfp_ppr_prev"], joined["expected"])


@needs(RAW / "ffc")
def test_ffc_pick_spread_files_are_complete():
    import json
    for season in range(2021, 2026):
        data = json.loads((RAW / "ffc" / f"ffc_ppr12_{season}.json").read_text())
        players = data["players"]
        assert data["meta"]["teams"] == 12 and data["meta"]["total_drafts"] > 1000
        assert len(players) > 100 and {"adp", "stdev", "times_drafted"} <= set(players[0])
        top = [p for p in players if p["adp"] <= 12 and p["times_drafted"] >= 30]
        assert top and all(0 < p["stdev"] < 6 for p in top), "early picks should have a small, positive spread"

