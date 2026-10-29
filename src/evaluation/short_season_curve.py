"""Pull short-season players toward the ADP curve: held-out accuracy, then backtest files for the simulator.

short_season_check.py shows the model under-projects draftable players who played 9 games or fewer last season (+34 points) while the ADP curve does not
(-7), and short_season_fixes.py shows no model-side change repairs it. Here the projection of those players (curve available, prior games <= 9) becomes the
ADP-curve expectation (weight 0) or the average of the two (weight 0.5); everyone else keeps the model. Curves are fit on earlier seasons only (2022-2025).
Scored on the draftable rows: top-150 Spearman per position (mean over seasons), RMSE, and the residual of the short-season rows. Writes backtest files under
data/processed/short_season/<arm>/ (`backtest --data <dir> --seasons 2022-2025` scores them); run: python src/evaluation/short_season_curve.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.blend_test import rmse
from src.evaluation.gap_reliability import load_rows
from src.evaluation.refit_oos import write_backtest_files

ROOT = Path(__file__).parent.parent.parent
OUT_DIR = ROOT / "data" / "processed" / "short_season"
SHORT = 9
ARMS = {"model": None, "short to curve": 0.0, "short half curve": 0.5}


def adjusted(d, model_weight):
    """The model's projection, except short-season rows with a curve value: model_weight x model + (1 - model_weight) x curve."""
    short = (d["games"] <= SHORT) & d["curve"].notna()
    return pd.Series(np.where(short, model_weight * d["oos_pred_ppr"] + (1 - model_weight) * d["curve"], d["oos_pred_ppr"]), index=d.index)


if __name__ == "__main__":
    d = load_rows()
    for name, weight in ARMS.items():
        d[name] = d["oos_pred_ppr"] if weight is None else adjusted(d, weight)
    top = d[d["in_top_adp"]]
    short = top["games"] <= SHORT
    print(f"{int(short.sum())} short-season draftable rows, 2022-2025\n")
    print(f"{'arm':<20}" + "".join(f"{p + ' rho':>9}{p + ' rmse':>10}" for p in ["QB", "RB", "WR", "TE"]) + f"{'short resid':>13}{'rest resid':>12}")
    for name in ARMS:
        cells = ""
        for position in ["QB", "RB", "WR", "TE"]:
            g = top[top["position"] == position]
            cells += f"{np.mean([spearmanr(s[name], s['actual_ppr'])[0] for _, s in g.groupby('season')]):>9.3f}{rmse(g[name], g['actual_ppr']):>10.1f}"
        resid = top["actual_ppr"] - top[name]
        print(f"{name:<20}{cells}{resid[short].mean():>13.1f}{resid[~short].mean():>12.1f}")

    for name in list(ARMS)[1:]:
        ratios = {p: rmse(g[name], g["actual_ppr"]) / rmse(g["oos_pred_ppr"], g["actual_ppr"]) for p, g in d.groupby("position")}
        folder = write_backtest_files(d, name, OUT_DIR / name.replace(" ", "_"), f"{name} (short_season_curve.py)", ratios)
        print(f"wrote {folder}")
