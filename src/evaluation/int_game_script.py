"""Do interceptions carry positive fantasy signal for QBs through game script? (user's hypothesis, 2026-11-04; evidence only, no model test)

Mechanism: an interception costs 2 PPR points and a possession, but it worsens the score, and a trailing team passes more, so the QB may get
the points back later in the game. The confound is reverse causation: a team that trails for other reasons passes more and so throws more
interceptions, and a full-game correlation between interceptions and points cannot tell the two apart.

Game level (play-by-play 2014-2025, regular season, the team's starter = most first-half dropbacks, 8 or more): the treatment is the starter's
FIRST-HALF interceptions; outcomes are his second-half dropbacks and fantasy points, and the full-game points. Controls are known before the
interceptions: the team's Vegas spread and the game total, the QB's points per dropback in his other games that season, first-half dropbacks,
season dummies. Adding the halftime score margin shows how much of the effect runs through the score (game script). SEs: bootstrap over QBs.

Season level (seasonal stats 2014-2025, QBs with 200+ attempts): does the interception rate predict next season's points per game beyond the
other prior-season rates, how persistent is it, and do draftable QBs with a high prior rate beat or trail the ADP curve (the market view)?
Writes nothing; run: python src/evaluation/int_game_script.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import load_history
from src.evaluation.blend_test import curve_points

ROOT = Path(__file__).parent.parent.parent
RAW = ROOT / "data" / "raw"
MIN_H1_DROPBACKS = 8
N_BOOT = 1000
SEED = 0
PBP_COLUMNS = ["game_id", "season", "week", "season_type", "posteam", "home_team", "game_half", "passer_player_id", "rusher_player_id",
               "qb_dropback", "qb_scramble", "interception", "passing_yards", "rushing_yards", "pass_touchdown", "rush_touchdown",
               "fumble_lost", "fumbled_1_player_id", "spread_line", "total_line", "total_home_score", "total_away_score", "play_type"]


def qb_play_points(pbp):
    """Long table: one row per (play, credited player) with that player's PPR points, dropback and interception on the play."""
    p = pbp.fillna({c: 0 for c in ["passing_yards", "rushing_yards", "pass_touchdown", "rush_touchdown", "interception", "fumble_lost", "qb_dropback", "qb_scramble"]})
    passer = p[p["passer_player_id"].notna()].assign(
        player=lambda x: x["passer_player_id"], pts=lambda x: 0.04 * x["passing_yards"] + 4 * x["pass_touchdown"] - 2 * x["interception"],
        db=lambda x: x["qb_dropback"], ints=lambda x: x["interception"])
    rusher = p[p["rusher_player_id"].notna()].assign(
        player=lambda x: x["rusher_player_id"], pts=lambda x: 0.1 * x["rushing_yards"] + 6 * x["rush_touchdown"],
        db=lambda x: x["qb_scramble"], ints=0.0)
    fumble = p[(p["fumble_lost"] == 1) & p["fumbled_1_player_id"].notna()].assign(player=lambda x: x["fumbled_1_player_id"], pts=-2.0, db=0.0, ints=0.0)
    keep = ["game_id", "season", "posteam", "game_half", "player", "pts", "db", "ints"]
    return pd.concat([passer[keep], rusher[keep], fumble[keep]], ignore_index=True)


def game_rows():
    """One row per team-game: the starter's first-half interceptions, second-half and full-game outcomes, and the pre-treatment controls."""
    pbp = pd.read_parquet(RAW / "pbp_20_25.parquet", columns=PBP_COLUMNS)
    pbp = pbp[(pbp["season_type"] == "REG") & pbp["posteam"].notna()]
    plays = qb_play_points(pbp)
    by_half = plays.groupby(["game_id", "season", "posteam", "player", "game_half"])[["pts", "db", "ints"]].sum().unstack("game_half", fill_value=0)
    by_half.columns = [f"{v}_{h}" for v, h in by_half.columns]
    by_half = by_half.reset_index()
    for c in ["pts_Overtime", "db_Overtime", "ints_Overtime"]:
        if c not in by_half:
            by_half[c] = 0.0
    starters = by_half.sort_values("db_Half1", ascending=False).drop_duplicates(["game_id", "posteam"])
    starters = starters[starters["db_Half1"] >= MIN_H1_DROPBACKS].copy()
    starters["game_pts"] = starters[["pts_Half1", "pts_Half2", "pts_Overtime"]].sum(axis=1)
    starters["game_db"] = starters[["db_Half1", "db_Half2", "db_Overtime"]].sum(axis=1)

    team_h2 = pbp[pbp["game_half"] == "Half2"].groupby(["game_id", "posteam"]).agg(
        team_db_h2=("qb_dropback", "sum"), team_plays_h2=("play_type", lambda s: s.isin(["pass", "run"]).sum())).reset_index()
    games = pbp.groupby("game_id").agg(home=("home_team", "first"), spread_line=("spread_line", "first"), total_line=("total_line", "first")).reset_index()
    half = pbp[pbp["game_half"] == "Half1"].groupby("game_id")[["total_home_score", "total_away_score"]].max().reset_index()
    d = starters.merge(team_h2, on=["game_id", "posteam"], how="left").merge(games, on="game_id").merge(half, on="game_id", how="left")
    home = d["posteam"] == d["home"]
    d["spread"] = np.where(home, d["spread_line"], -d["spread_line"])          # points the team is favoured by
    d["half_margin"] = np.where(home, d["total_home_score"] - d["total_away_score"], d["total_away_score"] - d["total_home_score"])
    season_tot = d.groupby(["season", "player"])[["game_pts", "game_db"]].transform("sum")
    d["skill"] = (season_tot["game_pts"] - d["game_pts"]) / (season_tot["game_db"] - d["game_db"])
    d["benched"] = (d["db_Half2"] == 0) & (d["team_db_h2"] >= 5)
    d["pass_rate_h2"] = d["team_db_h2"] / d["team_plays_h2"]
    d["pts_h2_before_ints"] = d["pts_Half2"] + 2 * d["ints_Half2"]
    d["int1"] = (d["ints_Half1"] == 1).astype(float)
    d["int2"] = (d["ints_Half1"] >= 2).astype(float)
    return d.replace([np.inf, -np.inf], np.nan).dropna(subset=["skill", "spread", "total_line", "half_margin"])


def ols(d, y, x):
    X = np.column_stack([np.ones(len(d))] + [d[c].values for c in x] + [(d["season"] == s).values.astype(float) for s in sorted(d["season"].unique())[1:]])
    return np.linalg.lstsq(X, d[y].values, rcond=None)[0][1:1 + len(x)]


def fit(d, y, x, rng):
    """Coefficients of x with a 90% bootstrap interval that resamples whole QBs."""
    beta = ols(d, y, x)
    groups = {p: g for p, g in d.groupby("player")}
    keys = list(groups)
    boots = np.array([ols(pd.concat([groups[k] for k in rng.choice(keys, len(keys))]), y, x) for _ in range(N_BOOT)])
    return beta, np.percentile(boots, 5, axis=0), np.percentile(boots, 95, axis=0)


def game_report(d, rng):
    print(f"Game level: {len(d)} starter games 2014-2025; first-half interceptions 0 / 1 / 2+: "
          f"{(d['ints_Half1'] == 0).mean():.0%} / {d['int1'].mean():.0%} / {d['int2'].mean():.0%}")
    raw = d.groupby(d["ints_Half1"].clip(upper=2))[["db_Half2", "pts_Half2", "game_pts", "half_margin", "benched"]].mean()
    print("raw means by first-half interceptions (2 = 2+):\n" + raw.round(2).to_string())
    pre = ["spread", "total_line", "skill", "db_Half1"]
    outcomes = [("db_Half2", "2nd-half dropbacks"), ("pass_rate_h2", "team 2nd-half pass rate"), ("pts_h2_before_ints", "2nd-half points before its own INT penalty"),
                ("pts_Half2", "2nd-half points"), ("game_pts", "full-game points (incl. the INT penalty)"), ("benched", "benched in the 2nd half")]
    print(f"\nEffect of the starter's first-half interceptions (vs none), controls: {', '.join(pre)}, season; 90% QB-bootstrap interval")
    print(f"{'outcome':<46}{'1 INT':>24}{'2+ INT':>24}{'1 INT, + halftime margin':>28}{'margin per point':>18}")
    for y, label in outcomes:
        dd = d.dropna(subset=[y]).assign(benched=lambda x: x["benched"].astype(float))
        b, lo, hi = fit(dd, y, ["int1", "int2"] + pre, rng)
        bm, lom, him = fit(dd, y, ["int1", "int2", "half_margin"] + pre, rng)
        cell = lambda i, b, lo, hi: f"{b[i]:+.2f} [{lo[i]:+.2f}, {hi[i]:+.2f}]"
        print(f"{label:<46}{cell(0, b, lo, hi):>24}{cell(1, b, lo, hi):>24}{cell(0, bm, lom, him):>28}{bm[2]:>+18.3f}")
    b, lo, hi = fit(d, "half_margin", ["int1", "int2"] + pre, rng)
    print(f"halftime margin: 1 INT {b[0]:+.1f} [{lo[0]:+.1f}, {hi[0]:+.1f}], 2+ INT {b[1]:+.1f} [{lo[1]:+.1f}, {hi[1]:+.1f}] points")


def season_rows():
    s = pd.read_parquet(RAW / "seasonal_20_25.parquet")
    s = s[(s["season_type"] == "REG") & (s["position"] == "QB")].copy()
    s["ppg"] = s["fantasy_points_ppr"] / s["games"]
    s["int_rate"] = s["passing_interceptions"] / s["attempts"]
    s["td_rate"] = s["passing_tds"] / s["attempts"]
    s["ypa"] = s["passing_yards"] / s["attempts"]
    s["att_g"] = s["attempts"] / s["games"]
    s["rush_g"] = s["rushing_yards"] / s["games"]
    nxt = s[["player_id", "season", "ppg", "attempts", "games", "int_rate", "td_rate", "fantasy_points_ppr"]].copy()
    nxt["season"] -= 1
    d = s[s["attempts"] >= 200].merge(nxt.add_suffix("_next").rename(columns={"player_id_next": "player_id", "season_next": "season"}), on=["player_id", "season"], how="left")
    d["kept_job"] = (d["attempts_next"].fillna(0) >= 200).astype(float)
    return d.rename(columns={"player_id": "player"})


def season_report(d, rng):
    print(f"\nSeason level: {len(d)} QB seasons with 200+ attempts, 2014-2024 -> next season")
    both = d.dropna(subset=["int_rate_next"])
    both = both[both["attempts_next"] >= 200]
    print("persistence (r with next season, both 200+ attempts): " + ", ".join(
        f"{c} {np.corrcoef(both[c], both[c + '_next'])[0, 1]:.2f}" for c in ["int_rate", "td_rate", "ppg"]))
    z = lambda x: (x - x.mean()) / x.std()
    d = d.assign(**{f"z_{c}": z(d[c]) for c in ["int_rate", "td_rate", "ypa", "att_g", "rush_g", "ppg"]})
    ctrl = ["z_ppg", "z_td_rate", "z_ypa", "z_att_g", "z_rush_g"]
    for y, label, rows in [("ppg_next", "next-season points per game (played 4+ games)", d[d["games_next"] >= 4]),
                           ("kept_job", "kept the job (200+ attempts next season)", d)]:
        b0, lo0, hi0 = fit(rows, y, ["z_int_rate"], rng)
        b, lo, hi = fit(rows, y, ["z_int_rate"] + ctrl, rng)
        print(f"{label:<48} per +1 SD interception rate: alone {b0[0]:+.3f} [{lo0[0]:+.3f}, {hi0[0]:+.3f}], "
              f"with prior ppg/TD/YPA/att/rush {b[0]:+.3f} [{lo[0]:+.3f}, {hi[0]:+.3f}]  (n {len(rows)})")


def market_report(d, rng):
    history = load_history(range(2015, 2026))
    rows = []
    for season in range(2016, 2026):
        curve = curve_points(season, history)
        adp = pd.read_csv(ROOT / "data" / "external" / f"adp_{season}.csv")[["player_id", "position", "adp"]]
        adp = adp[(adp["position"] == "QB") & (adp["adp"] <= 150)]
        adp["curve"] = adp["player_id"].map(curve)
        prior = d[d["season"] == season - 1][["player", "int_rate", "td_rate", "ppg", "fantasy_points_ppr_next"]]
        rows.append(adp.merge(prior, left_on="player_id", right_on="player").assign(season=season))
    m = pd.concat(rows, ignore_index=True).dropna(subset=["curve"])
    m["resid"] = m["fantasy_points_ppr_next"].fillna(0) - m["curve"]
    z = lambda x: (x - x.mean()) / x.std()
    m = m.assign(z_int_rate=z(m["int_rate"]), z_ppg=z(m["ppg"]), z_td_rate=z(m["td_rate"]))
    b0, lo0, hi0 = fit(m, "resid", ["z_int_rate"], rng)
    b, lo, hi = fit(m, "resid", ["z_int_rate", "z_ppg", "z_td_rate"], rng)
    top, bottom = m[m["int_rate"] >= m["int_rate"].quantile(2 / 3)], m[m["int_rate"] <= m["int_rate"].quantile(1 / 3)]
    print(f"\nMarket: draftable QBs (ADP <= 150) 2016-2025 with 200+ prior attempts, n {len(m)}; actual season PPR minus the ADP curve")
    print(f"per +1 SD prior interception rate: alone {b0[0]:+.1f} [{lo0[0]:+.1f}, {hi0[0]:+.1f}], with prior ppg and TD rate {b[0]:+.1f} [{lo[0]:+.1f}, {hi[0]:+.1f}] PPR")
    print(f"top-third prior interception rate {top['resid'].mean():+.1f} (n {len(top)}), bottom third {bottom['resid'].mean():+.1f} (n {len(bottom)})")


if __name__ == "__main__":
    rng = np.random.default_rng(SEED)
    game_report(game_rows(), rng)
    seasons = season_rows()
    season_report(seasons, rng)
    market_report(seasons, rng)
