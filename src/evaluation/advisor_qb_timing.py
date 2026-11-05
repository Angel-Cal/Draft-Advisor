"""When does the adopted advisor take its QB, and from which tier? (user's question, 2026-11-04; follows qb_opportunity_cost.py)

Reads the Sim's `pick-log` output (every own-team pick of plain ADP and `need+wait`, every slot and seed) and labels each QB pick by his
QB rank in that season's ADP, in the tiers set by `qb_cliff.py` (QB1-2, QB3-7, QB8-12, QB13+), with his realized start VOR from
`qb_opportunity_cost.rows` (3-WR league). Reports, per strategy: the tier and round of the team's first QB, its realized value, how often a
second QB is taken and when, and the split by season and slot. Writes nothing; run after
`dotnet run -c Release --project csharp/src/DraftBot.Sim -- pick-log --data data/processed/experiments/worlds/routed/routed --out data/processed/experiments/sims/pick_log_live.csv`:
python src/evaluation/advisor_qb_timing.py [--log data/processed/experiments/sims/pick_log_live.csv]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import SIMS
from src.evaluation.qb_opportunity_cost import rows as value_rows

ROOT = Path(__file__).parent.parent.parent
LOG = Path(sys.argv[sys.argv.index("--log") + 1]) if "--log" in sys.argv else SIMS / "pick_log_live.csv"
TIER_BINS = [0, 2, 7, 12, 999]
TIER_LABELS = ["QB1-2", "QB3-7", "QB8-12", "QB13+"]


def load():
    picks = pd.read_csv(LOG)
    values = value_rows(3)
    qb_rank = values[values["position"] == "QB"].set_index(["season", "player_id"])["pos_rank"]
    vor = values.set_index(["season", "player_id"])["start_vor"]
    qbs = picks[picks["position"] == "QB"].copy()
    key = pd.MultiIndex.from_frame(qbs[["season", "player_id"]])
    qbs["qb_rank"] = qb_rank.reindex(key).values
    qbs["start_vor"] = vor.reindex(key).fillna(0).values
    qbs["tier"] = pd.cut(qbs["qb_rank"].fillna(999), TIER_BINS, labels=TIER_LABELS)
    qbs["order"] = qbs.groupby(["season", "seed", "slot", "strategy"])["round"].rank(method="first")
    return picks, qbs


def report(picks, qbs):
    drafts = picks.groupby("strategy")[["season", "seed", "slot"]].apply(lambda g: len(g.drop_duplicates()))
    print(f"{LOG.name}: {drafts.to_dict()} drafts per strategy, seasons {picks['season'].min()}-{picks['season'].max()}")
    first = qbs[qbs["order"] == 1]
    print("\nfirst QB: tier share, mean round, mean overall ADP, realized start VOR (3-WR)")
    t = first.groupby(["strategy", "tier"], observed=True).agg(n=("round", "size"), round=("round", "mean"), adp=("adp", "mean"), vor=("start_vor", "mean"))
    t["share"] = t["n"] / t.groupby("strategy")["n"].transform("sum")
    print(t[["share", "round", "adp", "vor"]].round(2).to_string())
    print("\nfirst QB, all tiers: " + "; ".join(f"{s}: round {g['round'].mean():.1f}, value {g['start_vor'].mean():+.1f}" for s, g in first.groupby("strategy")))
    rounds = first.pivot_table(index="round", columns="strategy", values="seed", aggfunc="size", fill_value=0)
    print("\nround of the first QB (share of drafts):\n" + (rounds / rounds.sum()).round(3).to_string())
    second = qbs[qbs["order"] == 2]
    print("\nsecond QB: " + "; ".join(f"{s}: taken in {len(g) / drafts[s]:.0%} of drafts, mean round {g['round'].mean():.1f}" for s, g in second.groupby("strategy")))
    print("\nfirst-QB tier share by season:")
    print(first.groupby(["season", "strategy"])["tier"].value_counts(normalize=True).unstack().round(2).to_string())
    print("\nfirst-QB tier share by slot (need+wait):")
    print(first[first["strategy"] == "need+wait"].groupby("slot")["tier"].value_counts(normalize=True).unstack().round(2).to_string())
    paired = first.pivot_table(index=["season", "seed", "slot"], columns="strategy", values="start_vor")
    diff = (paired["need+wait"] - paired["adp"]).groupby(level="season").mean()
    print(f"\nfirst-QB realized value, need+wait minus adp: {diff.mean():+.1f} per draft (by season {diff.round(1).to_dict()})")


if __name__ == "__main__":
    report(*load())
