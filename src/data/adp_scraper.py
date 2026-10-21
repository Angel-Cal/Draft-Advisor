"""Historical preseason ADP: FantasyPros PPR consensus ADP from Wayback Machine snapshots,
closest to the day before each season's opener, mapped to gsis player_id."""

import io
import re
import sys
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.vor import normalize_names

ROOT = Path(__file__).parent.parent.parent
CACHE_DIR = ROOT / "data" / "raw" / "adp_html"
FP_URL = "fantasypros.com/nfl/adp/ppr-overall.php"
HEADERS = {"User-Agent": "Mozilla/5.0"}
POSITIONS = ["QB", "RB", "WR", "TE"]
SEASON_OPENERS = {2021: "2021-09-09", 2022: "2022-09-08", 2023: "2023-09-07",
                  2024: "2024-09-05", 2025: "2025-09-04"}
NAME_ALIASES = {"hollywood brown": "marquise brown", "gabe davis": "gabriel davis",
                "kenny gainwell": "kenneth gainwell", "chig okonkwo": "chigoziem okonkwo",
                "ken walker": "kenneth walker", "joshua palmer": "josh palmer",
                "mitch trubisky": "mitchell trubisky", "robby anderson": "robbie chosen", "robbie anderson": "robbie chosen"}
ID_OVERRIDES = {("mike williams", "WR"): "00-0033536", ("kyle williams", "WR"): "00-0040131"}


def wayback_get(url, params=None, retries=8):
    """Wayback throttles by refusing connections or returning 503, so back off and retry."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=120)
            if resp.ok and resp.text.strip():
                time.sleep(3)
                return resp
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"Wayback request failed after {retries} attempts: {url}")


def closest_snapshot(season):
    target = datetime.strptime(SEASON_OPENERS[season], "%Y-%m-%d") - timedelta(days=1)
    window = lambda days: (target + timedelta(days=days)).strftime("%Y%m%d")
    resp = wayback_get("https://web.archive.org/cdx/search/cdx", params={
        "url": FP_URL, "from": window(-21), "to": window(0), "output": "json",
        "fl": "timestamp", "filter": "statuscode:200"})
    stamps = [row[0] for row in resp.json()[1:]]
    return min(stamps, key=lambda ts: abs(datetime.strptime(ts, "%Y%m%d%H%M%S") - target))


def fetch_html(season, timestamp):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{season}_{timestamp}.html"
    if not path.exists():
        resp = wayback_get(f"https://web.archive.org/web/{timestamp}id_/https://www.{FP_URL}")
        path.write_text(resp.text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def parse_adp(html, season, timestamp):
    table = max(pd.read_html(io.StringIO(html)), key=len)
    player = table["Player Team (Bye)"].str.extract(r"^(?P<Player>.+?)\s+(?P<team>[A-Z]{2,3})\s+\(\d+\)$")
    df = pd.DataFrame({"season": season, "snapshot": timestamp, "rank": table["Rank"],
                       "Player": player["Player"], "team": player["team"],
                       "position": table["POS"].str.extract(r"^([A-Z]+)")[0], "adp": table["AVG"]})
    return df[df["position"].isin(POSITIONS) & df["Player"].notna()]


def attach_player_ids(adp, ids):
    adp = adp.copy()
    adp["Player"] = adp["Player"].str.replace(r"\s+(Sr\.?|II|IV|V)$", "", regex=True)
    adp = normalize_names(adp).rename(columns={"Player": "name"})
    adp["merge_name"] = adp["merge_name"].replace(NAME_ALIASES)
    ids = ids[ids["position"].isin(POSITIONS)].dropna(subset=["gsis_id"])
    ids = ids.drop_duplicates(subset=["merge_name", "position"], keep=False)
    adp = adp.merge(ids[["merge_name", "position", "gsis_id"]], on=["merge_name", "position"], how="left") \
             .rename(columns={"gsis_id": "player_id"})
    by_name = ids.drop_duplicates(subset="merge_name", keep=False).set_index("merge_name")["gsis_id"]
    adp["player_id"] = adp["player_id"].fillna(adp["merge_name"].map(by_name))  # position differs between sources
    overrides = pd.Series(list(zip(adp["merge_name"], adp["position"]))).map(ID_OVERRIDES)
    adp["player_id"] = adp["player_id"].fillna(overrides)
    return adp


if __name__ == "__main__":
    frames = []
    for season in SEASON_OPENERS:
        timestamp = closest_snapshot(season)
        print(f"{season}: snapshot {timestamp}")
        frames.append(parse_adp(fetch_html(season, timestamp), season, timestamp))
    adp = pd.concat(frames, ignore_index=True)
    adp = attach_player_ids(adp, pd.read_parquet(ROOT / "data" / "raw" / "ids.parquet"))

    unmatched = adp[adp["player_id"].isna()]
    print(f"{len(adp)} rows, {len(unmatched)} without player_id")
    print(unmatched[["season", "name", "position", "rank"]].sort_values("rank").head(30).to_string())

    adp[["season", "snapshot", "player_id", "name", "position", "team", "rank", "adp"]].to_csv(
        ROOT / "data" / "processed" / "historical_adp.csv", index=False)
