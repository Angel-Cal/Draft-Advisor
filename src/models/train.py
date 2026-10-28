import pandas as pd
import numpy as np
import lightgbm as lgb
from lightgbm import LGBMRegressor
import sklearn.metrics as lk
from pathlib import Path
import matplotlib.pyplot as plt
import optuna 
import sys
import json
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.features.registry import other_position_features




ID_COLS = ["player_id", "player_name"]

def drop_non_features(df):
    return df.drop(columns=["target_ppr", "season"] + ID_COLS, errors="ignore")


class Model:
    def __init__(self, train_range = (range(2015, 2024)), val_season = 2024, test_season = 2025):
        self.train_range = train_range
        self.val_season = val_season
        self.test_season = test_season

    def temporal_splits(self, df):
        x_train = df[df["season"].isin(self.train_range)]
        y_train = x_train["target_ppr"]
        x_train = drop_non_features(x_train)

        x_val = df[df["season"] == self.val_season]
        y_val = x_val["target_ppr"]
        x_val = drop_non_features(x_val)

        x_test = df[df["season"] == self.test_season]
        y_test = x_test["target_ppr"]
        x_test = drop_non_features(x_test)

        return x_train, x_val, x_test, y_train, y_val, y_test
     
        
    def rolling_splits(self, df, min_train_seasons=6, offset=1):
        FIRST_SEASON = 2015
        LAST_SEASON = 2025
        df_list =[]
        first_test = FIRST_SEASON + min_train_seasons
        for test_season in range(first_test, LAST_SEASON + 1):
            val_season = test_season - offset
            train_range = range(FIRST_SEASON, val_season)

            x_train = df[df["season"].isin(train_range)]
            y_train = x_train["target_ppr"]
            x_train = drop_non_features(x_train)

            x_val = df[df["season"] == val_season]
            y_val = x_val["target_ppr"]
            x_val = drop_non_features(x_val)

            x_test = df[df["season"] == test_season]
            y_test = x_test["target_ppr"]
            x_test = drop_non_features(x_test)

            df_list.append((x_train, x_val, x_test, y_train, y_val, y_test)) 
        return df_list
    
    def walk_forward(self, df_list, params):
        metrics_list = []
        for fold in df_list:
           x_train, x_val, x_test, y_train, y_val, y_test = fold
           trained_model= self.train_model(x_train, x_val, y_train, y_val, params)
           mae, r2, rmse = self.evaluate_model(trained_model, x_test, y_test)
           metrics_list.append((mae, r2, rmse))
        return metrics_list
            
    def train_model(self, x_train, x_val, y_train, y_val, params):
        model = lgb.LGBMRegressor(**params)
        
        model.fit(
            x_train,
            y_train,
            eval_set=[(x_val, y_val)],
            eval_metric="rmse",
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)]
        )
        return model
    
    def train_final_model(self, x_train, y_train, params):
        model = lgb.LGBMRegressor(**params)
        model.fit(x_train, y_train)
        return model

    def refit_predict(self, x_train, y_train, x_val, y_val, x_pred, params, seeds=range(5), scale_trees=False):
        """Mean prediction of the validated recipe: per seed, early-stop on x_val (fit on x_train), then refit on both at the best iteration.

        With scale_trees the refit tree count is multiplied by the data-size ratio (len(train + val) / len(train)).
        """
        x_all, y_all = pd.concat([x_train, x_val]), pd.concat([y_train, y_val])
        ratio = len(x_all) / len(x_train) if scale_trees else 1.0
        predictions = []
        for seed in seeds:
            seeded = dict(params, random_state=seed)
            stopped = lgb.LGBMRegressor(**seeded)
            stopped.fit(x_train, y_train, eval_set=[(x_val, y_val)], eval_metric="rmse",
                        callbacks=[lgb.early_stopping(50, verbose=False)])
            refit = lgb.LGBMRegressor(**dict(seeded, n_estimators=max(1, round(stopped.best_iteration_ * ratio))))
            refit.fit(x_all, y_all)
            predictions.append(refit.predict(x_pred[x_train.columns]))
        return np.mean(predictions, axis=0)

    def evaluate_model(self, model, x_test, y_test):
        y_pred = model.predict(x_test)
        mae = lk.mean_absolute_error(y_test, y_pred)
        r2 = lk.r2_score(y_test, y_pred)
        rmse = lk.root_mean_squared_error(y_test, y_pred)
        return mae, r2, rmse

    def evaluate_per_position(self, model, x_test, y_test, positions):
        y_pred = model.predict(x_test)
        for pos in positions.unique():
            mask = positions == pos
            mae = lk.mean_absolute_error(y_test[mask], y_pred[mask])
            r2 = lk.r2_score(y_test[mask], y_pred[mask])
            rmse = lk.root_mean_squared_error(y_test[mask], y_pred[mask])
            print("Metric for position: ", pos, "\nMAE: ", mae, "\nr2:", r2, "\nRMSE: ", rmse, "\n")

    def ablate(self, x_train, x_test, x_val, exclude_patterns = []):
        drop_cols = [c for c in x_train.columns if any(p in c for p in exclude_patterns)]
        x_train = x_train.drop(columns = drop_cols)
        x_test = x_test.drop(columns = drop_cols)
        x_val = x_val.drop(columns = drop_cols)
        return x_train, x_test, x_val
    
    def objective(self, trial, df):
        params = {
            "num_leaves" : trial.suggest_int("num_leaves", 20, 200),
            "learning_rate" : trial.suggest_float("learning_rate", .01, .3, log = True),
            "min_child_samples" : trial.suggest_int("min_child_samples", 10, 100),
            "reg_alpha" : trial.suggest_float("reg_alpha", 1e-4, 10, log =True),
            "reg_lambda" : trial.suggest_float("reg_lambda", 1e-4, 10, log=True),
            "subsample" : trial.suggest_float("subsample", .5, 1.0),
            "colsample_bytree" : trial.suggest_float("colsample_bytree", .5, 1.0),
            "max_depth" : trial.suggest_int("max_depth", 3, 12),
            "n_estimators" : 1000,
            "verbosity" : -1,
            "objective" : "regression",
            "n_jobs" : -1,
            "random_state" : 42,
            "subsample_freq" : 1,
            "min_child_weight" : 1e-3
        }
        folds = self.rolling_splits(df)
        rmse_scores = []
        for fold in folds:
            x_train, x_val, x_test, y_train, y_val, y_test = fold
            model = lgb.LGBMRegressor(**params)
            model.fit(
                x_train,
                y_train,
                eval_set=[(x_val, y_val)],
                eval_metric="rmse",
                callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
            )
            _, _, rmse = self.evaluate_model(model, x_test, y_test)
            rmse_scores.append(rmse)
        return float(np.mean(rmse_scores))

    def tune(self, df, position, n_trials=100):
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="minimize")
        study.optimize(lambda trial: self.objective(trial, df), n_trials=n_trials)
        best_params = study.best_params
        best_params.update({
            "n_estimators": 1000,
            "verbosity": -1,
            "objective": "regression",
            "n_jobs": -1,
            "random_state": 42,
            "subsample_freq": 1,
            "min_child_weight": 1e-3
        })
        output_dir = Path(__file__).parent.parent.parent / "models"
        filename = f"{position}_params"
        filepath = output_dir/filename
        with open(filepath, "w") as f:
            json.dump(best_params, f)
        return best_params
        

# def print_baseline(df, model):
#     x_train, x_val, x_test, y_train, y_val, y_test = model.temporal_splits(df)
#     x_train_org = x_train
#     x_val_org = x_val
#     x_test_org = x_test
#     positions = x_test["position"]
#     trained_model = model.train_model(x_train, x_val, y_train, y_val)
#     mae, r2, rmse = model.evaluate_model(trained_model, x_test, y_test)
#     print("Baseline:\nMAE: ", mae, "R2: ", r2, "RMSE: ", rmse, "\n")

def print_rolling_splits(df, model, params):
    df_list = model.rolling_splits(df)
    metrics_list = model.walk_forward(df_list, params)
    counter =1
    for metrics in metrics_list:
        mae, r2, rmse = metrics
        print("Fold ", counter, "metrics\nMAE: ", mae, "R2: ", r2, "RMSE: ", rmse )
        counter+=1

    avg_mae = np.mean([m[0] for m in metrics_list])
    avg_r2 = np.mean([m[1] for m in metrics_list])
    avg_rmse = np.mean([m[2] for m in metrics_list])
    print("Walk-Forward Averages:\nMAE: ", avg_mae, "R2: ", avg_r2, "RMSE: ", avg_rmse)

def split_positions(df):
    QB_DROP_COLS = [
        "targets", "receiving_epa",
        "target_share", "air_yards_share", "wopr",
        "targets_pg", "receptions_pg", "receiving_yards_pg", "receiving_tds_pg",
        "receiving_first_downs_pg", "receiving_air_yards_pg", "receiving_yards_after_catch_pg",
        "pacr", "racr",
        "late_target_pct", "late_snap_pct",
        "targets_delta",
        "targets_pg_delta", "receptions_pg_delta", "receiving_yards_pg_delta",
        "receiving_tds_pg_delta", "receiving_first_downs_pg_delta",
        "receiving_air_yards_pg_delta", "receiving_yards_after_catch_pg_delta",
        "target_share_delta", "air_yards_share_delta", "wopr_delta",
    ]

    RB_DROP_COLS = [
        "attempts", "passing_epa",
        "completions_pg", "attempts_pg", "passing_yards_pg",
        "passing_tds_pg", "passing_interceptions_pg", "sacks_suffered_pg",
        "passing_first_downs_pg", "passing_cpoe", "passing_cpoe_delta", "passing_air_yards_pg",
        "pacr", "racr",
        "air_yards_share", "wopr",
        "receiving_air_yards_pg",
        "late_target_pct",
        "attempts_delta",
        "completions_pg_delta", "attempts_pg_delta",
        "passing_yards_pg_delta", "passing_tds_pg_delta",
        "passing_interceptions_pg_delta", "sacks_suffered_pg_delta",
        "passing_first_downs_pg_delta", "passing_air_yards_pg_delta",
        "air_yards_share_delta", "wopr_delta",
        "receiving_air_yards_pg_delta",
    ]

    WR_DROP_COLS = [
        "attempts", "passing_epa",
        "completions_pg", "attempts_pg", "passing_yards_pg",
        "passing_tds_pg", "passing_interceptions_pg", "sacks_suffered_pg",
        "passing_first_downs_pg", "passing_cpoe", "passing_cpoe_delta", "passing_air_yards_pg",
        "carries", "rushing_epa",
        "carries_pg", "rushing_yards_pg", "rushing_tds_pg",
        "rushing_first_downs_pg",
        "carries_delta", "carries_pg_delta",
        "rushing_yards_pg_delta", "rushing_tds_pg_delta",
        "rushing_first_downs_pg_delta",
        "attempts_delta",
        "completions_pg_delta", "attempts_pg_delta",
        "passing_yards_pg_delta", "passing_tds_pg_delta",
        "passing_interceptions_pg_delta", "sacks_suffered_pg_delta",
        "passing_first_downs_pg_delta", "passing_air_yards_pg_delta",
    ]
    
    qb_df = df[df["position"] == "QB"] 
    qb_df = qb_df.drop(columns=QB_DROP_COLS + other_position_features("QB"))

    rb_df = df[df["position"] == "RB"]
    rb_df = rb_df.drop(columns=RB_DROP_COLS + other_position_features("RB"))

    wr_df = df[df["position"] == "WR"]
    wr_df = wr_df.drop(columns=WR_DROP_COLS + other_position_features("WR"))

    te_df = df[df["position"] == "TE"]
    te_df = te_df.drop(columns=WR_DROP_COLS + other_position_features("TE"))

    return qb_df, rb_df, wr_df, te_df


if __name__ == "__main__":
    sys.stdout = open("output.log", "w")
    filepath = Path(__file__).parent.parent.parent / "data" / "processed"/ 'training_data.parquet'
    df = pd.read_parquet(filepath)
    qb_df, rb_df, wr_df, te_df = split_positions(df)

    model = Model()
    qb_x_train, qb_x_val, qb_x_test, qb_y_train, qb_y_val, qb_y_test = model.temporal_splits(qb_df)
    rb_x_train, rb_x_val, rb_x_test, rb_y_train, rb_y_val, rb_y_test = model.temporal_splits(rb_df)
    wr_x_train, wr_x_val, wr_x_test, wr_y_train, wr_y_val, wr_y_test = model.temporal_splits(wr_df)
    te_x_train, te_x_val, te_x_test, te_y_train, te_y_val, te_y_test = model.temporal_splits(te_df)

    qb_params = model.tune(qb_df, "qb")
    rb_params = model.tune(rb_df, "rb")
    wr_params = model.tune(wr_df, "wr")
    te_params = model.tune(te_df, "te")

    print_rolling_splits(qb_df, model, qb_params)
    print_rolling_splits(rb_df, model, rb_params)
    print_rolling_splits(wr_df, model, wr_params)
    print_rolling_splits(te_df, model, te_params)

    sys.stdout.close()
    sys.stdout = sys.__stdout__

