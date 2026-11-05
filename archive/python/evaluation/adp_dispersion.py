"""Is the model's disagreement with the ADP curve more trustworthy where the ADP sources disagree with each other?

Mechanism: FantasyPros ADP averages several platforms (ESPN, Sleeper, CBS, ...). Where they agree the consensus is probably well informed and the
model's gap should be mostly noise; where they disagree the consensus is itself uncertain, so an independent estimate deserves more weight
(inverse-variance weighting). Prediction: the slope b in `actual - curve = b x (model - curve)` is lower where the sources agree.
Kill: the difference between the "agree" and "disagree" slopes is inside the spread of the same difference with dispersion shuffled within season.

Dispersion = SD of log(source ADP) over the platforms that list the player (3 or more), minus its typical value at that ADP (quadratic in log ADP),
so it is not a stand-in for ADP itself. Per-source ADPs come from the cached FantasyPros pages (data/raw/adp_html, the snapshots that
adp_{season}.csv was built from). Rows: draftable modeled players (top 150 by ADP among non-market rows), 2019-2025, in the validated files
(data/processed/live) and the live-recipe files (data/processed/experiments/worlds/routed/routed). The curve is the isotonic position-rank curve fit on earlier seasons
only (2015 on), as in gap_reliability.py. Writes nothing; run: python src/evaluation/adp_dispersion.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.paths import LIVE, WORLDS as WORLDS_DIR
from src.data.market_fallback import load_history
from src.evaluation.blend_test import curve_points

ROOT = Path(__file__).parent.parent.parent
HTML_DIR = ROOT / "data" / "raw" / "adp_html"
EXTERNAL_DIR = ROOT / "data" / "external"
SEASONS = range(2019, 2026)
WORLDS = {"validated": LIVE, "live recipe": WORLDS_DIR / "routed" / "routed"}
SOURCES = {"ESPN", "MFL", "FFC", "RTSports", "NFL", "Fantrax", "Sleeper", "CBS"}
MIN_SOURCES = 3
TOP_N = 150
N_BOOT = 2000
N_PERM = 2000
SEED = 0


def source_adps(season):
    """player_id -> list of the platforms' ADPs, parsed from the cached page that adp_{season}.csv was built from."""
    adp = pd.read_csv(EXTERNAL_DIR / f"adp_{season}.csv")
    page = (HTML_DIR / f"{season}_{adp['snapshot'].iloc[0]}.html").read_text(encoding="utf-8", errors="ignore")
    header = re.findall(r"<th[^>]*>(.*?)</th>", re.search(r"<thead>(.*?)</thead>", page, re.S).group(1))
    ids = {(n, p): i for n, p, i in zip(adp["name"], adp["position"], adp["player_id"]) if isinstance(i, str)}
    out = {}
    for row in re.findall(r"<tr.*?</tr>", re.search(r"<tbody>(.*?)</tbody>", page, re.S).group(1), re.S):
        name = re.search(r'class="player-name[^"]*"[^>]*>(.*?)</a>', row)
        cells = [c.strip().replace("&nbsp;", "") for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if not name or len(cells) < len(header):
            continue
        key = (name.group(1), re.sub(r"\d", "", cells[2]))
        values = [float(v) for h, v in zip(header, cells) if h in SOURCES and re.fullmatch(r"\d+(\.\d+)?", v)]
        if key in ids and len(values) >= MIN_SOURCES:
            out[ids[key]] = values
    return out


def load_rows():
    """Draftable modeled player-seasons with the curve, the projection in each world and the source dispersion."""
    history = load_history(range(2015, 2026))
    frames = []
    for season in SEASONS:
        curve = curve_points(season, history)
        spread = {pid: np.std(np.log(v), ddof=1) for pid, v in source_adps(season).items()}
        base = None
        for world, folder in WORLDS.items():
            players = json.loads((folder / f"projections_{season}_v1.json").read_text())["players"]
            df = pd.DataFrame(players)[["player_id", "position", "adp", "projected_ppr", "actual_ppr", "market_estimate"]]
            df = df[~df["market_estimate"]].rename(columns={"projected_ppr": world})
            base = df if base is None else base.merge(df[["player_id", world]], on="player_id")
        base["season"] = season
        base["curve"] = base["player_id"].map(curve)
        base["log_sd"] = base["player_id"].map(spread)
        base = base[base["adp"].rank(method="first") <= TOP_N]
        frames.append(base)
    d = pd.concat(frames, ignore_index=True)
    print(f"{len(d)} draftable modeled rows; with a curve and {MIN_SOURCES}+ sources: {d[['curve', 'log_sd']].notna().all(axis=1).sum()}")
    d = d.dropna(subset=["curve", "log_sd"]).copy()
    fit = np.polyfit(np.log(d["adp"]), d["log_sd"], 2)
    d["disp"] = d["log_sd"] - np.polyval(fit, np.log(d["adp"]))
    d["resid"] = d["actual_ppr"] - d["curve"]
    return d


def slope(g, world):
    """Least squares through the origin: share of the model's gap to the curve that shows up in the outcome."""
    gap = g[world] - g["curve"]
    return float((gap * g["resid"]).sum() / (gap ** 2).sum())


def terciles(disp):
    return pd.qcut(disp, 3, labels=["agree", "middle", "disagree"])


def player_boot(g, world, rng):
    players = g["player_id"].unique()
    groups = {p: x for p, x in g.groupby("player_id")}
    return np.percentile([slope(pd.concat([groups[p] for p in rng.choice(players, len(players))]), world) for _ in range(N_BOOT)], [5, 95])


def perm_difference(d, world, rng):
    """Observed disagree-minus-agree slope and its permutation p (dispersion shuffled within season)."""
    def diff(x):
        t = terciles(x["disp"])
        return slope(x[t == "disagree"], world) - slope(x[t == "agree"], world)
    observed = diff(d)
    null = []
    for _ in range(N_PERM):
        shuffled = d.copy()
        shuffled["disp"] = shuffled.groupby("season")["disp"].transform(lambda s: rng.permutation(s.values))
        null.append(diff(shuffled))
    null = np.array(null)
    return observed, float((np.abs(null) >= abs(observed)).mean()), float(np.std(null))


def held_out(d, world):
    """Leave one season out: b per tercile fit on the other seasons (clipped 0-1), applied to the held-out season; RMSE vs model and a uniform b."""
    out = {"model": [], "uniform b": [], "b by tercile": []}
    for season in SEASONS:
        fit, test = d[d["season"] != season], d[d["season"] == season]
        cuts = np.quantile(fit["disp"], [1 / 3, 2 / 3])
        bins = lambda x: np.digitize(x["disp"], cuts)
        b_all = np.clip(slope(fit, world), 0, 1)
        b_t = {k: np.clip(slope(fit[bins(fit) == k], world), 0, 1) for k in range(3)}
        gap = test[world] - test["curve"]
        preds = {"model": test[world], "uniform b": test["curve"] + b_all * gap,
                 "b by tercile": test["curve"] + pd.Series(bins(test), index=test.index).map(b_t) * gap}
        for k, p in preds.items():
            out[k].append(((p - test["actual_ppr"]) ** 2).values)
    return {k: float(np.sqrt(np.concatenate(v).mean())) for k, v in out.items()}


def report(d):
    rng = np.random.default_rng(SEED)
    d["tercile"] = terciles(d["disp"])
    print(f"rows per season {d.groupby('season')['log_sd'].size().to_dict()}; typical log-SD {d['log_sd'].median():.3f} "
          f"(about {np.expm1(d['log_sd'].median()):.0%} of the ADP)\n")
    for world in WORLDS:
        print(f"=== {world} files")
        print(f"{'group':<12}{'position':<9}{'n':>5}{'slope':>8}{'90% interval (players)':>25}{'mean |gap|':>12}")
        for position in ["ALL", "QB", "RB", "WR", "TE"]:
            g = d if position == "ALL" else d[d["position"] == position]
            for name, t in g.groupby("tercile", observed=True):
                lo, hi = player_boot(t, world, rng) if position == "ALL" else (np.nan, np.nan)
                band = f"{lo:.2f} to {hi:.2f}" if position == "ALL" else ""
                print(f"{name:<12}{position:<9}{len(t):>5}{slope(t, world):>8.2f}{band:>25}{(t[world] - t['curve']).abs().mean():>12.0f}")
        obs, p, sd = perm_difference(d, world, rng)
        print(f"disagree minus agree slope {obs:+.2f}; shuffled-dispersion SD {sd:.2f}, permutation p {p:.3f}")
        by_season = {s: round(slope(g[g["tercile"] == "disagree"], world) - slope(g[g["tercile"] == "agree"], world), 2) for s, g in d.groupby("season")}
        print(f"by season (disagree minus agree): {by_season}")
        bands = [(1, 36), (37, 80), (81, 400)]
        cells = []
        for lo_adp, hi_adp in bands:
            g = d[d["adp"].between(lo_adp, hi_adp)]
            half = g["disp"] > g["disp"].median()
            cells.append(f"ADP {lo_adp}-{hi_adp}: low {slope(g[~half], world):.2f} / high {slope(g[half], world):.2f} (n {len(g)})")
        print("within ADP bands, dispersion below / above the band median: " + "; ".join(cells))
        print("held-out RMSE (leave one season out): " + ", ".join(f"{k} {v:.2f}" for k, v in held_out(d, world).items()) + "\n")


if __name__ == "__main__":
    report(load_rows())
