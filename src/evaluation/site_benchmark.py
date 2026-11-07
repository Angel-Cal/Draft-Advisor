"""Model vs Sleeper's (Rotowire) preseason projections on the benchmark's per-position Spearman, seasons 2021-2025.

Sleeper's season-total projections are revised through the season (Puka Nacua 2023 reads 229 PPR), so the
preseason view is the week-1 projection: per-game PPR set before the opener, ranked as is (x17 changes nothing).
Players with no week-1 projection get 0. Cached under data/raw/sleeper/.
"""
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.evaluation.benchmark import SEASONS, TOP_N_ADP, load_season

ROOT = Path(__file__).parent.parent.parent
CACHE = ROOT / "data" / "raw" / "sleeper"
URL = "https://api.sleeper.com/projections/nfl/{season}/1?season_type=regular&position[]=QB&position[]=RB&position[]=WR&position[]=TE"


def sleeper_week1(season):
    """Sleeper's week-1 PPR projection per gsis player_id for one season (downloaded once, then cached)."""
    path = CACHE / f"week1_{season}.json"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL.format(season=season), headers={"User-Agent": "DraftBot research"})
        path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    rows = [{"sleeper_id": str(r["player_id"]), "sleeper_pg": r["stats"].get("pts_ppr")}
            for r in json.loads(path.read_text())]
    return pd.DataFrame(rows).dropna()


def id_map():
    """sleeper_id -> gsis player_id from the nflverse/DynastyProcess id table cached in data/raw/ids.parquet."""
    ids = pd.read_parquet(ROOT / "data" / "raw" / "ids.parquet")
    ids = ids.dropna(subset=["sleeper_id", "gsis_id"])
    ids["sleeper_id"] = ids["sleeper_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    return ids[["sleeper_id", "gsis_id"]].drop_duplicates("sleeper_id").rename(columns={"gsis_id": "player_id"})


def score(df, season, scope):
    """Per-position Spearman vs actual PPR for model (5-seed mean), ADP and Sleeper week 1."""
    seed_cols = [c for c in df.columns if c.startswith("oos_pred_s")]
    rows = []
    for position, g in df.groupby("position"):
        rows.append({"season": season, "scope": scope, "position": position, "n": len(g),
                     "sleeper_coverage": g["has_sleeper"].mean(),
                     "model": np.mean([spearmanr(g[c], g["actual_ppr"])[0] for c in seed_cols]),
                     "sleeper": spearmanr(g["sleeper_pg"], g["actual_ppr"])[0],
                     "adp": spearmanr(-g["adp"], g["actual_ppr"])[0]})
    return rows


if __name__ == "__main__":
    ids = id_map()
    rows = []
    for season in SEASONS:
        sl = sleeper_week1(season).merge(ids, on="sleeper_id").drop_duplicates("player_id")
        df = load_season(season).merge(sl[["player_id", "sleeper_pg"]], on="player_id", how="left")
        df["has_sleeper"] = df["sleeper_pg"].notna()
        df["sleeper_pg"] = df["sleeper_pg"].fillna(0)
        rows += score(df, season, "overall")
        rows += score(df[df["in_top_adp"]], season, f"top{TOP_N_ADP}_adp")
    res = pd.DataFrame(rows)
    mean = res.groupby(["scope", "position"], as_index=False)[["n", "sleeper_coverage", "model", "sleeper", "adp"]].mean()
    print(res.round(3).to_string(index=False))
    print("\nMEAN 2021-2025")
    print(mean.round(3).to_string(index=False))
