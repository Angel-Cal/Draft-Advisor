import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
import sys
import json
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.train import Model
from src.models.train import split_positions, drop_non_features
from src.data.pipeline import save
from src.data.validate import check_prediction_outputs
from src.data.run_manifest import check_freshness, update_manifest


def load_json(filename):
    MODELS_DIR = Path(__file__).parent.parent.parent / "models"
    with open(MODELS_DIR / filename, "r") as f:
        return json.load(f)
    
def load_data():
    filepath = Path(__file__).parent.parent.parent / "data" / "processed"
    prediction_df = pd.read_parquet(filepath/ "prediction_data.parquet")
    training_df = pd.read_parquet(filepath / "training_data.parquet")
    qb_params = load_json("qb_params")
    rb_params = load_json("rb_params")
    wr_params = load_json("wr_params")
    te_params = load_json("te_params")

    return prediction_df, training_df, qb_params, rb_params, wr_params,te_params

def save_metadata(df):
    df = df[["player_name", "player_id", "games", "games_delta", "injury_flag"]].copy()
    return df

def drop_season(df):
    df = df.drop(columns='season')
    return df

def drop_meta(df):
    df = df.drop(columns=['player_id', 'player_name', "injury_flag"])
    return df

if __name__ == "__main__":
    prediction_df, training_df, qb_params, rb_params, wr_params, te_params = load_data()
    qb_training_df, rb_training_df, wr_training_df, te_training_df = split_positions(training_df)
    qb_prediction_df, rb_prediction_df, wr_prediction_df, te_prediction_df = split_positions(prediction_df)

    qb_prediction_df = drop_season(qb_prediction_df)
    rb_prediction_df = drop_season(rb_prediction_df)
    wr_prediction_df = drop_season(wr_prediction_df)
    te_prediction_df = drop_season(te_prediction_df)

    qb_meta = save_metadata(qb_prediction_df)
    rb_meta = save_metadata(rb_prediction_df)
    wr_meta = save_metadata(wr_prediction_df)
    te_meta = save_metadata(te_prediction_df)

    qb_prediction_df = drop_meta(qb_prediction_df)
    rb_prediction_df = drop_meta(rb_prediction_df)
    wr_prediction_df = drop_meta(wr_prediction_df)
    te_prediction_df = drop_meta(te_prediction_df)

    model = Model()
    qb_x_train = drop_non_features(qb_training_df)
    qb_y_train = qb_training_df['target_ppr']

    rb_x_train = drop_non_features(rb_training_df)
    rb_y_train = rb_training_df['target_ppr']

    wr_x_train = drop_non_features(wr_training_df)
    wr_y_train = wr_training_df['target_ppr']

    te_x_train = drop_non_features(te_training_df)
    te_y_train = te_training_df['target_ppr']

    qb_model = model.train_final_model(qb_x_train, qb_y_train, qb_params)
    rb_model = model.train_final_model(rb_x_train,rb_y_train, rb_params)
    wr_model = model.train_final_model(wr_x_train, wr_y_train, wr_params)
    te_model = model.train_final_model(te_x_train, te_y_train, te_params)

    # LightGBM predicts positionally, so line the columns up with the training matrix by name
    qb_prediction = qb_model.predict(qb_prediction_df[qb_x_train.columns])
    rb_prediction = rb_model.predict(rb_prediction_df[rb_x_train.columns])
    wr_prediction = wr_model.predict(wr_prediction_df[wr_x_train.columns])
    te_prediction = te_model.predict(te_prediction_df[te_x_train.columns])

    results = {}
    for name, meta, prediction in [("qb", qb_meta, qb_prediction), ("rb", rb_meta, rb_prediction),
                                   ("wr", wr_meta, wr_prediction), ("te", te_meta, te_prediction)]:
        results[name] = meta.copy()
        results[name]['projected_ppr'] = prediction  # type: ignore

    # validate everything before writing anything, so a bad run can't leave half-updated outputs
    check_prediction_outputs({name.upper(): df for name, df in results.items()})
    for name, df in results.items():
        save(df, f"{name}_predictions")

    processed = Path(__file__).parent.parent.parent / "data" / "processed"
    check_freshness(inputs=[processed / "training_data.parquet", processed / "prediction_data.parquet"],
                    outputs=[processed / f"{name}_predictions.parquet" for name in results], label="predictions")
    update_manifest("predict", {"rows": {name: int(len(df)) for name, df in results.items()}, "validation": "passed"})


    

    


