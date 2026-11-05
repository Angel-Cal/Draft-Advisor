"""Realized QB cliff: what does each QB ADP rank actually return over a replacement QB? (user's question, 2026-11-04)

Before defining "early QB" as some top-N, look at the outcome by QB rank within the ADP (QB1, QB2, ...) for 2015-2025, one rank at a time.
Value over replacement for a 1-QB, 12-team league: the replacement is the 13th QB by actual season points that season (hindsight). Two views:
  season VOR  = season PPR minus the 13th QB's season PPR (a missed game counts as 0)
  start VOR   = sum over the weeks he played of (week PPR minus the replacement's points per game), i.e. a missed week is filled by a
                replacement-level starter, which is what a manager with a free backup gets
Also the mean overall ADP of each rank (the pick it costs) and a pooled view (each rank with its two neighbours) to smooth the 11 seasons.
Writes nothing; run: python src/evaluation/qb_cliff.py [--max-rank 24]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).parent.parent.parent
RAW = ROOT / "data" / "raw"
SEASONS = range(2015, 2026)
REPLACEMENT_RANK = 13
MAX_RANK = int(sys.argv[sys.argv.index("--max-rank") + 1]) if "--max-rank" in sys.argv else 24


def rows():
    seasonal = pd.read_parquet(RAW / "seasonal_20_25.parquet")
    seasonal = seasonal[(seasonal["season_type"] == "REG") & (seasonal["position"] == "QB")]
    weekly = pd.read_parquet(RAW / "weekly_20_25.parquet", columns=["player_id", "season", "week", "season_type", "position", "fantasy_points_ppr"])
    weekly = weekly[(weekly["season_type"] == "REG") & (weekly["position"] == "QB")]
    frames = []
    for season in SEASONS:
        s = seasonal[seasonal["season"] == season]
        repl = s["fantasy_points_ppr"].nlargest(REPLACEMENT_RANK).iloc[-1]
        repl_pg = repl / (17 if season >= 2021 else 16)
        adp = pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv")
        adp = adp[adp["position"] == "QB"].sort_values("adp").drop_duplicates("player_id").copy()
        adp["qb_rank"] = np.arange(1, len(adp) + 1)
        adp = adp[adp["qb_rank"] <= MAX_RANK]
        adp = adp.merge(s[["player_id", "fantasy_points_ppr", "games"]], on="player_id", how="left").fillna({"fantasy_points_ppr": 0, "games": 0})
        w = weekly[weekly["season"] == season].groupby("player_id")["fantasy_points_ppr"].apply(lambda x: (x - repl_pg).sum())
        adp["start_vor"] = adp["player_id"].map(w).fillna(0)
        adp["season_vor"] = adp["fantasy_points_ppr"] - repl
        adp["season"] = season
        adp["replacement"] = repl
        frames.append(adp)
    return pd.concat(frames, ignore_index=True)


def report(d):
    print(f"QBs by ADP rank, {SEASONS.start}-{SEASONS.stop - 1} ({d['season'].nunique()} seasons); replacement = QB{REPLACEMENT_RANK} by actual points, "
          f"mean {d.groupby('season')['replacement'].first().mean():.0f} PPR")
    t = d.groupby("qb_rank").agg(pick=("adp", "mean"), ppr=("fantasy_points_ppr", "mean"), games=("games", "mean"),
                                 season_vor=("season_vor", "mean"), start_vor=("start_vor", "mean"), sd=("start_vor", "std"), n=("start_vor", "size"))
    t["se"] = t["sd"] / np.sqrt(t["n"])
    t["top12_finish"] = d.assign(top=d["season_vor"] > 0).groupby("qb_rank")["top"].mean()
    t["step"] = t["start_vor"] - t["start_vor"].shift(-1)
    # pooled: each rank with its neighbours (rank-1, rank, rank+1), so each cell has about 33 player-seasons
    t["pooled"] = [d[d["qb_rank"].between(r - 1, r + 1)]["start_vor"].mean() for r in t.index]
    t["isotonic"] = IsotonicRegression(increasing=False).fit(d["qb_rank"], d["start_vor"]).predict(t.index)
    print("\nper rank (start VOR = weeks played minus the replacement's points per game; +/- is the SE over 11 seasons)")
    print(f"{'rank':>5}{'pick':>7}{'PPR':>7}{'games':>7}{'season VOR':>12}{'start VOR':>11}{'+/-':>6}{'top-12':>8}{'step to next':>14}{'pooled 3':>10}{'monotone':>10}")
    for r, x in t.iterrows():
        print(f"{'QB' + str(r):>5}{x.pick:>7.1f}{x.ppr:>7.0f}{x.games:>7.1f}{x.season_vor:>+12.0f}{x.start_vor:>+11.0f}{x.se:>6.0f}{x.top12_finish:>8.0%}"
              f"{x.step:>+14.0f}{x.pooled:>+10.0f}{x.isotonic:>+10.0f}")
    print("\nby season, start VOR of QB1-3 / QB4-6 / QB7-9 / QB10-12 (descriptive bands only):")
    bands = pd.cut(d["qb_rank"], [0, 3, 6, 9, 12, 99], labels=["1-3", "4-6", "7-9", "10-12", "13+"])
    print(d.groupby(["season", bands], observed=True)["start_vor"].mean().unstack().round(0).to_string())


if __name__ == "__main__":
    report(rows())
