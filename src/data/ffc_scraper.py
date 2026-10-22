"""Real draft-to-draft pick spread: Fantasy Football Calculator's public ADP API, 12-team PPR, one file per season.

Each player carries his mean pick (adp), the standard deviation of his pick across the mock drafts (stdev) and how often he was
taken. It is not used as an ADP source; the C# simulator compares its opponents' pick spread with it (`calibrate-noise`)."""

import json
import sys
import time
import requests
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
OUT_DIR = ROOT / "data" / "raw" / "ffc"
URL = "https://fantasyfootballcalculator.com/api/v1/adp/ppr"
SEASONS = range(2021, 2026)
REQUIRED = {"adp", "stdev", "times_drafted"}


def fetch(season):
    resp = requests.get(URL, params={"teams": 12, "year": season}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "Success" or not data.get("players"):
        raise RuntimeError(f"FFC returned no players for {season}: {data.get('status')}")
    missing = REQUIRED - set(data["players"][0])
    if missing:
        raise RuntimeError(f"FFC {season} rows lack {sorted(missing)}")
    return data


if __name__ == "__main__":
    refresh = "--refresh" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        path = OUT_DIR / f"ffc_ppr12_{season}.json"
        if path.exists() and not refresh:
            print(f"{season}: cached")
            continue
        data = fetch(season)
        path.write_text(json.dumps(data))
        print(f"{season}: {len(data['players'])} players over {data['meta']['total_drafts']} drafts")
        time.sleep(1)
