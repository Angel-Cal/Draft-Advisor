"""Are rookies mispriced in the late rounds? (LOG.md, 2026-11-05)

RB/WR/TE with ADP 73-192 (rounds 7-16 in a 12-team league), seasons 2015-2025. Rookie = the roster's rookie_year equals the season (years_exp 0 as fallback). Per player-season:
  res         actual PPR minus the leave-season-out ADP curve (the same curve the advisor uses for rookies)
  season_vor  points minus a full season at the hindsight replacement rate (`rb_premium.replacement`, 3-WR league)
  kept_vor    max(0, season_vor): the value of a bench pick you keep if he hits and cut for free if he busts (option view)
  weekly_vor  sum over played weeks of max(0, week - replacement rate) (a free replacement every week; a ceiling)
  starter     finished inside the league's starters at his position (RB 24+, WR 36+, TE 12 after FLEX)
Rookie minus veteran at the same ADP: OLS of each measure on ADP, position dummies and a rookie dummy; the rookie coefficient with a season-block bootstrap (11 seasons).
The curve is fit on players with 4+ games, so it runs high at deep ranks for everyone; the rookie-veteran comparison is at the same ADP and does not depend on it.
Run: python src/evaluation/rookie_late.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from src.data.market_fallback import fit_position_curves, load_history
from src.evaluation.rb_premium import STARTERS, TEAMS, player_seasons, replacement

LO, HI = 73, 192
MEASURES = ["res", "season_vor", "kept_vor", "weekly_vor", "starter"]


def rookie_flags():
    """(player_id, season) -> True for a player in his rookie season."""
    r = pd.read_parquet(ROOT / "data" / "raw" / "seasonal_roster_20_25.parquet", columns=["gsis_id", "season", "rookie_year", "years_exp"]).dropna(subset=["gsis_id"])
    r["rookie_year"] = pd.to_numeric(r.rookie_year, errors="coerce")
    r["years_exp"] = pd.to_numeric(r.years_exp, errors="coerce")
    r["rookie"] = np.where(r.rookie_year.notna(), r.rookie_year == r.season, r.years_exp == 0)
    return r.groupby(["gsis_id", "season"]).rookie.max().rename_axis(["player_id", "season"])


def build():
    hist = load_history(range(2015, 2026))
    ps = player_seasons().set_index(["player_id", "season"])
    rookies = rookie_flags()
    rows = []
    for y in range(2015, 2026):
        a = pd.read_csv(ROOT / "data" / "external" / f"adp_{y}.csv")[["player_id", "name", "position", "adp"]].sort_values("adp").drop_duplicates("player_id")
        a = a[a.position.isin(STARTERS)].copy()
        a["prank"] = a.groupby("position").adp.rank(method="first"); a["season"] = y
        curves = fit_position_curves(hist[hist.season != y])
        a["curve"] = [curves[p].predict([r])[0] for p, r in zip(a.position, a.prank)]
        rows.append(a[(a.adp >= LO) & (a.adp <= HI)])
    D = pd.concat(rows).set_index(["player_id", "season"])
    D = D.join(ps[["pts", "g", "R", "season_vor", "weekly_vor"]], how="left")
    # players with no snaps: 0 points, a full season of replacement given up
    D["pts"] = D.pts.fillna(0); D["g"] = D.g.fillna(0); D["weekly_vor"] = D.weekly_vor.fillna(0)
    repl = {s: replacement(ps.xs(s, level="season").reset_index()) for s in range(2015, 2026)}
    no_play = pd.Series([-repl[s][p] for s, p in zip(D.index.get_level_values("season"), D.position)], index=D.index)
    D["season_vor"] = D.season_vor.fillna(no_play)
    D["kept_vor"] = D.season_vor.clip(lower=0)
    D["res"] = D.pts - D.curve
    D["starter"] = (D.season_vor >= 0).astype(float)
    D["rookie"] = rookies.reindex(D.index, fill_value=False).astype(bool)
    return D.reset_index()


def rookie_coef(d, y):
    """OLS coefficient on the rookie dummy, controls ADP and position."""
    X = np.column_stack([np.ones(len(d)), d.adp, d.position.eq("RB"), d.position.eq("TE"), d.rookie]).astype(float)
    return np.linalg.lstsq(X, d[y].to_numpy(float), rcond=None)[0][-1]


def gap_table(D, label, rng):
    seasons = D.season.unique()
    out = {}
    for m in MEASURES:
        est = rookie_coef(D, m)
        boots = [rookie_coef(pd.concat([D[D.season == s] for s in rng.choice(seasons, len(seasons))]), m) for _ in range(1000)]
        out[m] = {"rookie": D[D.rookie][m].mean(), "veteran": D[~D.rookie][m].mean(), "gap at same ADP": est,
                  "90% lo": np.percentile(boots, 5), "90% hi": np.percentile(boots, 95)}
    print(f"\n=== {label}: rookies {D.rookie.sum()}, veterans {(~D.rookie).sum()}")
    print(pd.DataFrame(out).T.round(2).to_string())


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    D = build()
    rng = np.random.default_rng(0)
    gap_table(D, f"RB/WR/TE, ADP {LO}-{HI}, 2015-2025", rng)
    for pos in ("RB", "WR", "TE"):
        P = D[D.position == pos]
        X = P.assign(position="WR")  # single position: the dummies are constant zero
        gap_table(X, f"{pos} only", rng)
    gap_table(D[D.adp <= 120], f"ADP {LO}-120 (rounds 7-10)", rng)
    gap_table(D[D.adp > 120], f"ADP 121-{HI} (rounds 11-16)", rng)
    print("\nper season, rookie minus veteran at same ADP (res / kept_vor / starter rate), n rookies:")
    for s, g in D.groupby("season"):
        print(s, round(rookie_coef(g, "res"), 1), round(rookie_coef(g, "kept_vor"), 1), round(rookie_coef(g, "starter"), 3), int(g.rookie.sum()))
    R = D[D.rookie].sort_values("season_vor", ascending=False)
    print("\nbest late rookies:"); print(R.head(12)[["season", "name", "position", "adp", "pts", "curve", "season_vor"]].round(0).to_string(index=False))
    print(f"\nrookie share of the late pool {D.rookie.mean():.2f}; share of the late pool's starter finishes {D[D.starter == 1].rookie.mean():.2f}")
