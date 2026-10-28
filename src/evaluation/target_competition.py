"""Does the model over-project wide receivers whose target competition got tougher, or whose last-year volume came while a teammate was out?

Motivated by K.Allen 2024 (thin room at LAC in 2023, then D.Moore plus a top-10 rookie at CHI) and W.Robinson 2025 (STATUS.md, Open / Deferred). The WR model
has no teammate-competition input. On the walk-forward predictions for draftable WRs (2022-2025, the rows `gap_reliability.load_rows` builds) this adds three
measures from the cached raw files and compares the model's over-projection (prediction - actual PPR) and the ADP curve's, flagged group against the rest:

  rivals_change  top-2 rivals' targets per game in the new room (last season's rates, RB/WR/TE on the start roster) minus the same in the old room;
                 flagged = top third (the room got tougher)
  rookie_r1      a first-round rookie WR/TE on the new start roster
  absence_share  share of last season's targets earned in weeks the team's top rival (by targets per game, 3+ games) did not play; flagged = top third

It also shows the slope of `actual - curve` on `model - curve` (as in gap_reliability.py): below 1 means the model's disagreement with ADP is too big
for that group. Bootstrap resamples players.

`--profile` also searches for the combination of the two mechanisms the user described (absence share 0.5+ AND a new situation: changed teams or a
first-round rookie arrived) among healthy WRs, and lists the live 2026 matches.

`--role` tests the role-quality idea: does a big jump in the depth, air-yards share or expected points per target of last season's targets, against the
player's own two earlier seasons, predict over-projection? (K.Robinson 2025: same 140 targets, depth 4.7 -> 8.5.) Writes nothing; run:
python src/evaluation/target_competition.py [--profile] [--role]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.gap_reliability import load_rows, slope
from src.features.advanced import TWO_WAY_PLAYERS

RAW = Path(__file__).parent.parent.parent / "data" / "raw"
CATCHERS = ["WR", "TE", "RB"]
MIN_GAMES = 6            # fewer games than this: a rival's per-game rate is not trusted
FIRST_ROUND = 32
N_BOOT = 2000
ROSTER_TEAMS = {"LAR": "LA", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "OAK": "LV", "SD": "LAC", "SL": "LA", "STL": "LA"}


def load_weekly():
    """Regular-season weekly rows of the pass catchers: player, season, week, team, targets."""
    w = pd.read_parquet(RAW / "weekly_20_25.parquet", columns=["player_id", "season", "week", "season_type", "team", "position", "targets"])
    w = w[(w["season_type"] == "REG") & w["position"].isin(CATCHERS)].copy()
    w["targets"] = w["targets"].fillna(0)
    return w


def load_start_roster():
    """Each player's team and rookie status on his earliest roster row of the season (the file is sparse after week 1, so this is how the pipeline finds the start team)."""
    r = pd.read_parquet(RAW / "seasonal_roster_20_25.parquet", columns=["gsis_id", "season", "week", "team", "position", "years_exp", "draft_number"])
    r = r[r["position"].isin(CATCHERS) & ~r["gsis_id"].isin(TWO_WAY_PLAYERS)].dropna(subset=["gsis_id"])
    r = r.sort_values(["season", "week"]).drop_duplicates(["gsis_id", "season"])        # the pipeline's rule: a player's earliest roster row of the season
    r["team"] = r["team"].replace(ROSTER_TEAMS)
    r["draft_number"] = pd.to_numeric(r["draft_number"], errors="coerce")        # stored as text; undrafted players are missing
    r["years_exp"] = pd.to_numeric(r["years_exp"], errors="coerce")
    return r.rename(columns={"gsis_id": "player_id"})


def season_rates(weekly):
    """Per player-season over all teams: games, targets, targets per game (0 when under MIN_GAMES games)."""
    g = weekly.groupby(["player_id", "season"]).agg(games=("week", "nunique"), targets=("targets", "sum")).reset_index()
    g["tpg"] = np.where(g["games"] >= MIN_GAMES, g["targets"] / g["games"], 0.0)
    return g


def main_team(weekly):
    """(player, season) -> the team he played the most games for."""
    return (weekly.groupby(["player_id", "season", "team"])["week"].nunique().reset_index()
            .sort_values(["player_id", "season", "week"], ascending=[True, True, False]).drop_duplicates(["player_id", "season"])
            .set_index(["player_id", "season"])["team"])


def add_measures(d, weekly, roster):
    rates = season_rates(weekly).set_index(["player_id", "season"])
    main = main_team(weekly)
    team_weeks = weekly.groupby(["team", "season"])["week"].apply(set)
    by_team = {k: g for k, g in weekly.groupby(["team", "season"])}
    start = {k: g for k, g in roster.groupby(["team", "season"])}
    out = []
    for row in d.itertuples():
        pid, t = row.player_id, row.season
        new_team = roster.loc[(roster["player_id"] == pid) & (roster["season"] == t), "team"]
        old_team = main.get((pid, t - 1))
        if new_team.empty or old_team is None or (pid, t - 1) not in rates.index:
            out.append((np.nan, np.nan, np.nan))
            continue
        new_team = new_team.iloc[0]

        def top2(ids):
            ids = [i for i in ids if i != pid and (i, t - 1) in rates.index]
            return float(sum(sorted((rates.loc[(i, t - 1), "tpg"] for i in ids), reverse=True)[:2]))

        old_room = by_team.get((old_team, t - 1))
        old_ids = old_room["player_id"].unique() if old_room is not None else []
        new_room = start.get((new_team, t))
        new_ids = new_room["player_id"].unique() if new_room is not None else []
        change = top2(new_ids) - top2(old_ids)
        rookie = 0.0
        if new_room is not None:
            rk = new_room[(new_room["player_id"] != pid) & new_room["position"].isin(["WR", "TE"]) & (new_room["years_exp"] == 0)
                          & (new_room["draft_number"] <= FIRST_ROUND)]
            rookie = float(len(rk) > 0)

        share = np.nan
        mine = old_room[old_room["player_id"] == pid] if old_room is not None else None
        if mine is not None and mine["targets"].sum() > 0:
            # the rival is the teammate with the highest targets per game (3+ games), not the highest total: a star who was out most of the year has few targets
            others = old_room[old_room["player_id"] != pid].groupby("player_id").agg(targets=("targets", "sum"), games=("week", "nunique"))
            others = others[others["games"] >= 3]
            if len(others):
                rival = (others["targets"] / others["games"]).idxmax()
                rival_weeks = set(old_room.loc[old_room["player_id"] == rival, "week"])
                away = mine[~mine["week"].isin(rival_weeks) & mine["week"].isin(team_weeks[(old_team, t - 1)])]
                share = float(away["targets"].sum() / mine["targets"].sum())
        out.append((change, rookie, share))
    d = d.copy()
    d[["rivals_change", "rookie_r1", "absence_share"]] = pd.DataFrame(out, index=d.index)
    return d


def boot_diff(g, column, rng):
    """Mean of `column` in the flagged rows minus the rest, with a 90% bootstrap interval resampling players."""
    players = g["player_id"].unique()
    by_player = {p: x for p, x in g.groupby("player_id")}
    stats = []
    for _ in range(N_BOOT):
        s = pd.concat([by_player[p] for p in rng.choice(players, size=len(players))])
        stats.append(s.loc[s["flag"], column].mean() - s.loc[~s["flag"], column].mean())
    return np.nanpercentile(stats, 5), np.nanpercentile(stats, 95)


def report(d, rng, label):
    d = d.copy()
    d["model_over"] = d["oos_pred_ppr"] - d["actual_ppr"]
    d["curve_over"] = d["curve"] - d["actual_ppr"]
    print(f"\n=== {label}: {len(d)} draftable WR player-seasons, {int(d['season'].min())}-{int(d['season'].max())}")
    print(f"all WR: model over-projects by {d['model_over'].mean():+.1f} PPR on average, the ADP curve by {d['curve_over'].mean():+.1f}")
    print(f"{'measure':<16}{'group':<9}{'n':>5}{'model over':>12}{'curve over':>12}{'model-curve':>13}{'slope':>7}   (diff vs rest, 90% interval, model over)")
    for name, flagged in [("rivals_change", lambda s: s > s.quantile(2 / 3)), ("rookie_r1", lambda s: s == 1), ("absence_share", lambda s: s > s.quantile(2 / 3))]:
        g = d.dropna(subset=[name]).copy()
        g["flag"] = flagged(g[name])
        rho = spearmanr(g[name], g["model_over"])[0]
        diff = g.loc[g["flag"], "model_over"].mean() - g.loc[~g["flag"], "model_over"].mean()
        lo, hi = boot_diff(g, "model_over", rng)
        for tag, sub in [("flagged", g[g["flag"]]), ("rest", g[~g["flag"]])]:
            print(f"{name:<16}{tag:<9}{len(sub):>5}{sub['model_over'].mean():>+12.1f}{sub['curve_over'].mean():>+12.1f}"
                  f"{(sub['model_over'] - sub['curve_over']).mean():>+13.1f}{slope(sub):>7.2f}"
                  + (f"   {diff:+.1f} ({lo:+.1f} to {hi:+.1f}); Spearman(measure, over) {rho:+.2f}" if tag == "flagged" else ""))


def add_context(d, weekly, roster):
    """Adds the team he came from and went to, whether it changed, games played, the over-projection and the new-situation flag."""
    team_now = roster.set_index(["player_id", "season"])["team"]
    main = main_team(weekly)
    games = weekly.groupby(["player_id", "season"])["week"].nunique()
    d = d.copy()
    d["to"] = [team_now.get((p, s)) for p, s in zip(d["player_id"], d["season"])]
    d["from"] = [main.get((p, s - 1)) for p, s in zip(d["player_id"], d["season"])]
    d["moved"] = d["from"].notna() & (d["from"] != d["to"])
    d["G"] = [games.get((p, s), 0) for p, s in zip(d["player_id"], d["season"])]
    d["over"] = d["oos_pred_ppr"] - d["actual_ppr"]
    d["curve_over"] = d["curve"] - d["actual_ppr"]
    d["new_situation"] = d["moved"] | (d["rookie_r1"] == 1)
    return d


def diff_interval(h, mask, column, rng):
    """Mean of `column` where mask holds minus where it does not, with a 90% bootstrap interval resampling players."""
    by_player = {p: x for p, x in h.assign(_m=mask).groupby("player_id")}
    players = list(by_player)
    draws = []
    for _ in range(N_BOOT):
        s = pd.concat([by_player[p] for p in rng.choice(players, size=len(players))])
        if s["_m"].any() and (~s["_m"]).any():
            draws.append(s.loc[s["_m"], column].mean() - s.loc[~s["_m"], column].mean())
    return np.percentile(draws, 5), np.percentile(draws, 95)


def profile_report(d, rng):
    """Healthy (9+ games) WRs: the combined profile against its parts and against thresholds, then the matches themselves."""
    h = d[d["G"] >= 9].copy()
    print(f"\n=== profile search: {len(h)} healthy draftable WR player-seasons; all of them: model over {h['over'].mean():+.1f}, over by 20+ in {(h['over'] >= 20).mean():.0%}")
    print(f"{'group':<36}{'n':>4}{'model over':>12}{'rest':>8}{'diff (90% interval)':>24}{'ADP curve over':>16}{'over 20+':>9}")
    groups = {
        "absence 0.4+ and new situation": (h["absence_share"] >= 0.4) & h["new_situation"],
        "absence 0.5+ and new situation": (h["absence_share"] >= 0.5) & h["new_situation"],
        "absence 0.6+ and new situation": (h["absence_share"] >= 0.6) & h["new_situation"],
        "0.5+ and new, 12+ games only": (h["absence_share"] >= 0.5) & h["new_situation"] & (h["G"] >= 12),
        "new situation, absence under 0.5": (h["absence_share"] < 0.5) & h["new_situation"],
        "absence 0.5+, nothing new": (h["absence_share"] >= 0.5) & ~h["new_situation"],
    }
    for name, m in groups.items():
        lo, hi = diff_interval(h, m, "over", rng)
        diff = h.loc[m, "over"].mean() - h.loc[~m, "over"].mean()
        print(f"{name:<36}{int(m.sum()):>4}{h.loc[m, 'over'].mean():>+12.1f}{h.loc[~m, 'over'].mean():>+8.1f}{f'{diff:+.0f} ({lo:+.0f} to {hi:+.0f})':>24}"
              f"{h.loc[m, 'curve_over'].mean():>+16.1f}{int((h.loc[m, 'over'] >= 20).sum()):>9}")
    strict = h[groups["absence 0.5+ and new situation"]].sort_values("over", ascending=False)
    print("\nthe matches (absence 0.5+ and new situation), by over-projection:")
    print(strict[["player_name", "season", "from", "to", "age", "oos_pred_ppr", "curve", "actual_ppr", "gap", "over", "G", "rookie_r1", "absence_share"]]
          .round(2).to_string(index=False))
    print("by season:", strict.groupby("season")["over"].agg(["size", "mean"]).round(0).T.to_string())


def live_2026_pool(weekly, roster):
    """The live 2026 WRs with the model's projection, the ADP curve, the gap, the competition measures and the new-situation flag."""
    import json
    from src.draft.market_fallback import fit_position_curves, load_history
    r26 = pd.read_parquet(RAW / "roster_2026.parquet")
    r26 = r26[r26["position"].isin(CATCHERS) & ~r26["gsis_id"].isin(TWO_WAY_PLAYERS)].dropna(subset=["gsis_id"]).copy()
    r26["week"], r26["team"] = 0, r26["team"].replace(ROSTER_TEAMS)
    for c in ["draft_number", "years_exp"]:
        r26[c] = pd.to_numeric(r26[c], errors="coerce")
    r26 = r26.rename(columns={"gsis_id": "player_id"})[["player_id", "season", "week", "team", "position", "years_exp", "draft_number"]].drop_duplicates(["player_id", "season"])
    both = pd.concat([roster, r26], ignore_index=True)
    projections = pd.DataFrame(json.load(open(RAW.parent / "processed" / "projections_2026_v1.json"))["players"])
    wr = projections[projections["position"] == "WR"].copy()
    wr["curve"] = fit_position_curves(load_history())["WR"].predict(wr["adp"].rank(method="first").values)
    wr["gap"] = wr["projected_ppr"] - wr["curve"]
    wr["season"], wr["oos_pred_ppr"] = 2026, wr["projected_ppr"]
    wr = add_measures(wr, weekly, both)
    main = main_team(weekly)
    wr["from"] = [main.get((p, 2025)) for p in wr["player_id"]]
    wr["new_situation"] = (wr["from"].notna() & (wr["from"] != wr["team"])) | (wr["rookie_r1"] == 1)
    return wr


def live_2026_matches(weekly, roster):
    """The same profile on the live 2026 WR pool (model projection against the ADP curve, 2025 weekly data, 2026 rosters)."""
    wr = live_2026_pool(weekly, roster)
    print("\n=== live 2026 WR pool: absence 0.5+ and a new situation (model against the ADP curve)")
    matches = wr[(wr["absence_share"] >= 0.5) & wr["new_situation"]].sort_values("gap", ascending=False)
    print(matches[["player_name", "from", "team", "adp", "projected_ppr", "curve", "gap", "rookie_r1", "absence_share"]].round(2).to_string(index=False))


ROLE_MIN_TARGETS = 40     # last season and the baseline each need this many targets for a depth or quality figure to mean anything


def season_quality(seasonal, opportunity):
    """Per WR player-season: targets, air yards, expected receiving points, air-yards share (from the team row with most games)."""
    s = seasonal[seasonal["position"] == "WR"]
    main_row = s.sort_values("games", ascending=False).drop_duplicates(["player_id", "season"]).set_index(["player_id", "season"])["air_yards_share"]
    q = s.groupby(["player_id", "season"]).agg(targets=("targets", "sum"), air=("receiving_air_yards", "sum"), games=("games", "sum"))
    q["air_share"] = main_row
    xfp = opportunity.groupby(["player_id", "season"])["rec_fantasy_points_exp"].sum()
    q["xfp"] = xfp.reindex(q.index)
    return q


def add_role_change(d, quality, season_col="season"):
    """Last season's depth (aDOT), air-yards share and expected points per target minus the same over the two seasons before it."""
    rows = []
    for pid, t in zip(d["player_id"], d[season_col]):
        last = quality.loc[(pid, t - 1)] if (pid, t - 1) in quality.index else None
        base = quality.reindex([(pid, t - 2), (pid, t - 3)]).dropna(subset=["targets"])
        out = [np.nan, np.nan, np.nan]
        if last is not None and last["targets"] >= ROLE_MIN_TARGETS and base["targets"].sum() >= ROLE_MIN_TARGETS:
            out[0] = last["air"] / last["targets"] - base["air"].sum() / base["targets"].sum()
            if not np.isnan(last["xfp"]) and base["xfp"].notna().all():
                out[1] = last["xfp"] / last["targets"] - base["xfp"].sum() / base["targets"].sum()
            shares = base.loc[base["games"] >= 6, "air_share"].dropna()
            if len(shares) and not np.isnan(last["air_share"]):
                out[2] = last["air_share"] - shares.mean()
        rows.append(out)
    d = d.copy()
    d[["adot_jump", "xfp_per_target_jump", "air_share_jump"]] = pd.DataFrame(rows, index=d.index)
    return d


def role_report(d, rng, cuts=None):
    """Top-third flag on each role-change measure against the rest; returns the cut points so the 2026 pool can reuse them."""
    cuts = cuts or {}
    for label, sub in [("all draftable WRs with a baseline", d), ("only players who played 12+ games", d[d["G"] >= 12])]:
        sub = sub.copy()
        print(f"\n=== role change, {label}: {len(sub)} rows, {sub['adot_jump'].notna().sum()} with a depth baseline")
        print(f"{'measure':<22}{'group':<9}{'n':>5}{'model over':>12}{'curve over':>12}{'model-curve':>13}{'slope':>7}   (flagged minus rest, 90% interval)")
        for name in ["adot_jump", "xfp_per_target_jump", "air_share_jump"]:
            g = sub.dropna(subset=[name]).copy()
            cuts.setdefault(name, g[name].quantile(2 / 3))
            g["flag"] = g[name] > cuts[name]
            lo, hi = diff_interval(g, g["flag"], "over", rng)
            diff = g.loc[g["flag"], "over"].mean() - g.loc[~g["flag"], "over"].mean()
            rho = spearmanr(g[name], g["over"])[0]
            for tag, x in [("flagged", g[g["flag"]]), ("rest", g[~g["flag"]])]:
                print(f"{name:<22}{tag:<9}{len(x):>5}{x['over'].mean():>+12.1f}{x['curve_over'].mean():>+12.1f}{(x['over'] - x['curve_over']).mean():>+13.1f}{slope(x):>7.2f}"
                      + (f"   {diff:+.1f} ({lo:+.1f} to {hi:+.1f}); Spearman(measure, over) {rho:+.2f}; cut {cuts[name]:+.2f}" if tag == "flagged" else ""))
    return cuts


def live_2026_role(weekly, roster, quality, cuts):
    """2026 WRs whose 2025 depth, air-yards share and expected points per target jumped by more than the historical cut points."""
    import json
    from src.draft.market_fallback import fit_position_curves, load_history
    projections = pd.DataFrame(json.load(open(RAW.parent / "processed" / "projections_2026_v1.json"))["players"])
    wr = projections[projections["position"] == "WR"].copy()
    wr["curve"] = fit_position_curves(load_history())["WR"].predict(wr["adp"].rank(method="first").values)
    wr["gap"] = wr["projected_ppr"] - wr["curve"]
    wr["season"] = 2026
    wr = add_role_change(wr, quality)
    wr["flags"] = sum((wr[m] > cuts[m]).astype(int) for m in cuts)
    print(f"\n=== live 2026 WR pool: role-change measures against the historical top-third cuts (flags = how many of the three are above the cut)")
    x = wr[wr["flags"] >= 2].sort_values("gap", ascending=False)
    print(x[["player_name", "team", "adp", "projected_ppr", "curve", "gap", "adot_jump", "xfp_per_target_jump", "air_share_jump", "flags"]].round(2).to_string(index=False))


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    d = load_rows()
    d = d[(d["position"] == "WR") & d["in_top_adp"]].copy()
    weekly, roster = load_weekly(), load_start_roster()
    d = add_measures(d, weekly, roster)
    games = weekly.groupby(["player_id", "season"])["week"].nunique().rename("games_played")
    d = d.merge(games, on=["player_id", "season"], how="left")
    cases = d[((d["player_name"] == "K.Allen") & (d["season"] == 2024)) | ((d["player_name"] == "W.Robinson") & (d["season"] == 2025))]
    print(cases[["player_name", "season", "oos_pred_ppr", "curve", "actual_ppr", "rivals_change", "rookie_r1", "absence_share"]].round(2).to_string(index=False))
    report(d, rng, "all draftable WRs")
    report(d[d["games_played"].fillna(0) >= 12], rng, "only WRs who played 12+ games (injury luck removed)")
    if "--profile" in sys.argv:
        profile_report(add_context(d, weekly, roster), rng)
        live_2026_matches(weekly, roster)
    if "--role" in sys.argv:
        seasonal = pd.read_parquet(RAW / "seasonal_20_25.parquet", columns=["player_id", "season", "position", "games", "targets", "receiving_air_yards", "air_yards_share"])
        opportunity = pd.read_parquet(RAW / "ff_opportunity_14_25.parquet", columns=["player_id", "season", "rec_fantasy_points_exp"])
        quality = season_quality(seasonal, opportunity)
        rolled = add_role_change(add_context(d, weekly, roster), quality)
        show = rolled[((rolled["player_name"] == "K.Allen") & (rolled["season"] == 2024)) | ((rolled["player_name"] == "W.Robinson") & (rolled["season"] == 2025))]
        print("\n" + show[["player_name", "season", "adot_jump", "xfp_per_target_jump", "air_share_jump", "over"]].round(2).to_string(index=False))
        cuts = role_report(rolled, rng)
        live_2026_role(weekly, roster, quality, cuts)
