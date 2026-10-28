"""Freeze a season's projections and score them later with rules written down in advance (.claude/PREREGISTRATION_2026.md).

  python src/evaluation/preseason_eval.py snapshot --season 2026 [--source data/processed/projections_2026_v1.json]
      writes .claude/snapshots/projections_<season>_preseason.csv: the projections, the ADP-curve expectation, the gap and the role-caution inputs and flag, and
      prints the SHA-256 of the source file and the snapshot so the freeze can be checked later.
  python src/evaluation/preseason_eval.py score --season 2026 --actuals data/raw/seasonal_20_26.parquet [--snapshot path] [--exclude 00-0038117]
      scores the frozen snapshot against the season's results: the role-caution comparison (H1), the reliability of big model-above-ADP gaps against big
      fades (H2) and the list of big gaps (H3), each alone and pooled with 2022 to season-1, with 90% bootstrap intervals that resample players.

Only WRs enter the comparisons (the study behind them is WR-only). Writes nothing except the snapshot.
"""
import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import fit_position_curves, load_history
from src.evaluation.benchmark import TOP_N_ADP
from src.evaluation.gap_reliability import load_rows, slope_interval
from src.evaluation.target_competition import add_context, add_measures, diff_interval, load_start_roster, load_weekly
from src.features.role_context import ROLE_CAUTION_ABSENCE, role_caution

ROOT = Path(__file__).parent.parent.parent
SNAPSHOTS = ROOT / ".claude" / "snapshots"
GAP = 30             # PPR above (or below) the ADP curve that counts as a big gap
HEALTHY_GAMES = 9    # a season shorter than this says little about the projection (the same rule as the 2022-2025 studies)
COLUMNS = ["season", "player_id", "player_name", "position", "team", "adp", "in_top_adp", "projected_ppr", "market_estimate", "injury_flag", "curve", "gap",
           "absence_share_prev", "team_changed", "rookie_r1_teammate", "role_caution"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(season, source):
    """The projection file as a flat CSV, with the ADP-curve expectation (curves fit on earlier seasons only) and the role-caution flag."""
    import json
    players = pd.DataFrame(json.load(open(source))["players"])
    curves = fit_position_curves(load_history().query("season < @season"))
    players["position_rank"] = players.groupby("position")["adp"].rank(method="first")
    players["curve"] = [float(curves[p].predict([r])[0]) for p, r in zip(players["position"], players["position_rank"])]
    players["gap"] = players["projected_ppr"] - players["curve"]
    modeled = ~players["market_estimate"].astype(bool)
    players["in_top_adp"] = modeled & (players["adp"].where(modeled).rank(method="first") <= TOP_N_ADP)
    for column in ["absence_share_prev", "team_changed", "rookie_r1_teammate"]:
        if column not in players.columns:
            players[column] = np.nan
    players["role_caution"] = role_caution(players) & (players["position"] == "WR")
    players["season"] = season
    out = players[COLUMNS].round(3).sort_values("adp")
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f"projections_{season}_preseason.csv"
    out.to_csv(path, index=False, lineterminator="\n")        # LF, so the SHA-256 is the same on every machine (compare after removing carriage returns if git converted them)
    print(f"wrote {path.relative_to(ROOT)}: {len(out)} players, {int(out['role_caution'].sum())} with the role caution, {int(out['in_top_adp'].sum())} in the top {TOP_N_ADP} by ADP")
    print(f"source {Path(source).name} sha256 {sha256(source)}\nsnapshot sha256 {sha256(path)}")


def history(before):
    """The 2022 to before-1 WR rows with the same columns: the flag is the role caution, healthy seasons only."""
    weekly, roster = load_weekly(), load_start_roster()
    d = load_rows()
    d = d[(d["position"] == "WR") & d["in_top_adp"] & (d["season"] < before)].copy()
    d = add_context(add_measures(d, weekly, roster), weekly, roster)
    d["flag"] = (d["absence_share"] >= ROLE_CAUTION_ABSENCE) & d["new_situation"]
    return d[d["G"] >= HEALTHY_GAMES]


def season_rows(snapshot_path, actuals_path, season, draftable_only=True):
    s = pd.read_csv(snapshot_path)
    s = s[(s["position"] == "WR") & ~s["market_estimate"] & (s["in_top_adp"] if draftable_only else True)].copy()
    a = pd.read_parquet(actuals_path, columns=["player_id", "season", "games", "fantasy_points_ppr"])
    a = a[a["season"] == season].groupby("player_id").agg(G=("games", "sum"), actual_ppr=("fantasy_points_ppr", "sum"))
    s = s.merge(a, on="player_id", how="left")
    s["G"], s["actual_ppr"] = s["G"].fillna(0), s["actual_ppr"].fillna(0.0)             # drafted and never played: that is what a roster scores
    s["oos_pred_ppr"] = s["projected_ppr"]
    s["flag"] = s["role_caution"].astype(bool)
    return s


def with_errors(d):
    d = d.copy()
    d["over"] = d["oos_pred_ppr"] - d["actual_ppr"]
    d["curve_over"] = d["curve"] - d["actual_ppr"]
    d["resid"] = d["actual_ppr"] - d["curve"]          # what gap_reliability.slope regresses on the gap
    return d


def h1(d, label, rng):
    h = d[d["G"] >= HEALTHY_GAMES]
    f = h["flag"]
    if f.sum() == 0 or (~f).sum() == 0:
        print(f"  {label}: no flagged or no unflagged healthy rows")
        return
    lo, hi = diff_interval(h, f, "over", rng)
    print(f"  {label}: flagged n={int(f.sum())} model over {h.loc[f, 'over'].mean():+.1f} (ADP curve {h.loc[f, 'curve_over'].mean():+.1f}), rest n={int((~f).sum())} "
          f"{h.loc[~f, 'over'].mean():+.1f}; difference {h.loc[f, 'over'].mean() - h.loc[~f, 'over'].mean():+.1f} (90% interval {lo:+.1f} to {hi:+.1f})")


def h2(d, label, rng):
    for name, m in [(f"gap >= +{GAP} (the likes)", d["gap"] >= GAP), (f"gap <= -{GAP} (the fades)", d["gap"] <= -GAP)]:
        g = d[m]
        if len(g) < 5:
            print(f"  {label}, {name}: only {len(g)} rows")
            continue
        b, lo, hi = slope_interval(g, rng)
        print(f"  {label}, {name}: n={len(g)}, mean gap {g['gap'].mean():+.1f}, mean actual - curve {(g['actual_ppr'] - g['curve']).mean():+.1f}, slope {b:.2f} ({lo:.2f} to {hi:.2f})")


def score(season, snapshot_path, actuals_path, exclude):
    rng = np.random.default_rng(0)
    now = with_errors(season_rows(snapshot_path, actuals_path, season))
    past = with_errors(history(season))
    keep = ~now["player_id"].isin(exclude)
    now_all, past_all = now, past
    pooled_cols = ["player_id", "season", "oos_pred_ppr", "curve", "actual_ppr", "gap", "G", "flag", "over", "curve_over", "resid"]
    pooled = pd.concat([past[pooled_cols], now[pooled_cols]], ignore_index=True)
    pooled = pooled[pooled["G"] >= HEALTHY_GAMES]                                  # the same healthy-season rule for every comparison
    print(f"=== {season} score: {len(now)} draftable WRs in the snapshot, {int((now['G'] >= HEALTHY_GAMES).sum())} healthy ({HEALTHY_GAMES}+ games); pooled adds {len(past)} healthy rows from 2022-{season - 1}")
    print("H1: role caution, model over-projection (projected - actual PPR), flagged vs rest")
    h1(now_all, f"{season} alone", rng)
    h1(now_all[keep], f"{season} alone, without {sorted(exclude)}", rng) if exclude else None
    h1(pooled, f"pooled 2022-{season}", rng)
    h1(pooled[~pooled["player_id"].isin(exclude)], f"pooled without {sorted(exclude)}", rng) if exclude else None
    print("H2: reliability of big gaps (slope of actual - curve on model - curve; 1 = the gap is right, 0 = the curve is)")
    h2(now_all[now_all["G"] >= HEALTHY_GAMES], f"{season}", rng)
    h2(pooled, f"pooled 2022-{season}", rng)
    print(f"H3: every modeled WR in the snapshot with a gap of {GAP}+ (descriptive)")
    big = with_errors(season_rows(snapshot_path, actuals_path, season, draftable_only=False))
    big = big[big["gap"] >= GAP].sort_values("gap", ascending=False)               # every modeled WR with a big gap, drafted early or not
    print(big[["player_name", "team", "adp", "oos_pred_ppr", "curve", "actual_ppr", "G", "gap", "over", "flag"]].round(1).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["snapshot", "score"])
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--source", default=None, help="snapshot: the projection json (default data/processed/projections_<season>_v1.json)")
    parser.add_argument("--snapshot", default=None, help="score: the frozen csv (default .claude/snapshots/projections_<season>_preseason.csv)")
    parser.add_argument("--actuals", default=None, help="score: seasonal stats parquet that holds the season's results")
    parser.add_argument("--exclude", nargs="*", default=[], help="score: player ids whose early results were already known when the rules were frozen")
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot(args.season, args.source or ROOT / "data" / "processed" / f"projections_{args.season}_v1.json")
    else:
        if not args.actuals:
            sys.exit("score needs --actuals (a seasonal stats parquet with the season's results)")
        score(args.season, args.snapshot or SNAPSHOTS / f"projections_{args.season}_preseason.csv", args.actuals, set(args.exclude))
