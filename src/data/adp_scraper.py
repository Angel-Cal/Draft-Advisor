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
SEASON_OPENERS = {2019: "2019-09-05", 2020: "2020-09-10", 2021: "2021-09-09", 2022: "2022-09-08", 2023: "2023-09-07",
                  2024: "2024-09-05", 2025: "2025-09-04", 2026: "2026-09-09"}
# how far before the day before the opener to look for a capture; 2026 has none inside 21 days (the last pre-season capture is 2026-08-15, 24 days before)
WINDOW_DAYS = {2026: 30}
# 2019 has no capture before the opener (Sep 5); the only one is Sep 9, so look this many days past the day before the opener. The page's own source dates
# (`source_dates`) say whether its data predates Week 1, which is what matters.
AFTER_DAYS = {2019: 6}
# the live page lists its sources' dates (ESPN, CBS, Sleeper, Fantrax 9/07, RTSports 9/06), so an export of it is the pre-season ADP, dated 2026-09-07
# 2015-2018: FantasyPros' year view of the PPR ADP, exported by hand (no capture dates are printed; the Sleeper and RTSports columns are mostly empty then), used as the market input of the ADP-conditioned model
LOCAL_EXPORT_SNAPSHOT = {2015: "preseason", 2016: "preseason", 2017: "preseason", 2018: "preseason", 2026: "20260907"}
NAME_ALIASES = {"hollywood brown": "marquise brown", "gabe davis": "gabriel davis",
                "kenny gainwell": "kenneth gainwell", "chig okonkwo": "chigoziem okonkwo",
                "ken walker": "kenneth walker", "joshua palmer": "josh palmer",
                "mitch trubisky": "mitchell trubisky", "robby anderson": "robbie chosen", "robbie anderson": "robbie chosen",
                "benjamin watson": "ben watson", "william fuller": "will fuller", "robert kelley": "rob kelley"}
ID_OVERRIDES = {("mike williams", "WR"): "00-0033536", ("kyle williams", "WR"): "00-0040131",
                # ambiguous names in the 2015-2018 exports: the veterans, not the later namesakes
                ("frank gore", "RB"): "00-0023500", ("steve smith", "WR"): "00-0020337", ("zach miller", "TE"): "00-0025425"}


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
    back = WINDOW_DAYS.get(season, 21)
    resp = wayback_get("https://web.archive.org/cdx/search/cdx", params={
        "url": FP_URL, "from": window(-back), "to": window(AFTER_DAYS.get(season, 0)), "output": "json",
        "fl": "timestamp", "filter": "statuscode:200"})
    stamps = [row[0] for row in resp.json()[1:]]
    return min(stamps, key=lambda ts: abs(datetime.strptime(ts, "%Y%m%d%H%M%S") - target))


def fetch_html(season, timestamp):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{season}_{timestamp}.html"
    if not path.exists():
        resp = wayback_get(f"https://web.archive.org/web/{timestamp}id_/https://www.{FP_URL}")
        if "<table" not in resp.text:      # Wayback answers 200 with a block notice when it flags the client as a bot
            raise RuntimeError(f"Wayback returned no ADP table for {season} ({resp.text[:120]!r}); wait before retrying")
        path.write_text(resp.text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def source_dates(html):
    """The dates the page prints for its sources (FantasyPros lists e.g. 'ESPN 9/07'); empty if the page does not."""
    text = re.sub(r"<[^>]+>", " ", html)
    return sorted(set(re.findall(r"(?:ESPN|CBS|Sleeper|Fantrax|RTSports|NFL|Yahoo|MyFantasyLeague|MFL)[^0-9]{0,40}(\d{1,2}/\d{1,2})", text)))


def parse_adp(html, season, timestamp):
    table = max(pd.read_html(io.StringIO(html)), key=len)
    player = table["Player Team (Bye)"].str.extract(r"^(?P<Player>.+?)\s+(?P<team>[A-Z]{2,3})\s+\(\d+\)$")
    df = pd.DataFrame({"season": season, "snapshot": timestamp, "rank": table["Rank"],
                       "Player": player["Player"], "team": player["team"],
                       "position": table["POS"].str.extract(r"^([A-Z]+)")[0], "adp": table["AVG"]})
    return df[df["position"].isin(POSITIONS) & df["Player"].notna()]


def parse_adp_csv(path, season, snapshot):
    """FantasyPros' own CSV export of the ADP page (columns Rank, "Player (Bye)", POS, ESPN, Sleeper, CBS, RTSports, Fantrax, AVG, Real-Time): same frame as parse_adp."""
    table = pd.read_csv(path)
    player = table["Player (Bye)"].str.extract(r"^(?P<Player>.+?)(?:\s+(?!(?:II|III|IV)$)(?P<team>[A-Z]{2,3})(?:\s+\(\d+\))?)?$")      # older exports often carry no team or bye, or a team without the bye (a name suffix is not a team)
    df = pd.DataFrame({"season": season, "snapshot": snapshot, "rank": table["Rank"], "Player": player["Player"], "team": player["team"],
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


def fill_from_roster(adp, roster):
    """Fill missing player_ids by (name, position) from a season roster (ids.parquet predates that year's draft, so its rookies are absent)."""
    roster = roster[roster["position"].isin(POSITIONS)].dropna(subset=["gsis_id", "full_name"])
    roster = normalize_names(roster.rename(columns={"full_name": "Player"})).rename(columns={"Player": "name"})
    roster = roster.drop_duplicates(subset=["merge_name", "position"], keep=False)
    by_key = roster.set_index(["merge_name", "position"])["gsis_id"]
    keys = pd.MultiIndex.from_frame(adp[["merge_name", "position"]])
    adp = adp.copy()
    adp["player_id"] = adp["player_id"].fillna(pd.Series(by_key.reindex(keys).to_numpy(), index=adp.index))
    return adp


if __name__ == "__main__":
    seasons = [int(a) for a in sys.argv[1:]] or list(SEASON_OPENERS)      # e.g. `python adp_scraper.py 2026` refreshes one season
    frames = []
    for season in seasons:
        local = ROOT / "data" / "external" / f"FantasyPros_{season}_Overall_ADP_Rankings.csv"      # a CSV export of the live page, when we have one
        if local.exists():
            timestamp = LOCAL_EXPORT_SNAPSHOT[season]
            print(f"{season}: local FantasyPros export {local.name} (ADP dated {timestamp})")
            frames.append(parse_adp_csv(local, season, timestamp))
            continue
        timestamp = closest_snapshot(season)
        print(f"{season}: snapshot {timestamp}")
        html = fetch_html(season, timestamp)
        print(f"{season}: dates printed on the page: {source_dates(html) or 'none found'}")
        frames.append(parse_adp(html, season, timestamp))
    adp = pd.concat(frames, ignore_index=True)
    adp = attach_player_ids(adp, pd.read_parquet(ROOT / "data" / "raw" / "ids.parquet"))
    for season in seasons:
        roster_path = ROOT / "data" / "raw" / f"roster_{season}.parquet"      # exists for the not-yet-played season only
        if roster_path.exists():
            this = adp["season"] == season
            adp[this] = fill_from_roster(adp[this], pd.read_parquet(roster_path))

    unmatched = adp[adp["player_id"].isna()]
    print(f"{len(adp)} rows, {len(unmatched)} without player_id")
    print(unmatched[["season", "name", "position", "rank"]].sort_values("rank").head(30).to_string())

    out_dir = ROOT / "data" / "external"
    out_dir.mkdir(parents=True, exist_ok=True)
    adp = adp.dropna(subset=["player_id"])
    for season, season_df in adp.groupby("season"):
        season_df[["season", "snapshot", "player_id", "name", "position", "team", "rank", "adp"]].to_csv(
            out_dir / f"adp_{season}.csv", index=False)
