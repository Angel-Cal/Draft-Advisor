"""Does averaging the model with the ADP-to-points curve beat the model alone? Walk-forward: the curve for season s is fit on seasons before s only.

Reports point accuracy (RMSE, bias on the 'risers' the model under-projects) and top-150 Spearman for 2022-2025, then writes blended copies of the
backtest projection files to data/processed/blend/ so the simulator can judge the blend: `backtest --data data/processed/blend --seasons 2022-2025`.
Position RMSE in each blended file's header is scaled by the blend's RMSE ratio over the same players.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import fit_position_curves, load_history
from src.evaluation.benchmark import load_season

ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
EXTERNAL_DIR = ROOT / "data" / "external"
BLEND_DIR = PROCESSED_DIR / "blend"
SEASONS = range(2022, 2026)        # 2021 has no earlier season to fit a curve on
WEIGHT = 0.5                       # share of the model in the blend


def curve_points(season, history):
    """player_id -> expected PPR from the ADP curve fit on seasons before `season`."""
    curves = fit_position_curves(history[history["season"] < season])
    adp = pd.read_csv(EXTERNAL_DIR / f"adp_{season}.csv")[["player_id", "position", "adp"]].dropna(subset=["player_id"])
    adp["position_rank"] = adp.groupby("position")["adp"].rank(method="first")
    adp["curve_ppr"] = [float(curves[p].predict([r])[0]) if p in curves else np.nan for p, r in zip(adp["position"], adp["position_rank"])]
    return adp.set_index("player_id")["curve_ppr"]


def blended(model, curve, weight=WEIGHT):
    """Weighted average where the curve exists, the model alone elsewhere."""
    return np.where(curve.notna(), weight * model + (1 - weight) * curve, model)


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


if __name__ == "__main__":
    history = load_history()
    rows, spearman_rows, riser_rows, ratios = [], [], [], {}
    for season in SEASONS:
        df = load_season(season)
        df["curve"] = df["player_id"].map(curve_points(season, history))
        df["blend"] = blended(df["oos_pred_ppr"], df["curve"])
        df["season"] = season
        rows.append(df)
        for position, g in df[df["in_top_adp"]].groupby("position"):
            g = g.dropna(subset=["curve"])
            spearman_rows.append(dict(season=season, position=position, model=spearmanr(g["oos_pred_ppr"], g["actual_ppr"])[0],
                                      blend=spearmanr(g["blend"], g["actual_ppr"])[0], adp=spearmanr(-g["adp"], g["actual_ppr"])[0]))
    d = pd.concat(rows, ignore_index=True)

    print(f"Seasons {SEASONS.start}-{SEASONS.stop - 1}, curve fit walk-forward, blend = {WEIGHT:.0%} model + {1 - WEIGHT:.0%} ADP curve\n")
    print("RMSE of points, players with a curve value (all ranked players / top 150 by ADP)")
    out = []
    for position, g in d.dropna(subset=["curve"]).groupby("position"):
        t = g[g["in_top_adp"]]
        out.append(dict(position=position, n_all=len(g), model=rmse(g["oos_pred_ppr"], g["actual_ppr"]), curve=rmse(g["curve"], g["actual_ppr"]),
                        blend=rmse(g["blend"], g["actual_ppr"]), n_top=len(t), top_model=rmse(t["oos_pred_ppr"], t["actual_ppr"]),
                        top_curve=rmse(t["curve"], t["actual_ppr"]), top_blend=rmse(t["blend"], t["actual_ppr"])))
        ratios[position] = rmse(g["blend"], g["actual_ppr"]) / rmse(g["oos_pred_ppr"], g["actual_ppr"])
    print(pd.DataFrame(out).round(2).to_string(index=False))

    print("\nTop-150 Spearman vs actual points, mean over seasons")
    print(pd.DataFrame(spearman_rows).groupby("position")[["model", "blend", "adp"]].mean().round(3).to_string())

    print("\nRisers (ADP rank better than last-year output rank, top third within position): mean (actual - projection) / projection")
    top = d[d["in_top_adp"]].dropna(subset=["curve"]).copy()
    top["adp_rank"] = top.groupby(["season", "position"])["adp"].rank()
    top["prod_rank"] = top.groupby(["season", "position"])["last_year_ppr"].rank(ascending=False)
    top["lift"] = top["prod_rank"] - top["adp_rank"]
    top["riser"] = top.groupby("position")["lift"].rank(pct=True) >= 2 / 3
    for label, g in [("risers", top[top["riser"]]), ("rest", top[~top["riser"]])]:
        scale = g["oos_pred_ppr"].clip(lower=50)
        print(f"  {label:7} n={len(g):3d}  model bias {((g['actual_ppr'] - g['oos_pred_ppr']) / scale).mean():+.3f}   "
              f"blend bias {((g['actual_ppr'] - g['blend']) / g['blend'].clip(lower=50)).mean():+.3f}   "
              f"RMSE model {rmse(g['oos_pred_ppr'], g['actual_ppr']):.1f}  blend {rmse(g['blend'], g['actual_ppr']):.1f}")

    BLEND_DIR.mkdir(exist_ok=True)
    for season in SEASONS:
        path = PROCESSED_DIR / f"projections_{season}_v1.json"
        data = json.loads(path.read_text())
        curve = curve_points(season, history)
        for player in data["players"]:
            value = curve.get(player["player_id"], np.nan)
            if not player["market_estimate"] and not np.isnan(value):
                player["projected_ppr"] = round(WEIGHT * player["projected_ppr"] + (1 - WEIGHT) * float(value), 2)
        data["position_rmse"] = {p: round(v * ratios[p], 2) for p, v in data["position_rmse"].items()}
        data["adp_source"] = data["adp_source"] + "; projected_ppr = 50/50 model and walk-forward ADP curve (blend_test.py)"
        (BLEND_DIR / path.name).write_text(json.dumps(data))
    print(f"\nwrote {len(list(SEASONS))} blended files to {BLEND_DIR}; RMSE scaled by {({p: round(r, 3) for p, r in ratios.items()})}")
