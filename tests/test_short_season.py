import numpy as np
import pandas as pd

from src.models.short_season import SHORT_SEASON_GAMES, rate_refit, route, routed_refit, to_rates
from src.models.train import Model

PARAMS = {"n_estimators": 100, "learning_rate": 0.1, "num_leaves": 4, "min_child_samples": 5, "verbosity": -1,
          "n_jobs": 1, "random_state": 42}


def frame(games, ppr=(100.0, 100.0)):
    return pd.DataFrame({"games": games, "games_delta": [-2, 0], "fantasy_points_ppr": list(ppr), "fantasy_points": [90.0, 90.0],
                         "attempts": [400, 400], "passing_epa": [20.0, 20.0], "attempts_pg": [25.0, 25.0], "age": [27, 27]})


def test_to_rates_replaces_totals_with_per_game_values_and_drops_availability():
    out = to_rates(frame([8, 16]))

    assert list(out["ppg_prev"]) == [12.5, 6.25]
    assert list(out["passing_epa_pg"]) == [2.5, 1.25]
    assert {"games", "games_delta", "fantasy_points_ppr", "fantasy_points", "attempts", "passing_epa"}.isdisjoint(out.columns)
    assert {"attempts_pg", "age"} <= set(out.columns)


def test_to_rates_drops_the_qb_attempt_share_because_the_backup_takes_it_when_a_starter_is_hurt():
    out = to_rates(frame([8, 16]).assign(qb_att_share_prev=[0.4, 0.9]))

    assert "qb_att_share_prev" not in out.columns


def test_to_rates_leaves_the_input_untouched_and_survives_zero_games():
    x = frame([0, 16])
    out = to_rates(x)

    assert "games" in x.columns
    assert np.isnan(out["ppg_prev"].iloc[0]) and out["ppg_prev"].iloc[1] == 6.25


def test_to_rates_skips_columns_a_position_does_not_have():
    out = to_rates(frame([8, 16]).drop(columns=["passing_epa", "attempts"]))

    assert "passing_epa_pg" not in out.columns and "ppg_prev" in out.columns


def test_route_takes_the_rate_projection_only_up_to_the_cutoff():
    games = [SHORT_SEASON_GAMES, SHORT_SEASON_GAMES + 1, 4]

    assert list(route(np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0]), games)) == [10.0, 2.0, 30.0]


def test_routed_refit_changes_only_the_short_season_rows():
    rng = np.random.default_rng(0)

    def make(n):
        games = rng.integers(4, 18, n)
        ppg = rng.normal(15, 4, n)
        x = pd.DataFrame({"games": games, "games_delta": 0, "fantasy_points_ppr": ppg * games, "age": rng.integers(22, 34, n)})
        return x, pd.Series(ppg * 15 + rng.normal(0, 10, n))

    (x_train, y_train), (x_val, y_val), (x_pred, _) = make(300), make(80), make(60)
    model = Model()

    base = model.refit_predict(x_train, y_train, x_val, y_val, x_pred, PARAMS, seeds=range(2))
    rates = rate_refit(model, x_train, y_train, x_val, y_val, x_pred, PARAMS)
    routed = routed_refit(model, x_train, y_train, x_val, y_val, x_pred, PARAMS)
    short = (x_pred["games"] <= SHORT_SEASON_GAMES).to_numpy()

    assert short.any() and not short.all()
    assert routed.shape == (60,)
    assert np.allclose(routed[~short], model.refit_predict(x_train, y_train, x_val, y_val, x_pred, PARAMS)[~short])
    assert not np.allclose(routed[short], model.refit_predict(x_train, y_train, x_val, y_val, x_pred, PARAMS)[short])
    assert base.shape == rates.shape == (60,)


def test_routed_refit_is_the_base_model_when_nobody_had_a_short_season():
    rng = np.random.default_rng(1)
    x = pd.DataFrame({"games": rng.integers(12, 18, 120), "games_delta": 0, "fantasy_points_ppr": rng.normal(200, 40, 120), "age": 27})
    y = x["fantasy_points_ppr"] + rng.normal(0, 10, 120)
    model = Model()

    assert np.allclose(routed_refit(model, x[:80], y[:80], x[80:], y[80:], x[80:], PARAMS),
                       model.refit_predict(x[:80], y[:80], x[80:], y[80:], x[80:], PARAMS))
