import warnings
import numpy as np
import pandas as pd
import pytest
from src.data import validate as v
from src.data.run_manifest import check_freshness
from src.features.manifest import undeclared


def seasonal_rows(**overrides):
    rows = pd.DataFrame({"player_id": ["a", "b", "c"], "season": 2020, "games": [16, 10, 4],
                         "recent_team": ["KC", "OAK", "SD"]})
    return rows.assign(**overrides)


def training_frame(seasons=range(2015, 2018), per_season=260):
    n = len(list(seasons)) * per_season
    return pd.DataFrame({
        "player_id": [f"p{i}" for i in range(n)], "season": np.repeat(list(seasons), per_season),
        "position": "WR", "target_ppr": 100.0, "implied_total": 22.0, "age": 25.0, "draft_number": 50.0,
        "games": 15.0, "target_share": 0.05 + 0.01 * (np.arange(n) % 10), "wopr": 0.3})


# ---- raw data -------------------------------------------------------------------------------------------------

def test_drop_junk_rows_removes_null_ids():
    df = pd.DataFrame({"player_id": ["a", None], "games": [16, 272]})
    assert list(v.drop_junk_rows(df, "player_id")["player_id"]) == ["a"]


def test_raw_seasonal_accepts_clean_data_with_legacy_team_codes():
    v.check_raw_seasonal(seasonal_rows())          # OAK and SD are mapped to current codes


def test_raw_seasonal_rejects_junk_duplicates_and_bad_games():
    with pytest.raises(v.DataIntegrityError, match="null player_id"):
        v.check_raw_seasonal(seasonal_rows(player_id=["a", None, "c"]))
    with pytest.raises(v.DataIntegrityError, match="duplicate"):
        v.check_raw_seasonal(seasonal_rows(player_id=["a", "a", "c"]))
    with pytest.raises(v.DataIntegrityError, match="games outside"):
        v.check_raw_seasonal(seasonal_rows(games=[16, 10, 272]))


def test_raw_seasonal_rejects_unknown_team():
    with pytest.raises(v.DataIntegrityError, match="unknown team"):
        v.check_raw_seasonal(seasonal_rows(recent_team=["KC", "XXX", "SD"]))


def test_raw_roster_rejects_null_ids_and_warns_on_duplicates():
    roster = pd.DataFrame({"gsis_id": ["a", "a"], "season": 2020, "week": 1, "team": ["KC", "KC"]})
    with pytest.warns(v.DataIntegrityWarning, match="duplicate"):
        v.check_raw_roster(roster)
    with pytest.raises(v.DataIntegrityError, match="null gsis_id"):
        v.check_raw_roster(roster.assign(gsis_id=["a", None]))


# ---- merges ---------------------------------------------------------------------------------------------------

def test_retention_flags_a_season_that_loses_rows():
    expected = pd.Series({2015: 100, 2016: 100})
    v.check_retention(expected, pd.Series({2015: 99, 2016: 98}), "merge")
    with pytest.raises(v.DataIntegrityError, match="season 2016"):
        v.check_retention(expected, pd.Series({2015: 100, 2016: 80}), "merge")


def test_no_row_loss():
    v.check_no_row_loss(10, 10, "merge")
    with pytest.raises(v.DataIntegrityError, match="2 of 10"):
        v.check_no_row_loss(10, 8, "merge")


# ---- training data --------------------------------------------------------------------------------------------

def test_training_accepts_a_valid_frame():
    v.check_training(training_frame())


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.assign(player_id="dup"), "duplicate"),
    (lambda d: d.assign(implied_total=np.where(d.index == 0, np.nan, 22.0)), "nulls in implied_total"),
    (lambda d: d.assign(games=np.where(d.index == 0, 272, 15)), "games outside"),
    (lambda d: d.assign(target_share=np.where(d.index == 0, 0.9 / 0.05, 0.1)), "target_share outside"),
    (lambda d: d.assign(position="K"), "unexpected positions"),
    (lambda d: d[d.season != 2016], "missing seasons"),
    (lambda d: d[~((d.season == 2016) & (d.index % 2 == 0))], "fewer than"),
])
def test_training_rejects_each_problem(mutate, message):
    with pytest.raises(v.DataIntegrityError, match=message):
        v.check_training(mutate(training_frame()))


# ---- prediction rows ------------------------------------------------------------------------------------------

def prediction_frame(train):
    last = train.groupby("player_id").tail(1)
    return last.drop(columns=["target_ppr"]).assign(age=last["age"] + 1, season=last["season"] + 1, injury_flag=False).reset_index(drop=True)


def test_prediction_accepts_matching_frame():
    train = training_frame()
    v.check_prediction(prediction_frame(train), train)


def test_prediction_rejects_column_mismatch_and_stale_age():
    train = training_frame()
    pred = prediction_frame(train)
    with pytest.raises(v.DataIntegrityError, match="column mismatch"):
        v.check_prediction(pred.drop(columns=["wopr"]), train)
    with pytest.raises(v.DataIntegrityError, match="age advanced"):
        v.check_prediction(pred.assign(age=train.groupby("player_id").tail(1)["age"].values), train)


def test_prediction_warns_on_order_dtype_and_drift():
    train = training_frame()
    pred = prediction_frame(train)
    reordered = pred[["wopr"] + [c for c in pred.columns if c != "wopr"]].astype({"games": "int64"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        v.check_prediction(reordered.assign(target_share=5.0), train)
    messages = " ".join(str(w.message) for w in caught)
    assert "column order" in messages and "dtype" in messages and "drift" in messages


def test_prediction_outputs():
    good = pd.DataFrame({"player_id": ["a", "b"], "projected_ppr": [200.0, 150.0]})
    v.check_prediction_outputs({"QB": good})
    for bad in [good.assign(player_id="a"), good.assign(projected_ppr=[np.nan, 1.0]),
                good.assign(projected_ppr=[900.0, 1.0]), good.iloc[0:0]]:
        with pytest.raises(v.DataIntegrityError):
            v.check_prediction_outputs({"QB": bad})


def test_adp_matches():
    adp = pd.DataFrame({"season": 2021, "name": ["x", "y"], "rank": [5, 400], "player_id": ["a", None]})
    v.check_adp_matches(adp)                                  # unmatched player is outside the top 200
    with pytest.raises(v.DataIntegrityError, match="no player_id"):
        v.check_adp_matches(adp.assign(rank=[5, 50]))
    with pytest.raises(v.DataIntegrityError, match="duplicate"):
        v.check_adp_matches(adp.assign(player_id=["a", "a"]))


# ---- freshness and feature manifest ---------------------------------------------------------------------------

def test_freshness(tmp_path):
    source, output = tmp_path / "in.parquet", tmp_path / "out.parquet"
    output.write_text("old"); source.write_text("new")
    import os
    os.utime(output, (1_000, 1_000)); os.utime(source, (2_000, 2_000))
    with pytest.raises(v.DataIntegrityError, match="older than their inputs"):
        check_freshness([source], [output], "test")
    with pytest.warns(v.DataIntegrityWarning):
        check_freshness([source], [output], "test", strict=False)
    os.utime(output, (3_000, 3_000))
    check_freshness([source], [output], "test")


def test_manifest_flags_unclassified_columns():
    assert undeclared(["player_id", "target_ppr", "fantasy_points_ppr", "age", "completions_pg_delta"]) == []
    assert undeclared(["fantasy_points_ppr", "brand_new_feature"]) == ["brand_new_feature"]
