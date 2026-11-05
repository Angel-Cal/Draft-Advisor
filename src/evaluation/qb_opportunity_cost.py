"""Is an early QB worth his pick? Each QB's realized value against the RBs and WRs drafted at the same picks (user's question, 2026-11-04).

Follows `qb_cliff.py`, which set the tiers by realized value: QB1-2, QB3-7, QB8-12 by ADP rank. Here the question is the cost: the pick spent
on a QB could have been an RB or WR. For every player with an ADP (2015-2025) the realized value is his start VOR (weeks played minus his
position's replacement points per game, so a missed week is filled at replacement level); replacement levels come from filling a 12-team
lineup with actual season points (QB 1, RB 2, WR 3 or 2, TE 1, one RB/WR/TE FLEX; the best non-starter is the replacement). A QB's excess is
his start VOR minus the mean start VOR of the RBs and WRs whose ADP is within `--window` picks of his (same season).
Strategy reading: "early QB" (a QB1-2 at about pick 23 plus a skill player at about pick 50) against "mid QB" (a skill player at pick 23 plus a
QB3-7 at pick 50) differs by excess(QB1-2) - excess(QB3-7); likewise mid against late. First-order only: no roster fit, hindsight replacement.
Writes nothing; run: python src/evaluation/qb_opportunity_cost.py [--window 6]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent.parent
RAW = ROOT / "data" / "raw"
SEASONS = range(2015, 2026)
TEAMS = 12
TIERS = {"QB1-2": (1, 2), "QB3-7": (3, 7), "QB8-12": (8, 12)}
WINDOW = int(sys.argv[sys.argv.index("--window") + 1]) if "--window" in sys.argv else 6
N_BOOT = 4000
SEED = 0


def replacement_levels(season_points, wr_slots):
    """{position: season points of the best non-starter} from a greedy fill of a 12-team lineup with actual points."""
    slots = {"QB": 1, "RB": 2, "WR": wr_slots, "TE": 1}
    starters, rest = {}, []
    for pos, n in slots.items():
        pts = season_points[season_points["position"] == pos]["fantasy_points_ppr"].sort_values(ascending=False).values
        starters[pos] = n * TEAMS
        if pos != "QB":
            rest += [(p, pos) for p in pts[n * TEAMS:]]
    for _, pos in sorted(rest, reverse=True)[:TEAMS]:          # FLEX
        starters[pos] += 1
    return {pos: season_points[season_points["position"] == pos]["fantasy_points_ppr"].sort_values(ascending=False).values[starters[pos]]
            for pos in slots}


def rows(wr_slots):
    seasonal = pd.read_parquet(RAW / "seasonal_20_25.parquet")
    seasonal = seasonal[(seasonal["season_type"] == "REG") & seasonal["position"].isin(["QB", "RB", "WR", "TE"])]
    weekly = pd.read_parquet(RAW / "weekly_20_25.parquet", columns=["player_id", "season", "season_type", "fantasy_points_ppr"])
    weekly = weekly[weekly["season_type"] == "REG"]
    frames = []
    for season in SEASONS:
        s = seasonal[seasonal["season"] == season]
        repl = replacement_levels(s, wr_slots)
        weeks = 17 if season >= 2021 else 16
        adp = pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv")
        adp = adp[adp["position"].isin(["QB", "RB", "WR"])].sort_values("adp").drop_duplicates("player_id").copy()
        adp["pos_rank"] = adp.groupby("position").cumcount() + 1
        w = weekly[weekly["season"] == season].groupby("player_id")["fantasy_points_ppr"].apply(list)
        adp["start_vor"] = [sum(x - repl[p] / weeks for x in w.get(pid, [])) for pid, p in zip(adp["player_id"], adp["position"])]
        adp["season"] = season
        frames.append(adp)
    return pd.concat(frames, ignore_index=True)


def qb_excess(d, window=WINDOW, comparators=("RB", "WR")):
    """QB rows in the three tiers with the mean start VOR of the RBs/WRs drafted within `window` picks."""
    out = []
    for season, g in d.groupby("season"):
        skill = g[g["position"].isin(comparators)]
        for tier, (lo, hi) in TIERS.items():
            for _, qb in g[(g["position"] == "QB") & g["pos_rank"].between(lo, hi)].iterrows():
                near = skill[(skill["adp"] - qb["adp"]).abs() <= window]
                out.append(dict(season=season, tier=tier, name=qb["name"], adp=qb["adp"], qb=qb["start_vor"],
                                skill=near["start_vor"].mean(), n_skill=len(near)))
    e = pd.DataFrame(out)
    e["excess"] = e["qb"] - e["skill"]
    return e


def boot(e, stat, rng):
    seasons = e["season"].unique()
    by = {s: g for s, g in e.groupby("season")}
    vals = [stat(pd.concat([by[s] for s in rng.choice(seasons, len(seasons))])) for _ in range(N_BOOT)]
    return stat(e), np.percentile(vals, 5), np.percentile(vals, 95)


def tier_mean(e, tier):
    return e.loc[e["tier"] == tier, "excess"].mean()


def report(e, label, rng):
    print(f"\n=== {label}")
    print(f"{'tier':<8}{'n':>4}{'pick':>7}{'QB value':>10}{'RB/WR at that pick':>20}{'excess':>8}{'90% interval':>16}")
    for tier in TIERS:
        g = e[e["tier"] == tier]
        b, lo, hi = boot(e, lambda x: tier_mean(x, tier), rng)
        print(f"{tier:<8}{len(g):>4}{g['adp'].mean():>7.1f}{g['qb'].mean():>+10.0f}{g['skill'].mean():>+20.0f}{b:>+8.0f}{f'[{lo:+.0f}, {hi:+.0f}]':>16}")
    for name, a, c in [("early (QB1-2) minus mid (QB3-7)", "QB1-2", "QB3-7"), ("mid (QB3-7) minus late (QB8-12)", "QB3-7", "QB8-12"),
                       ("early (QB1-2) minus late (QB8-12)", "QB1-2", "QB8-12")]:
        b, lo, hi = boot(e, lambda x: tier_mean(x, a) - tier_mean(x, c), rng)
        print(f"  strategy {name}: {b:+.0f} [{lo:+.0f}, {hi:+.0f}] points per season")


if __name__ == "__main__":
    rng = np.random.default_rng(SEED)
    for wr_slots, league in [(3, "3-WR league (yours)"), (2, "2-WR league")]:
        d = rows(wr_slots)
        e = qb_excess(d)
        report(e, f"{league}, window +/-{WINDOW} picks, 2015-2025", rng)
        for era, ss in [("2015-2019", range(2015, 2020)), ("2020-2025", range(2020, 2026))]:
            report(e[e["season"].isin(ss)], f"{league}, {era}", rng)
        if wr_slots == 3:
            for comp in [("RB",), ("WR",)]:
                report(qb_excess(d, comparators=comp), f"{league}, against {comp[0]}s only, 2015-2025", rng)
            report(qb_excess(d, window=10), f"{league}, window +/-10 picks, 2015-2025", rng)
            e["year_excess"] = e["excess"]
            print("\nper season, excess by tier (3-WR):")
            print(e.pivot_table(index="season", columns="tier", values="excess", aggfunc="mean").round(0).to_string())
