"""Handcuff study: when a team's lead RB misses games, can the RB who absorbs the work be identified from preseason information?

For every team-season (2015-2024) with a week-1 depth-chart RB1, the lead RB's absent team-weeks are found from the weekly stats (no touches that
week, and he did not play for another team). Every RB on the team is then scored by how many PPR points he gained in those weeks over his own
average in the weeks the starter played; the top gainer is the "absorber". Preseason predictors (all known in August) each pick one chart RB
other than the starter, and are scored by how often the pick is the absorber, against picking at random. Also reported: how often the absorber is
not on the chart at all, how many PPR points a well-chosen backup is worth per season, and whether the share a team's RB2 absorbs persists
from one season to the next.

Run: python src/evaluation/handcuff_study.py   (writes data/processed/handcuff_events.csv)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.features.team_context import _norm

ROOT = Path(__file__).parent.parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "handcuff_events.csv"
SEASONS = range(2015, 2025)      # depth charts end in 2024; prior-season shares need the season before
MIN_ABSENT = 2                   # games the starter must miss for the team-season to count as an event
MIN_PRESENT = 2                  # games he must play, to know what he was doing
PREDICTORS = ["depth_tier", "carry_share", "target_share", "ppg", "draft_capital"]


def load_weekly():
    cols = ["player_id", "position", "season", "week", "season_type", "team", "carries", "targets", "fantasy_points_ppr"]
    w = pd.read_parquet(RAW / "weekly_20_25.parquet", columns=cols)
    w = w[w["season_type"] == "REG"].copy()
    w["team"] = _norm(w["team"])
    w["touches"] = w["carries"].fillna(0) + w["targets"].fillna(0)
    return w


def load_chart():
    """Week-1 depth chart, running backs only (the file already keeps week 1 of each season)."""
    d = pd.read_parquet(RAW / "depth_old_14_24.parquet")
    d = d[d["depth_position"].isin(["RB", "HB"])].copy()
    d["season"] = d["season"].astype(int)
    d["team"] = _norm(d["club_code"])
    d["tier"] = pd.to_numeric(d["depth_team"], errors="coerce")
    return d.dropna(subset=["tier", "gsis_id"]).rename(columns={"gsis_id": "player_id"})[["season", "team", "player_id", "tier"]].drop_duplicates()


def prior_season_roles(rb):
    """Each RB's share of his team's carries and targets, and points per game, in a season; keyed to the NEXT season (what is known preseason)."""
    g = rb.groupby(["season", "team", "player_id"]).agg(carries=("carries", "sum"), targets=("targets", "sum"),
                                                          ppr=("fantasy_points_ppr", "sum"), games=("touches", lambda x: int((x > 0).sum()))).reset_index()
    g["carry_share"] = g["carries"] / g.groupby(["season", "team"])["carries"].transform("sum").clip(lower=1)
    g["target_share"] = g["targets"] / g.groupby(["season", "team"])["targets"].transform("sum").clip(lower=1)
    g["ppg"] = g["ppr"] / g["games"].clip(lower=1)
    best = g.sort_values("carries", ascending=False).drop_duplicates(["season", "player_id"])
    best["season"] = best["season"] + 1
    return best[["season", "player_id", "carry_share", "target_share", "ppg"]]


def load_draft_capital():
    """Draft pick number by player where the roster file has it (it starts in 2020, so older players may be missing); None if the columns are absent."""
    try:
        r = pd.read_parquet(RAW / "seasonal_roster_20_25.parquet")
        r = r.rename(columns={"gsis_id": "player_id"})
        r["draft_number"] = pd.to_numeric(r["draft_number"], errors="coerce")
        return r.dropna(subset=["player_id"]).drop_duplicates("player_id").set_index("player_id")["draft_number"]
    except (KeyError, FileNotFoundError):
        return None


def team_event(season, team, starter_id, chart_rows, rb, team_weeks):
    """One team-season: when the starter was absent, who gained points. None if the team-season cannot be read."""
    weeks = sorted(team_weeks)
    mine = rb[(rb["season"] == season) & (rb["team"] == team)]
    starter_rows = rb[(rb["season"] == season) & (rb["player_id"] == starter_id) & (rb["touches"] > 0)]
    if (starter_rows["team"] != team).any():
        return None                                                   # traded: his absence is not an injury absence
    played = set(starter_rows["week"])
    absent = [wk for wk in weeks if wk not in played]
    present = [wk for wk in weeks if wk in played]
    row = dict(season=season, team=team, starter=starter_id, absent=len(absent), present=len(present))
    if len(absent) == 0 or len(present) < MIN_PRESENT:
        return row
    row["starter_ppg"] = starter_rows["fantasy_points_ppr"].mean()
    gains = {}
    for pid, p in mine[mine["player_id"] != starter_id].groupby("player_id"):
        first = p["week"].min()
        by_week = p.groupby("week")["fantasy_points_ppr"].sum()
        pres_weeks = [wk for wk in present if wk >= first]
        abs_weeks = [wk for wk in absent if wk >= first]
        if not abs_weeks:
            continue
        baseline = np.mean([by_week.get(wk, 0.0) for wk in pres_weeks]) if pres_weeks else 0.0
        gains[pid] = sum(by_week.get(wk, 0.0) for wk in abs_weeks) - len(abs_weeks) * baseline
    row["gains"] = gains
    return row


def main():
    w = load_weekly()
    rb = w[w["position"] == "RB"].copy()
    chart = load_chart()
    roles = prior_season_roles(rb).set_index(["season", "player_id"])
    draft = load_draft_capital()
    weeks_by_team = w.groupby(["season", "team"])["week"].apply(lambda s: set(s)).to_dict()
    print(f"draft capital available: {'no' if draft is None else f'{draft.notna().mean():.0%} of rostered players'}")

    rows = []
    for (season, team), grp in chart[chart["season"].isin(SEASONS)].groupby(["season", "team"]):
        if (season, team) not in weeks_by_team:
            continue
        starters = grp[grp["tier"] == grp["tier"].min()]
        # several RBs can share tier 1; the one with the most carries last year is the starter
        def last_year(pid, col):
            return roles[col].get((season, pid), 0.0)
        starter = max(starters["player_id"], key=lambda pid: last_year(pid, "carry_share"))
        candidates = grp[grp["player_id"] != starter]
        ev = team_event(season, team, starter, grp, rb, weeks_by_team[(season, team)])
        if ev is None:
            continue
        ev["n_candidates"] = len(candidates)
        gains = ev.pop("gains", {})
        positive = {k: v for k, v in gains.items() if v > 0}
        if gains and candidates is not None and len(candidates):
            ev["absorber"] = max(gains, key=gains.get)
            ev["absorber_gain"] = gains[ev["absorber"]]
            ev["absorber_on_chart"] = ev["absorber"] in set(candidates["player_id"])
            ev["total_positive_gain"] = sum(positive.values())
            picks = {}
            ids = list(candidates["player_id"])
            tiers = dict(zip(candidates["player_id"], candidates["tier"]))
            picks["depth_tier"] = min(ids, key=lambda p: (tiers[p], -last_year(p, "carry_share")))
            for col in ("carry_share", "target_share", "ppg"):
                picks[col] = max(ids, key=lambda p: last_year(p, col))
            if draft is not None:
                picks["draft_capital"] = min(ids, key=lambda p: draft.get(p, 300) if pd.notna(draft.get(p, np.nan)) else 300)
            for name, pid in picks.items():
                ev[f"hit_{name}"] = float(pid == ev["absorber"])
                ev[f"gain_{name}"] = gains.get(pid, 0.0)
            ev["gain_random"] = float(np.mean([gains.get(p, 0.0) for p in ids]))       # a chart RB picked at random
            tier2 = min(ids, key=lambda p: (tiers[p], -last_year(p, "carry_share")))
            ev["rb2_share"] = max(0.0, gains.get(tier2, 0.0)) / ev["total_positive_gain"] if ev["total_positive_gain"] > 0 else np.nan
        rows.append(ev)

    ev = pd.DataFrame(rows)
    ev.to_csv(OUT, index=False)
    events = ev[(ev["absent"] >= MIN_ABSENT) & (ev["present"] >= MIN_PRESENT) & ev["absorber"].notna()].copy()
    print(f"\n{len(ev)} team-seasons with a week-1 chart RB1 ({ev['season'].min()}-{ev['season'].max()}); "
          f"{len(events)} events where he missed >= {MIN_ABSENT} games and played >= {MIN_PRESENT}")
    print(f"starter absent >= 2 games in {(ev['absent'] >= 2).mean():.0%} of team-seasons, >= 4 games in {(ev['absent'] >= 4).mean():.0%}")
    print(f"absorber is on the week-1 chart (as RB2/RB3): {events['absorber_on_chart'].mean():.0%}; a player not on it: {1 - events['absorber_on_chart'].mean():.0%}")

    # a predictor can only hit when the absorber was on the chart, so the random baseline is computed over those events only
    for_pred = events[events["absorber_on_chart"] & (events["n_candidates"] >= 1)]
    print(f"\nHow often each preseason predictor picks the actual absorber, over the {len(for_pred)} events where he was on the chart (random = mean of 1/candidates):")
    print(f"  {'predictor':<15}{'hit rate':>9}{'random':>9}{'lift':>7}{'avg gain of pick':>18}{'random pick':>13}{'absorber':>10}")
    baseline = (1 / for_pred["n_candidates"]).mean()
    for name in PREDICTORS:
        if f"hit_{name}" not in for_pred:
            continue
        hit = for_pred[f"hit_{name}"].mean()
        print(f"  {name:<15}{hit:>9.1%}{baseline:>9.1%}{hit / baseline:>7.2f}{for_pred[f'gain_{name}'].mean():>18.1f}{for_pred['gain_random'].mean():>13.1f}{for_pred['absorber_gain'].mean():>10.1f}")
    print(f"  (a binomial SE on a hit rate near {baseline:.0%} is about {np.sqrt(baseline * (1 - baseline) / len(for_pred)):.1%}; gains are PPR points over the player's own baseline, per event)")

    n_all = len(ev)
    print(f"\nPPR points per team-season (all {n_all}, events or not) a backup would have added over his own baseline while the starter was out:")
    print(f"  {'picking a chart RB at random':<30}: {ev['gain_random'].fillna(0).sum() / n_all:5.1f}")
    for name in PREDICTORS:
        if f"gain_{name}" in ev:
            print(f"  picking by {name:<19}: {ev[f'gain_{name}'].fillna(0).sum() / n_all:5.1f}")
    print(f"  {'the actual absorber (hindsight)':<30}: {ev['absorber_gain'].fillna(0).sum() / n_all:5.1f}")

    pairs = ev.dropna(subset=["rb2_share"]).set_index(["team", "season"])["rb2_share"]
    joined = [(pairs[(t, s)], pairs[(t, s + 1)]) for (t, s) in pairs.index if (t, s + 1) in pairs.index]
    if len(joined) >= 10:
        a, b = zip(*joined)
        r = spearmanr(a, b)[0]
        print(f"\nShare of the vacated points the depth-chart RB2 absorbed, same team in consecutive seasons: Spearman {r:+.2f} (n = {len(joined)} pairs; "
              f"|r| under about {2 / np.sqrt(len(joined)):.2f} is indistinguishable from none)")


if __name__ == "__main__":
    main()
