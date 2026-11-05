"""Do per-opportunity skill rates explain what the ADP curve and the model miss?

User's hypothesis (2026-10-28): ADP averages the sharp drafters away, so a stat the sharp ones use (yards per route run, yards after contact) may
still explain results the market missed. Two read-only diagnostics on the walk-forward predictions for draftable players (2022-2025, the rows
`gap_reliability.load_rows` builds), each metric taken from the PRIOR season:

  receiving  per pass play on the field (the route-run proxy: participation has no per-player routes, only the targeted receiver's route):
             targets, yards and first downs per pass play, plus yards per target, for WR, TE and RB
  rb_contact PFR rushing splits (2018+): yards after contact, yards before contact (mostly the line) and broken tackles per carry, plus plain
             yards per carry, for RB with at least MIN_CARRIES carries

First the year-to-year persistence of each metric (is it a skill or a result?), then for each position the Spearman correlation of the metric with
`actual - curve` and `actual - model`, and the coefficient of its z-score in `actual - curve ~ gap + z` (PPR points per standard deviation, beyond
both the market and the model) with a 90% bootstrap interval resampling players and a permutation p-value. Many metric x position cells are looked
at, so one hit is a lead, not a finding. Writes only the PFR cache; run:
python src/evaluation/skill_vs_market.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.gap_reliability import load_rows
from src.features.advanced import _on_field_counts

RAW = Path(__file__).parent.parent.parent / "data" / "raw"
PFR_CACHE = RAW / "pfr_rush_18_25.parquet"
MIN_PASS_PLAYS = 150     # on the field for fewer pass plays than this: a per-play rate is not trusted
MIN_CARRIES = 80
MIN_GAMES = 6
N_BOOT = 2000
N_PERM = 2000
SEED = 0
RECEIVING = ["tpp", "ypp", "fdpp", "ypt"]
CONTACT = ["yac_att", "ybc_att", "broken_att", "ypc"]
LABELS = {"tpp": "targets / pass play", "ypp": "yards / pass play", "fdpp": "first downs / pass play", "ypt": "yards / target",
          "yac_att": "yards after contact / carry", "ybc_att": "yards before contact / carry", "broken_att": "broken tackles / carry", "ypc": "yards / carry"}


def receiving_rates():
    """Per player-season (2020-2025): pass plays on the field, targets, yards and first downs per pass play, yards per target."""
    participation = pd.read_parquet(RAW / "participation_16_25.parquet")
    participation = participation[participation["nflverse_game_id"] >= "2020"]
    pbp = pd.read_parquet(RAW / "pbp_20_25.parquet", columns=["game_id", "play_id", "season", "season_type", "pass", "rush"])
    on_field = _on_field_counts(participation, pbp).groupby(["player_id", "season"], as_index=False)["pass_plays"].sum()
    w = pd.read_parquet(RAW / "weekly_20_25.parquet", columns=["player_id", "season", "week", "season_type", "targets", "receiving_yards", "receiving_first_downs"])
    w = w[w["season_type"] == "REG"]
    g = w.groupby(["player_id", "season"]).agg(games=("week", "nunique"), targets=("targets", "sum"), yards=("receiving_yards", "sum"),
                                              first_downs=("receiving_first_downs", "sum")).reset_index()
    g = g.merge(on_field, on=["player_id", "season"])
    g = g[(g["pass_plays"] >= MIN_PASS_PLAYS) & (g["games"] >= MIN_GAMES)].copy()
    g["tpp"], g["ypp"], g["fdpp"] = g["targets"] / g["pass_plays"], g["yards"] / g["pass_plays"], g["first_downs"] / g["pass_plays"]
    g["ypt"] = g["yards"] / g["targets"].replace(0, np.nan)
    return g[["player_id", "season"] + RECEIVING]


def rb_contact_rates():
    """Per player-season (2018-2025): yards after and before contact and broken tackles per carry (PFR), plus plain yards per carry."""
    if not PFR_CACHE.exists():
        import nflreadpy
        nflreadpy.load_pfr_advstats(list(range(2018, 2026)), stat_type="rush").to_pandas().to_parquet(PFR_CACHE)
    p = pd.read_parquet(PFR_CACHE)
    p = p[p["game_type"] == "REG"]
    ids = pd.read_parquet(RAW / "ids.parquet")[["pfr_id", "gsis_id"]].dropna().drop_duplicates("pfr_id")
    p = p.merge(ids, left_on="pfr_player_id", right_on="pfr_id").rename(columns={"gsis_id": "player_id"})
    g = p.groupby(["player_id", "season"]).agg(games=("week", "nunique"), carries=("carries", "sum"), yac=("rushing_yards_after_contact", "sum"),
                                              ybc=("rushing_yards_before_contact", "sum"), broken=("rushing_broken_tackles", "sum")).reset_index()
    g = g[(g["carries"] >= MIN_CARRIES) & (g["games"] >= MIN_GAMES)].copy()
    g["yac_att"], g["ybc_att"], g["broken_att"] = g["yac"] / g["carries"], g["ybc"] / g["carries"], g["broken"] / g["carries"]
    g["ypc"] = (g["yac"] + g["ybc"]) / g["carries"]
    return g[["player_id", "season"] + CONTACT]


def persistence(rates, metrics, positions):
    """Pearson correlation of each metric with the same metric the next season, for the players in `positions` ({player_id: position})."""
    nxt = rates.assign(season=rates["season"] - 1)
    pair = rates.merge(nxt, on=["player_id", "season"], suffixes=("", "_next"))
    pair["position"] = pair["player_id"].map(positions)
    out = {}
    for pos, g in pair.groupby("position"):
        out[pos] = {m: (round(g[m].corr(g[f"{m}_next"]), 2), len(g)) for m in metrics if g[m].notna().sum() > 20}
    return out


def ols_coef(y, gap, z):
    """Coefficient of z in y ~ 1 + gap + z."""
    x = np.column_stack([np.ones(len(y)), gap, z])
    return np.linalg.lstsq(x, y, rcond=None)[0][2]


def test_cell(g, metric, rng):
    """Spearman with both residuals, the z coefficient in actual - curve ~ gap + z, its bootstrap 90% interval and permutation p."""
    g = g.copy()
    g["z"] = g.groupby("season")[metric].transform(lambda s: (s - s.mean()) / s.std())
    g = g.dropna(subset=["z"])
    y, gap, z = g["resid"].to_numpy(), g["gap"].to_numpy(), g["z"].to_numpy()
    coef = ols_coef(y, gap, z)
    boots = []
    idx_by_player = [np.flatnonzero((g["player_id"] == p).to_numpy()) for p in g["player_id"].unique()]
    for _ in range(N_BOOT):
        idx = np.concatenate([idx_by_player[i] for i in rng.integers(0, len(idx_by_player), len(idx_by_player))])
        boots.append(ols_coef(y[idx], gap[idx], z[idx]))
    perm = []
    for _ in range(N_PERM):
        zp = g.groupby("season")["z"].transform(lambda s: rng.permutation(s.to_numpy())).to_numpy()
        perm.append(ols_coef(y, gap, zp))
    p = float((np.abs(perm) >= abs(coef)).mean())
    return (len(g), spearmanr(g["z"], g["resid"])[0], spearmanr(g["z"], g["actual_ppr"] - g["oos_pred_ppr"])[0], coef,
            np.percentile(boots, 5), np.percentile(boots, 95), p)


def run_tests(d, rates, metrics, positions, rng, title):
    d = d[d["in_top_adp"] & d["position"].isin(positions)].merge(rates.assign(season=rates["season"] + 1), on=["player_id", "season"])
    print(f"\n=== {title}: prior-season metric vs this season's results, draftable player-seasons, 2022-2025")
    print(f"{'position':<9}{'metric':<30}{'n':>5}{'rho vs curve':>14}{'rho vs model':>14}{'coef/SD':>9}{'90% interval':>18}{'perm p':>8}")
    for pos in positions:
        for m in metrics:
            g = d[d["position"] == pos]
            if g[m].notna().sum() < 40:
                continue
            n, r_curve, r_model, coef, lo, hi, p = test_cell(g, m, rng)
            mark = "  <-" if lo > 0 or hi < 0 else ""
            print(f"{pos:<9}{LABELS[m]:<30}{n:>5}{r_curve:>+14.2f}{r_model:>+14.2f}{coef:>+9.1f}{f'{lo:+.1f} to {hi:+.1f}':>18}{p:>8.3f}{mark}")


if __name__ == "__main__":
    rng = np.random.default_rng(SEED)
    d = load_rows()
    positions = dict(zip(d["player_id"], d["position"]))
    receiving, contact = receiving_rates(), rb_contact_rates()
    print("Persistence (r with next season's value, n pairs), draftable-pool positions only")
    for title, rates, metrics in [("receiving rates 2020-25", receiving, RECEIVING), ("RB contact rates 2018-25", contact, CONTACT)]:
        print(f"  {title}: {persistence(rates, metrics, positions)}")
    run_tests(d, receiving, RECEIVING, ["WR", "TE", "RB"], rng, "receiving rates per pass play on the field")
    run_tests(d, contact, CONTACT, ["RB"], rng, "RB contact rates")
