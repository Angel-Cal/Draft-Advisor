import numpy as np
import pandas as pd

from src.models.train import Model

PARAMS = {"n_estimators": 300, "learning_rate": 0.1, "num_leaves": 8, "min_child_samples": 5, "verbosity": -1,
          "n_jobs": 1, "random_state": 42}


def make_data(n, rng):
    x = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    return x, 3 * x["a"] + rng.normal(scale=0.5, size=n)


def test_refit_predict_returns_one_prediction_per_row_and_aligns_columns_by_name():
    rng = np.random.default_rng(0)
    x_train, y_train = make_data(200, rng)
    x_val, y_val = make_data(60, rng)
    x_pred, y_pred = make_data(40, rng)

    result = Model().refit_predict(x_train, y_train, x_val, y_val, x_pred[["b", "a"]], PARAMS, seeds=range(2))

    assert result.shape == (40,)
    assert np.corrcoef(result, y_pred)[0, 1] > 0.9


def test_refit_predict_is_reproducible_and_scaling_changes_the_tree_count():
    rng = np.random.default_rng(1)
    x_train, y_train = make_data(200, rng)
    x_val, y_val = make_data(60, rng)
    x_pred, _ = make_data(40, rng)
    model = Model()

    first = model.refit_predict(x_train, y_train, x_val, y_val, x_pred, PARAMS, seeds=range(2))
    again = model.refit_predict(x_train, y_train, x_val, y_val, x_pred, PARAMS, seeds=range(2))
    scaled = model.refit_predict(x_train, y_train, x_val, y_val, x_pred, PARAMS, seeds=range(2), scale_trees=True)

    assert np.allclose(first, again)
    assert not np.allclose(first, scaled)
