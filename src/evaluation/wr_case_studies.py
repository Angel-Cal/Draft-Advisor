"""Single-player and list tools behind the WR case studies (K.Allen 2024, W.Robinson 2025-2026; LOG.md, 2026-10-28).

  python src/evaluation/wr_case_studies.py quality W.Robinson K.Allen   value-weighted targets by season: depth, air yards, red zone, deep targets, expected points
  python src/evaluation/wr_case_studies.py attribute W.Robinson         what drives a live 2026 WR projection: feature contributions and counterfactuals
  python src/evaluation/wr_case_studies.py gaps                         WRs the model rates 30+ PPR above the ADP curve: slope by gap size, the healthy over-projections, the live 2026 list

Reads the cached raw files and the model data; writes nothing.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.gap_reliability import load_rows, slope_interval
from src.evaluation.target_competition import RAW, add_context, add_measures, live_2026_pool, load_start_roster, load_weekly

GAP = 30            # PPR above the ADP curve that counts as "significantly more" (about one standard deviation)
HEALTHY_GAMES = 9   # fewer games than this and the season says little about the projection


def player_id(name):
    """The WR with this abbreviated name (the one with the most targets if several share it)."""
    s = pd.read_parquet(RAW / "seasonal_20_25.parquet", columns=["player_id", "player_name", "position", "targets"])
    s = s[(s["player_name"] == name) & (s["position"] == "WR")].groupby("player_id")["targets"].sum()
    if s.empty:
        raise SystemExit(f"no WR named {name}")
    return s.idxmax()


def quality(names):
    """Per season: targets and what they were worth. Depth and air yards come from play by play, expected points from ff_opportunity."""
    cols = ["season", "season_type", "posteam", "pass", "receiver_player_id", "air_yards", "yardline_100", "qb_spike", "two_point_attempt"]
    p = pd.read_parquet(RAW / "pbp_20_25.parquet", columns=cols)
    p = p[(p["season_type"] == "REG") & (p["pass"] == 1) & p["air_yards"].notna() & (p["qb_spike"] != 1) & (p["two_point_attempt"] != 1) & p["receiver_player_id"].notna()].copy()
    p["rz"], p["gl"], p["deep"] = p["yardline_100"] <= 20, p["yardline_100"] <= 10, p["air_yards"] >= 20
    seasonal = pd.read_parquet(RAW / "seasonal_20_25.parquet", columns=["player_id", "season", "games", "targets", "receiving_yards", "receiving_tds", "wopr", "fantasy_points_ppr"])
    xfp = pd.read_parquet(RAW / "ff_opportunity_14_25.parquet").groupby(["player_id", "season"])["rec_fantasy_points_exp"].sum().rename("xfp")
    for name in names:
        pid = player_id(name)
        rows = []
        for season in sorted(p["season"].unique()):
            mine = p[(p["receiver_player_id"] == pid) & (p["season"] == season)]
            if mine.empty:
                continue
            team_plays = p[(p["posteam"] == mine["posteam"].mode().iloc[0]) & (p["season"] == season)]
            s = seasonal[(seasonal["player_id"] == pid) & (seasonal["season"] == season)].iloc[0]
            rows.append({"season": season, "team": mine["posteam"].mode().iloc[0], "G": int(s["games"]), "targets": len(mine), "aDOT": mine["air_yards"].mean(),
                         "air_yds": mine["air_yards"].sum(), "air_share": mine["air_yards"].sum() / team_plays["air_yards"].sum(), "deep": int(mine["deep"].sum()),
                         "deep_share": mine["deep"].sum() / team_plays["deep"].sum(), "rz": int(mine["rz"].sum()), "rz_share": mine["rz"].sum() / team_plays["rz"].sum(),
                         "goal": int(mine["gl"].sum()), "yds/tgt": s["receiving_yards"] / s["targets"], "wopr": s["wopr"], "xfp": xfp.get((pid, season), np.nan),
                         "xfp/tgt": xfp.get((pid, season), np.nan) / s["targets"], "ppr/tgt": s["fantasy_points_ppr"] / s["targets"], "PPR": s["fantasy_points_ppr"]})
        print(f"\n{name}")
        print(pd.DataFrame(rows).round(2).to_string(index=False))


def attribute(name):
    """What drives the live 2026 projection of a WR: contributions of each input (PPR points) and counterfactuals that change one group of inputs."""
    import lightgbm as lgb
    from src.models.predict import drop_meta, drop_season, load_data, save_metadata
    from src.models.train import drop_non_features, split_positions
    prediction_df, training_df, _, _, wr_params, _ = load_data()
    wr_train, wr_pred = split_positions(training_df)[2], split_positions(prediction_df)[2]
    wr_pred = drop_season(wr_pred)
    meta = save_metadata(wr_pred)
    wr_pred = drop_meta(wr_pred)
    newest = wr_train["season"].max()
    older, latest = wr_train[wr_train["season"] < newest], wr_train[wr_train["season"] == newest]
    x_old, y_old, x_new, y_new = drop_non_features(older), older["target_ppr"], drop_non_features(latest), latest["target_ppr"]
    cols = x_old.columns
    idx = meta.index[meta["player_name"] == name]
    if len(idx) == 0:
        raise SystemExit(f"{name} is not in the 2026 prediction rows")
    row = wr_pred.loc[[idx[0]]][cols]
    last = wr_train[(wr_train["player_name"] == name) & (wr_train["season"] == newest)]          # the row built from his previous season's stats
    cases = {"as is": row}
    air = [c for c in cols if any(k in c for k in ("air_yards", "wopr", "racr"))]
    production = [c for c in cols if any(k in c for k in ("fantasy_points", "receiving_yards", "receptions", "targets", "target_share", "air_yards", "wopr", "racr", "receiving_epa", "first_downs"))]
    if len(last) == 1:
        cases["air-yards, WOPR and RACR inputs set to his previous-season row"] = row.assign(**dict(zip(air, last[air].values[0])))
        cases["all production inputs set to his previous-season row"] = row.assign(**dict(zip(production, last[production].values[0])))
    if "depth_tier_wk1" in cols:
        for tier in (2, 3):
            cases[f"depth_tier_wk1 = {tier}"] = row.assign(depth_tier_wk1=tier)
    x_all, y_all = pd.concat([x_old, x_new]), pd.concat([y_old, y_new])
    projections = {k: [] for k in cases}
    contributions = []
    for seed in range(5):
        params = dict(wr_params, random_state=seed)
        stopped = lgb.LGBMRegressor(**params)
        stopped.fit(x_old, y_old, eval_set=[(x_new, y_new)], eval_metric="rmse", callbacks=[lgb.early_stopping(50, verbose=False)])
        model = lgb.LGBMRegressor(**dict(params, n_estimators=max(1, stopped.best_iteration_)))
        model.fit(x_all, y_all)
        for k, v in cases.items():
            projections[k].append(model.predict(v)[0])
        contributions.append(model.booster_.predict(row, pred_contrib=True)[0])
    c = pd.Series(np.mean(contributions, axis=0), index=list(cols) + ["(baseline: average WR)"])
    print(f"\n{name}: 2026 projection {np.mean(projections['as is']):.1f} (5 seeds)\nlargest contributions, PPR points:")
    print(pd.concat([c.sort_values(ascending=False).head(8), c.sort_values().head(4)]).round(1).to_string())
    print("\ncounterfactuals (one group of inputs changed, model unchanged):")
    for k, v in projections.items():
        print(f"  {np.mean(v):6.1f}  {k}")


def gaps():
    """The WRs the model rates GAP+ PPR above the ADP curve: how reliable those gaps are, the healthy ones it over-projected, and the live 2026 list."""
    weekly, roster = load_weekly(), load_start_roster()
    d = load_rows()
    d = add_context(add_measures(d[(d["position"] == "WR") & d["in_top_adp"]].copy(), weekly, roster), weekly, roster)
    rng = np.random.default_rng(0)
    print(f"{len(d)} draftable WR player-seasons, 2022-2025. Slope of (actual - ADP curve) on (model - curve): 1 means the gap is right, 0 means the curve is.")
    print(f"{'gap band':<16}{'n':>4}{'mean gap':>10}{'actual - ADP':>14}{'slope':>7}{'90% interval':>16}")
    for label, m in [("all", d["gap"].notna()), (f"{GAP}+", d["gap"] >= GAP), ("10 to 30", (d["gap"] >= 10) & (d["gap"] < GAP)), ("-10 to 10", d["gap"].abs() < 10),
                     ("-30 to -10", (d["gap"] <= -10) & (d["gap"] > -GAP)), (f"-{GAP} or less", d["gap"] <= -GAP)]:
        g = d[m]
        b, lo, hi = slope_interval(g, rng)
        print(f"{label:<16}{len(g):>4}{g['gap'].mean():>+10.1f}{(g['actual_ppr'] - g['curve']).mean():>+14.1f}{b:>7.2f}{f'{lo:.2f} to {hi:.2f}':>16}")
    big = d[d["gap"] >= GAP]
    healthy = big[big["G"] >= HEALTHY_GAMES]
    print(f"\n{len(big)} rows with a gap of {GAP}+: mean over-projection {big['over'].mean():+.1f}; {len(big) - len(healthy)} missed most of the season and are left out below")
    over = healthy[healthy["over"] > 0].sort_values("over", ascending=False)
    print(f"healthy ({HEALTHY_GAMES}+ games): {len(healthy)} rows, mean over-projection {healthy['over'].mean():+.1f}; {len(over)} were over-projected:")
    t = over[["player_name", "season", "from", "to", "age", "oos_pred_ppr", "curve", "actual_ppr", "gap", "over", "G", "rookie_r1", "absence_share"]].copy()
    print(t.round(2).to_string(index=False))
    live = live_2026_pool(weekly, roster)
    live = live[live["gap"] >= GAP].sort_values("gap", ascending=False)
    print(f"\nlive 2026 WRs {GAP}+ above the ADP curve:")
    print(live[["player_name", "from", "team", "adp", "projected_ppr", "curve", "gap", "rookie_r1", "absence_share"]].round(2).to_string(index=False))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "quality" and len(sys.argv) > 2:
        quality(sys.argv[2:])
    elif command == "attribute" and len(sys.argv) > 2:
        attribute(sys.argv[2])
    elif command == "gaps":
        gaps()
    else:
        raise SystemExit(__doc__)
