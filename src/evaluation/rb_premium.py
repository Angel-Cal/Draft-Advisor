"""What does the market's RB premium pay for that season value over replacement misses? (LOG.md, 2026-10-30)

Plain VOR takes WR over RB about 6 to 1 in rounds 3-6 even with a neutral curve, so at equal ADP the market charges RBs something that season points over replacement do not show. Realized outcomes,
RBs and WRs with ADP 25-72, seasons 2015-2025, hindsight replacement (the first non-starter at the position after the league's dedicated slots and FLEX, from actual season points, as `calibrate-deviations`).
Per player-season, with R = the position's replacement points per scheduled game and g = games played:
  season VOR        points - schedule x R               (what the advisor values: a replacement who plays every week)
  weekly-start VOR  sum over played weeks of max(0, week - R)   (a manager with a free replacement on the bench starts the player only when he beats R)
  their difference  = cover + bench:  cover = (schedule - g) x R  (weeks missed, replaced from the bench)   bench = sum over played weeks of max(0, R - week)  (weeks the player is benched for being bad)
Compared at equal ADP: within ADP 25-72, regress each quantity on ADP and an RB dummy; the RB coefficient is the RB-minus-WR gap at the same ADP (season-block bootstrap, 11 seasons). The weekly-start value
assumes a free replacement at R every week, so it is a ceiling on what weekly lineups can add; the advisor's option value over the waiver level is a partial version of it.
Run: python src/evaluation/rb_premium.py [--wr 2]   (default is the user's 3-WR league)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
TEAMS, STARTERS, FLEX = 12, {"RB": 2, "WR": 3, "TE": 1}, 1
if "--wr" in sys.argv:
    STARTERS["WR"] = int(sys.argv[sys.argv.index("--wr") + 1])
schedule = lambda season: 16 if season <= 2020 else 17


def replacement(points):
    """First non-starter at each position: dedicated slots first, then the best remaining RB/WR/TE fill the FLEX slots. `points` is a DataFrame with position and pts."""
    ranked = {p: points[points.position == p].pts.sort_values(ascending=False).to_numpy() for p in STARTERS}
    counts = {p: TEAMS * STARTERS[p] for p in STARTERS}
    rest = sorted((x, p) for p in ("RB", "WR", "TE") for x in ranked[p][counts[p]:])[::-1][:TEAMS * FLEX]
    for _, p in rest:
        counts[p] += 1
    return {p: ranked[p][min(counts[p], len(ranked[p]) - 1)] for p in STARTERS}


def player_seasons():
    weekly = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet")
    weekly = weekly[(weekly.season_type == "REG") & weekly.player_id.notna() & weekly.position.isin(STARTERS)]
    weekly = weekly[weekly.season.between(2015, 2025)]
    rows = []
    for season, w in weekly.groupby("season"):
        s = schedule(season)
        w = w.assign(week_pts=w.fantasy_points_ppr)
        tot = w.groupby(["player_id", "position"]).agg(pts=("week_pts", "sum"), g=("week_pts", "size")).reset_index()
        tot["g"] = tot.g.clip(upper=s)
        repl = replacement(tot)
        R = {p: repl[p] / s for p in repl}
        w = w.assign(R=w.position.map(R))
        agg = w.groupby("player_id").apply(lambda d: pd.Series({"start": np.maximum(0, d.week_pts - d.R).sum(), "bench": np.maximum(0, d.R - d.week_pts).sum()}), include_groups=False)
        t = tot.merge(agg, left_on="player_id", right_index=True)
        t["R"] = t.position.map(R)
        t["season"] = season
        t["season_vor"] = t.pts - s * t.R
        t["cover"] = (s - t.g) * t.R
        t["weekly_vor"] = t.start
        rows.append(t)
        print(f"{season}: replacement points RB {repl['RB']:.0f} WR {repl['WR']:.0f} TE {repl['TE']:.0f}", flush=True)
    return pd.concat(rows, ignore_index=True)


def with_adp(ps):
    out = []
    for y in range(2015, 2026):
        a = pd.read_csv(ROOT / "data" / "external" / f"adp_{y}.csv")[["player_id", "position", "adp"]].sort_values("adp").drop_duplicates("player_id")
        out.append(a[a.position.isin(["RB", "WR"])].assign(season=y))
    return pd.concat(out).merge(ps.drop(columns="position"), on=["player_id", "season"], how="left").pipe(lambda d: d[(d.adp >= 25) & (d.adp <= 72)])


def gap(d, column):
    """RB coefficient in column ~ 1 + adp + RB (same ADP, RB minus WR)."""
    x = np.column_stack([np.ones(len(d)), d.adp, (d.position == "RB").astype(float)])
    return np.linalg.lstsq(x, d[column].to_numpy(), rcond=None)[0][2]


if __name__ == "__main__":
    ps = player_seasons()
    D = with_adp(ps)
    for c in ("pts", "g", "start", "bench", "cover", "season_vor", "weekly_vor"):
        D[c] = D[c].fillna(0)
    D["g"] = D.g
    D["flex_value"] = D.weekly_vor - D.season_vor
    print(f"\nADP 25-72, {len(D)} player-seasons ({(D.position == 'RB').sum()} RB, {(D.position == 'WR').sum()} WR); STARTERS WR = {STARTERS['WR']}")
    print(D.groupby("position")[["adp", "pts", "g", "season_vor", "weekly_vor", "flex_value", "cover", "bench"]].mean().round(1).to_string())
    rng = np.random.default_rng(0)
    seasons = D.season.unique()
    print("\nRB minus WR at the same ADP (coefficient in value ~ ADP + RB; 90% interval from a season-block bootstrap):")
    for column in ("pts", "season_vor", "weekly_vor", "flex_value", "cover", "bench"):
        draws = [gap(pd.concat([D[D.season == s] for s in rng.choice(seasons, len(seasons))]), column) for _ in range(1000)]
        print(f"  {column:11s}{gap(D, column):8.1f}   [{np.percentile(draws, 5):7.1f}, {np.percentile(draws, 95):7.1f}]")
    print("\nby ADP half (RB minus WR, same regression inside the half):")
    for lo, hi in ((25, 48), (49, 72)):
        h = D[(D.adp >= lo) & (D.adp <= hi)]
        print(f"  ADP {lo}-{hi}: " + "  ".join(f"{c} {gap(h, c):6.1f}" for c in ("season_vor", "weekly_vor", "flex_value")))
    print("\nby season (RB minus WR gap): season_vor / weekly_vor")
    print("  " + "  ".join(f"{s}: {gap(D[D.season == s], 'season_vor'):5.0f}/{gap(D[D.season == s], 'weekly_vor'):4.0f}" for s in sorted(seasons)))
