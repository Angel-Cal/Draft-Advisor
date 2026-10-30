"""Does the advisor's WR-over-RB lean come from what the model learned, or from the lineup structure? (LOG.md, 2026-10-30)

Copies of the backtest files in which every projection is replaced by an ADP-to-points curve fitted on 2015-2018 only (position rank by ADP -> expected season PPR, the same isotonic curve the
advisor's market rows use), so no model and no outcome after 2018 reaches the advisor. ADP, outcomes and flags are untouched. If the advisor still swaps WR for RB in rounds 3-6 at about the
usual rate (`calibrate-deviations`), the lean comes from the lineup structure of the league, not from anything the model learned from the 2020-23 RB busts.

Run: python src/evaluation/adp_curve_world.py [--fit 2019,2024] [--out curveworld_boom]   (default fit 2015-2018, writes data/processed/curveworld; `calibrate-deviations --data data/processed/curveworld --seasons 2019-2025`)
`--fit` picks other seasons for the curve, e.g. only the seasons RBs beat their ADP pricing, to see whether the lean survives a curve that says RBs are good value.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.market_fallback import fit_position_curves, load_history

ROOT = Path(__file__).parent.parent.parent
PROCESSED = ROOT / "data" / "processed"
SEASONS = range(2019, 2026)
FIT_SEASONS = range(2015, 2019)


def option(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    fit_seasons = [int(x) for x in option("--fit", "").split(",") if x] or FIT_SEASONS
    curves = fit_position_curves(load_history(fit_seasons))
    out = PROCESSED / option("--out", "curveworld")
    out.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        data = json.loads((PROCESSED / f"projections_{season}_v1.json").read_text())
        players = pd.DataFrame(data["players"])
        rank = players.groupby("position")["adp"].rank(method="first")
        for player, r in zip(data["players"], rank):
            player["projected_ppr"] = round(float(curves[player["position"]].predict([r])[0]), 2)
            player["market_estimate"] = True
        data["adp_source"] = data["adp_source"] + "; projected_ppr = ADP curve fitted on " + ",".join(map(str, fit_seasons)) + " (adp_curve_world.py)"
        (out / f"projections_{season}_v1.json").write_text(json.dumps(data))
    print(f"wrote {out}")
