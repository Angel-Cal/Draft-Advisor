"""Are the RB busts in rounds 3-6 injuries or genuine underperformance? (LOG.md, 2026-10-30)

RBs and WRs with ADP 25-72, seasons 2015-2025 (FantasyPros ADP exports), outcomes from the seasonal stats. Each player's shortfall against the ADP curve (fitted on the other seasons) is split into availability
(games missed, valued at the expected rate), rate (points per game over the expected games) and their interaction; the rate is split again into opportunity (touches per game against the rank band's norm) and
efficiency (points per touch). Also: the share of busts (under 70% of the curve) that missed 4+ games, and the shortfall of players who missed at most one game.

Run: python src/evaluation/rb_availability.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
ROOT = str(Path(__file__).parent.parent.parent) + "/"
sys.path.insert(0, ROOT)
from src.draft.market_fallback import fit_position_curves, load_history

hist = load_history(range(2015, 2026))
seas = pd.read_parquet(ROOT + "data/raw/seasonal_20_25.parquet")
seas = seas[seas.player_id.notna() & seas.position.isin(["RB", "WR"])][["player_id", "season", "games", "carries", "targets", "fantasy_points_ppr"]]
seas = seas.drop_duplicates(["player_id", "season"])
rows = []
for y in range(2015, 2026):
    a = pd.read_csv(ROOT + f"data/external/adp_{y}.csv")[["player_id", "position", "adp"]].sort_values("adp").drop_duplicates("player_id")
    a = a[a.position.isin(["RB", "WR"])].copy()
    a["prank"] = a.groupby("position")["adp"].rank(method="first"); a["season"] = y
    curves = fit_position_curves(hist[hist.season != y])
    a["curve"] = [curves[p].predict([r])[0] for p, r in zip(a.position, a.prank)]
    a = a.merge(seas[seas.season == y], on=["player_id", "season"], how="left")
    rows.append(a)
D = pd.concat(rows)
D[["games", "carries", "targets", "fantasy_points_ppr"]] = D[["games", "carries", "targets", "fantasy_points_ppr"]].fillna(0)
season_games = lambda y: 16 if y <= 2020 else 17
D["games"] = np.minimum(D.games, D.season.map(season_games))
D["missed"] = D.season.map(season_games) - D.games
D["touches"] = D.carries + D.targets
R = D[(D.adp >= 25) & (D.adp <= 72)].copy()

out = {}
for pos in ("RB", "WR"):
    P = R[R.position == pos].copy()
    played = P[P.games >= 4]                                            # the expectations come from players who played
    G = played.games.mean() / 1.0                                      # expected games of a draftable player in this range
    # expected rate per game and touches per game by position rank band, fitted on all seasons
    P["band"] = pd.cut(P.prank, [0, 12, 24, 36, 100], labels=False)
    played = P[P.games >= 4]
    tpg_band = (played.touches / played.games).groupby(played.band).mean()
    ppt_band = (played.fantasy_points_ppr / played.touches.replace(0, np.nan)).groupby(played.band).mean()
    P["exp_tpg"] = P.band.map(tpg_band); P["exp_ppt"] = P.band.map(ppt_band)
    P["exp_ppg"] = P.curve / G
    P["ppg"] = np.where(P.games > 0, P.fantasy_points_ppr / P.games.replace(0, np.nan), 0.0)
    P["avail"] = (P.games - G) * P.exp_ppg                              # games missed (or extra), valued at the expected rate
    P["rate"] = G * (P.ppg - P.exp_ppg)                                 # rate shortfall over the expected games
    P["inter"] = (P.games - G) * (P.ppg - P.exp_ppg)
    P["total"] = P.fantasy_points_ppr - P.curve
    P["check"] = P.avail + P.rate + P.inter
    P["tpg"] = np.where(P.games > 0, P.touches / P.games.replace(0, np.nan), 0.0)
    P["ppt"] = np.where(P.touches > 0, P.fantasy_points_ppr / P.touches.replace(0, np.nan), 0.0)
    P["opp"] = G * (P.tpg - P.exp_tpg) * P.exp_ppt                      # opportunity: touches per game below/above the band norm, at the band's points per touch
    P["eff"] = G * P.tpg * (P.ppt - P.exp_ppt)                          # efficiency: points per touch below/above the norm, at the player's touches
    P["injured"] = P.missed >= 4
    P["healthy"] = P.missed <= 1
    P["bust"] = P.fantasy_points_ppr < 0.7 * P.curve
    P["group"] = P.season.map(lambda y: "2015-18" if y <= 2018 else "2019" if y == 2019 else "2020-23" if y <= 2023 else "2024-25")
    out[pos] = (P, G)

pd.set_option("display.width", 220)
for pos in ("RB", "WR"):
    P, G = out[pos]
    print(f"\n=== {pos}, ADP 25-72; expected games {G:.1f}")
    g = P.groupby("group")
    t = pd.DataFrame({"n": g.size(), "shortfall": g.total.mean(), "availability": g.avail.mean(), "rate": g.rate.mean(), "interaction": g.inter.mean(),
                      "games missed": g.missed.mean(), "missed4+": g.injured.mean(), "healthy(<=1)": g.healthy.mean(), "bust": g.bust.mean()}).round(2)
    print(t.to_string())
    print("rate split (opportunity = touches/game, efficiency = points/touch), players with 4+ games:")
    Q = P[P.games >= 4]; gq = Q.groupby("group")
    print(pd.DataFrame({"n": gq.size(), "rate": gq.rate.mean(), "opportunity": gq.opp.mean(), "efficiency": gq.eff.mean(), "touches/g": gq.tpg.mean(), "pts/touch": gq.ppt.mean()}).round(2).to_string())
    print("busts only: share who missed 4+ games / played 14+ games / in between")
    B = P[P.bust]; gb = B.groupby("group")
    print(pd.DataFrame({"n busts": gb.size(), "missed4+": gb.injured.mean(), "missed<=1": gb.healthy.mean()}).round(2).to_string())
    print("healthy players (missed <=1): mean shortfall vs curve")
    H = P[P.healthy]; print(H.groupby("group").total.agg(["size", "mean"]).round(1).T.to_string())

P, G = out["RB"]
a = P[P.group == "2020-23"]; b = P[P.group != "2020-23"]
print("\nRB 2020-23 vs all other seasons: p-values (Welch for amounts, Fisher for shares)")
for col in ("total", "avail", "rate", "inter"):
    print(f"  {col:8s}{a[col].mean():8.1f} vs {b[col].mean():8.1f}  p = {stats.ttest_ind(a[col], b[col], equal_var=False).pvalue:.3f}")
for col in ("injured",):
    t = [[int(a[col].sum()), int((~a[col]).sum())], [int(b[col].sum()), int((~b[col]).sum())]]
    print(f"  missed 4+: {a[col].mean():.2f} vs {b[col].mean():.2f}  p = {stats.fisher_exact(t)[1]:.3f}")

print("\n=== RB vs WR in ADP 25-72, all seasons 2015-2025: availability")
for pos in ("RB", "WR"):
    P, G = out[pos]
    print(pos, "n", len(P), "mean games missed", round(P.missed.mean(), 2), "share missing 4+", round(P.injured.mean(), 3), "share healthy (<=1)", round(P.healthy.mean(), 3))
rb, wr = out["RB"][0], out["WR"][0]
t = [[int(rb.injured.sum()), int((~rb.injured).sum())], [int(wr.injured.sum()), int((~wr.injured).sum())]]
print("missing 4+ games, RB vs WR: Fisher p =", round(stats.fisher_exact(t)[1], 3), "| games missed Welch p =", round(stats.ttest_ind(rb.missed, wr.missed, equal_var=False).pvalue, 3))
print("by season, share missing 4+ (RB / WR):")
print(pd.DataFrame({"RB": rb.groupby("season").injured.mean(), "WR": wr.groupby("season").injured.mean()}).round(2).T.to_string())
print("COVID check, RB share missing 4+: 2020-21", round(rb[rb.season.isin([2020, 2021])].injured.mean(), 2), "| 2022-23", round(rb[rb.season.isin([2022, 2023])].injured.mean(), 2), "| 2015-18", round(rb[rb.season <= 2018].injured.mean(), 2), "| 2019, 2024, 2025", round(rb[rb.season.isin([2019, 2024, 2025])].injured.mean(), 2))
