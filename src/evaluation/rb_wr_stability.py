"""Are RBs or WRs more stable in rounds 3-6? (LOG.md, 2026-10-30)

RBs and WRs with ADP 25-72, 2015-2025: spread of points against the leave-season-out ADP curve, bust/boom shares (under 70% / over 130% of the curve), rank correlation with ADP, the same for
players with 14+ games, by ADP half, per-season mean residual and a season-block bootstrap of the RB-minus-WR spread difference.

Run: python src/evaluation/rb_wr_stability.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
ROOT = str(Path(__file__).parent.parent.parent) + "/"
sys.path.insert(0, ROOT)
from src.draft.market_fallback import fit_position_curves, load_history

hist = load_history(range(2015, 2026))
seas = pd.read_parquet(ROOT + "data/raw/seasonal_20_25.parquet")
seas = seas[seas.player_id.notna() & seas.position.isin(["RB", "WR"])][["player_id", "season", "games", "fantasy_points_ppr"]].drop_duplicates(["player_id", "season"])
rows = []
for y in range(2015, 2026):
    a = pd.read_csv(ROOT + f"data/external/adp_{y}.csv")[["player_id", "position", "adp"]].sort_values("adp").drop_duplicates("player_id")
    a = a[a.position.isin(["RB", "WR"])].copy()
    a["prank"] = a.groupby("position")["adp"].rank(method="first"); a["season"] = y
    curves = fit_position_curves(hist[hist.season != y])
    a["curve"] = [curves[p].predict([r])[0] for p, r in zip(a.position, a.prank)]
    rows.append(a.merge(seas[seas.season == y], on=["player_id", "season"], how="left"))
D = pd.concat(rows)
D["pts"] = D.fantasy_points_ppr.fillna(0); D["games"] = D.games.fillna(0)
D["ratio"] = D.pts / D.curve
# overall finish rank within position among ADP-ranked players, per season
D["finish"] = D.groupby(["season", "position"]).pts.rank(ascending=False, method="first")
R = D[(D.adp >= 25) & (D.adp <= 72)].copy()
R["healthy"] = R.games >= 14
R["res"] = R.pts - R.curve
R["rankgap"] = R.finish - R.prank

def table(P, label):
    out = {}
    for pos in ("RB", "WR"):
        q = P[P.position == pos]
        out[pos] = {"n": len(q), "mean pts": q.pts.mean(), "mean curve": q.curve.mean(), "SD pts": q.pts.std(), "SD resid": q.res.std(),
                    "CV (SD resid/curve)": q.res.std() / q.curve.mean(), "P10 ratio": q.ratio.quantile(.1), "P50 ratio": q.ratio.median(), "P90 ratio": q.ratio.quantile(.9),
                    "bust (<70%)": (q.ratio < .7).mean(), "boom (>130%)": (q.ratio > 1.3).mean(),
                    "rank corr ADP~pts": stats.spearmanr(q.prank, -q.pts)[0], "finish <= prank+12": (q.rankgap <= 12).mean(), "finish > prank+24": (q.rankgap > 24).mean()}
    print(f"\n=== {label}"); print(pd.DataFrame(out).round(3).to_string())

table(R, "ADP 25-72, all 2015-2025")
table(R[R.healthy], "same, played 14+ games only")
table(R[R.season >= 2019], "ADP 25-72, 2019-2025")
# bands within the range
for lo, hi in ((25, 48), (49, 72)):
    table(R[(R.adp >= lo) & (R.adp <= hi)], f"ADP {lo}-{hi}")
# per-season SD of residual (does one position swing more year to year?)
g = R.groupby(["season", "position"]).res.agg(["mean", "std"]).unstack()
print("\nper-season mean residual / SD:"); print(g.round(1).to_string())
print("SD across seasons of the position's mean residual: RB", round(g[("mean", "RB")].std(), 1), "WR", round(g[("mean", "WR")].std(), 1))
# year-over-year repeatability of finishing above/below ADP price
print("\nLevene test on residual dispersion RB vs WR:", stats.levene(R[R.position == "RB"].res, R[R.position == "WR"].res))
# bootstrap by season for SD difference
rng = np.random.default_rng(0); seasons = R.season.unique(); diffs = []
for _ in range(2000):
    s = rng.choice(seasons, len(seasons)); b = pd.concat([R[R.season == x] for x in s])
    diffs.append(b[b.position == "RB"].res.std() - b[b.position == "WR"].res.std())
print("SD(resid) RB - WR, season bootstrap: mean %.1f, 90%% CI %.1f to %.1f" % (np.mean(diffs), *np.percentile(diffs, [5, 95])))
