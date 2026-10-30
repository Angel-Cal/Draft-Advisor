"""Does a recommender setting chosen on the validated files keep its sign in other worlds? (LOG.md, 2026-10-29)

The validated files turned out to be one favourable draw for the survival-scaled reach cost, so every setting tuned only there is exposed to the same winner's curse. This driver
runs the Sim's `world-sweep` (waiting weight x lambda, reach cap, the first free pick, each against the adopted advisor, paired, points and title odds) on several worlds and reports,
per setting, the margin in each world, its mean and spread across worlds, and how many worlds it is ahead in.

Worlds: `validated` (data/processed), `refit` and `refit_routed` (the live recipe, from routed_oos.py), `perturb/p0-p3` (validated projections plus N(0, 8) noise: projection luck only) and
`shuffled/s0-s2` (validated projections and ADP, the actual outcomes of players with neighbouring ADP at the same position swapped in groups of four: outcome luck re-rolled, and the
model's within-group information removed). Perturbed worlds share the real outcomes; shuffled worlds share the real projections.

Writes data/processed/world_sweep.csv (or world_sweep_<arms>.csv). Run: python src/evaluation/world_sweep.py [--seeds 40] [--arms reach|need] [--make-only] [--worlds validated,refit]
`--tiers` instead runs the adopted advisor alone at several tier-gap settings in every world and prints its edge over ADP (the tier gap only changes the pool's valuation).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent.parent
PROCESSED = ROOT / "data" / "processed"
SEASONS = range(2021, 2026)
GROUP = 4          # neighbours (by ADP, same position) whose outcomes are swapped
N_SHUFFLED = 3
N_PERTURBED = 4
NOISE_SD = 8.0


def make_perturbed():
    """Validated files with N(0, NOISE_SD) added to every model projection."""
    for k in range(N_PERTURBED):
        out = PROCESSED / "perturb" / f"p{k}"
        out.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(1000 + k)
        for season in SEASONS:
            data = json.loads((PROCESSED / f"projections_{season}_v1.json").read_text())
            for p in data["players"]:
                if not p["market_estimate"]:
                    p["projected_ppr"] = round(p["projected_ppr"] + float(rng.normal(0, NOISE_SD)), 2)
            (out / f"projections_{season}_v1.json").write_text(json.dumps(data))


def make_shuffled():
    """Validated files with the outcomes (actual_ppr and weekly_ppr) permuted inside groups of GROUP same-position players with neighbouring ADP."""
    for k in range(N_SHUFFLED):
        out = PROCESSED / "shuffled" / f"s{k}"
        out.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(2000 + k)
        for season in SEASONS:
            data = json.loads((PROCESSED / f"projections_{season}_v1.json").read_text())
            players = data["players"]
            for position in {p["position"] for p in players}:
                members = sorted([p for p in players if p["position"] == position], key=lambda p: p["adp"] if p["adp"] is not None else 1e9)
                for start in range(0, len(members), GROUP):
                    group = members[start:start + GROUP]
                    outcomes = [(p["actual_ppr"], p.get("weekly_ppr")) for p in group]
                    for p, (actual, weekly) in zip(group, [outcomes[i] for i in rng.permutation(len(group))]):
                        p["actual_ppr"], p["weekly_ppr"] = actual, weekly
            (out / f"projections_{season}_v1.json").write_text(json.dumps(data))


def worlds():
    found = {"validated": PROCESSED, "refit": PROCESSED / "routed" / "current", "refit_routed": PROCESSED / "routed" / "routed"}
    found.update({f"perturb_p{k}": PROCESSED / "perturb" / f"p{k}" for k in range(N_PERTURBED)})
    found.update({f"shuffled_s{k}": PROCESSED / "shuffled" / f"s{k}" for k in range(N_SHUFFLED)})
    return {name: path for name, path in found.items() if (path / "projections_2021_v1.json").exists()}


def run_world(path, seeds, arms="reach", tier_gap=None):
    command = ["dotnet", "run", "-c", "Release", "--no-build", "--project", str(ROOT / "csharp" / "src" / "DraftBot.Sim"), "--", "world-sweep",
               "--data", str(path), "--seeds", str(seeds), "--first-seed", "100", "--noise", "1", "--arms", arms]
    if tier_gap is not None:
        command += ["--tier-gap", str(tier_gap)]
    out = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        if line.startswith("RESULT\t"):
            _, arm, pd_, pse, td, tse, padp, tadp, seasons = line.split("\t")
            rows.append(dict(arm=arm, points=float(pd_), points_se=float(pse), title=float(td), title_se=float(tse), points_vs_adp=float(padp), title_vs_adp=float(tadp),
                             by_season=[float(x) for x in seasons.split(",")]))
    return rows


def summarize(results):
    table = results.pivot(index="arm", columns="world", values="points")
    title = results.pivot(index="arm", columns="world", values="title")
    summary = pd.DataFrame({"mean_points": table.mean(axis=1), "sd_points": table.std(axis=1), "worlds_ahead": (table > 0).sum(axis=1), "worlds_behind": (table < 0).sum(axis=1),
                            "mean_title": title.mean(axis=1), "worlds_title_ahead": (title > 0).sum(axis=1)})
    return table, title, summary.sort_values("mean_points", ascending=False)


if __name__ == "__main__":
    if "--make-only" in sys.argv or "--make" in sys.argv:
        make_perturbed()
        make_shuffled()
    if "--make-only" in sys.argv:
        sys.exit()
    seeds = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 40
    arms = sys.argv[sys.argv.index("--arms") + 1] if "--arms" in sys.argv else "reach"
    if "--tiers" in sys.argv:
        gaps = [0.03, 0.05, 0.1, 0.2, 0.4]
        edge = {}
        for name, path in worlds().items():
            for gap in gaps:
                headline = next(r for r in run_world(path, seeds, "tiers", gap) if r["arm"].startswith("adopted"))
                edge[(name, gap)] = (headline["points_vs_adp"], headline["title_vs_adp"])
        points = pd.DataFrame({gap: {w: edge[(w, gap)][0] for w in worlds()} for gap in gaps})
        title = pd.DataFrame({gap: {w: edge[(w, gap)][1] for w in worlds()} for gap in gaps})
        print("Adopted advisor's edge over ADP (points), by world and tier gap (x position RMSE)")
        print(points.round(1).to_string())
        print()
        print("mean points / title pp by tier gap")
        print(pd.DataFrame({"points": points.mean(), "title": title.mean()}).round(2).T.to_string())
        sys.exit()
    wanted = sys.argv[sys.argv.index("--worlds") + 1].split(",") if "--worlds" in sys.argv else None
    rows = []
    for name, path in worlds().items():
        if wanted and name not in wanted:
            continue
        for row in run_world(path, seeds, arms):
            rows.append(dict(world=name, **row))
        print(f"{name}: done", flush=True)
    results = pd.DataFrame(rows)
    results.to_csv(PROCESSED / ("world_sweep.csv" if arms == "reach" else f"world_sweep_{arms}.csv"), index=False)
    points, title, summary = summarize(results)
    pd.set_option("display.width", 250)
    print("\nPoints margin against the adopted advisor, by world (positive = ahead of the adopted settings)")
    print(points.round(0).astype(int).loc[summary.index].to_string())
    print("\nSummary (points mean / SD across worlds, worlds ahead / behind, title mean pp, worlds ahead on title)")
    print(summary.round(1).to_string())
