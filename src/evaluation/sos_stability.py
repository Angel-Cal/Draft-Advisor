"""Is strength of schedule predictable before the season? Stability of fantasy points allowed by position, 2014-2025."""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import ROOT

FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA"}
d = pd.read_parquet(ROOT / "data" / "raw" / "weekly_20_25.parquet",
                    columns=["season", "week", "season_type", "position", "team", "opponent_team", "fantasy_points_ppr"])
d = d[(d.season_type == "REG") & d.position.isin(["QB", "RB", "WR", "TE"])].copy()
d["team"] = d.team.replace(FIX); d["opponent_team"] = d.opponent_team.replace(FIX)

# one row per game and position: points the offense scored = points the defense allowed
g = d.groupby(["season", "week", "position", "team", "opponent_team"], as_index=False).fantasy_points_ppr.sum()
g["ratio"] = g.fantasy_points_ppr / g.groupby(["season", "position"]).fantasy_points_ppr.transform("mean")

allowed = g.groupby(["season", "position", "opponent_team"]).ratio.agg(["sum", "count"]).reset_index().rename(columns={"opponent_team": "dfn"})
allowed["per_game"] = allowed["sum"] / allowed["count"]
scored = g.groupby(["season", "position", "team"]).ratio.mean().rename("per_game").reset_index()

print("1) Year-to-year correlation of per-game ratio (defense allowed vs offense scored, for reference)")
for pos in ["QB", "RB", "WR", "TE"]:
    a = allowed[allowed.position == pos].pivot(index="dfn", columns="season", values="per_game")
    o = scored[scored.position == pos].pivot(index="team", columns="season", values="per_game")
    ra = np.mean([a[s].corr(a[s + 1]) for s in range(2014, 2025)])
    ro = np.mean([o[s].corr(o[s + 1]) for s in range(2014, 2025)])
    print(f"  {pos}: defense r={ra:.2f}   offense r={ro:.2f}")

print("\n2) Preseason SOS (opponents' last-season allowed) vs realized SOS (opponents' same-season allowed, games vs this team left out)")
key = allowed.set_index(["season", "position", "dfn"])
rows = []
for (s, pos, team), games in g[g.season > 2014].groupby(["season", "position", "team"]):
    pre, real = [], []
    for opp in games.opponent_team:
        prev = key["per_game"].get((s - 1, pos, opp))
        cur = key.loc[(s, pos, opp)]
        vs = games.loc[games.opponent_team == opp, "ratio"].sum(); n = (games.opponent_team == opp).sum()
        if prev is None or cur["count"] - n < 1: continue
        pre.append(prev); real.append((cur["sum"] - vs) / (cur["count"] - n))
    rows.append((s, pos, team, np.mean(pre), np.mean(real), games.ratio.mean()))
r = pd.DataFrame(rows, columns=["season", "position", "team", "pre", "real", "offense"])
for pos in ["QB", "RB", "WR", "TE"]:
    x = r[r.position == pos]
    c = np.mean([x[x.season == s].pre.corr(x[x.season == s].real) for s in range(2015, 2026)])
    c_off = np.mean([x[x.season == s].real.corr(x[x.season == s].offense) for s in range(2015, 2026)])
    print(f"  {pos}: r(pre, real)={c:.2f}  SD pre={x.pre.std():.3f}  SD real={x.real.std():.3f}  "
          f"r(real SOS, team's own per-game ratio)={c_off:.2f}")
print("\nSD is a share of the league-average room score; x 250 PPR gives a typical starter's season swing.")
