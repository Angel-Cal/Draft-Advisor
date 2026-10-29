import numpy as np
import pandas as pd
import pytest
from src.data import validate as v
from src.draft.market_fallback import fit_position_curves, market_projections, SYNTHETIC_PREFIX


def history():
    ranks = np.arange(1, 21)
    return pd.concat([pd.DataFrame({"position": position, "position_rank": ranks, "actual_ppr": top - 10.0 * ranks})
                      for position, top in [("QB", 400.0), ("RB", 350.0), ("WR", 300.0), ("TE", 250.0)]])


def adp_table(rows):
    frame = pd.DataFrame(rows, columns=["Player", "Position", "ADP", "player_id"])
    frame["merge_name"] = frame["Player"].str.lower()
    return frame


def test_curves_are_monotone_and_ranked_per_position():
    curves = fit_position_curves(history())
    assert curves["QB"].predict([1])[0] > curves["QB"].predict([10])[0] > curves["QB"].predict([20])[0]
    assert curves["QB"].predict([1])[0] > curves["WR"].predict([1])[0]


def test_fallback_only_for_unmodeled_players_and_rank_counts_everyone():
    table = adp_table([("Star WR", "WR-01", 1, "a"), ("Rookie WR", "WR-02", 2, None),
                       ("Vet WR", "WR-03", 3, "b"), ("Star RB", "RB-01", 4, "c")])
    out = market_projections(table, model_player_ids={"a", "b", "c"}, curves=fit_position_curves(history()))
    assert list(out["player_name"]) == ["Rookie WR"]
    row = out.iloc[0]
    assert row["player_id"] == SYNTHETIC_PREFIX + "rookie wr" and bool(row["market_estimate"])
    assert row["projected_ppr"] == pytest.approx(300.0 - 10.0 * 2)       # WR #2 by ADP, though modeled WRs sit around it


def test_fallback_players_with_real_ids_keep_them():
    table = adp_table([("Returning Vet", "RB-01", 1, "x1")])
    out = market_projections(table, model_player_ids=set(), curves=fit_position_curves(history()))
    assert out.iloc[0]["player_id"] == "x1"


def advisor_table(**overrides):
    base = pd.DataFrame({"player_id": ["a", "b"], "projected_ppr": [200.0, 150.0], "vor": [50.0, 0.0], "tier": [1, 2],
                         "adp": [1, 2], "position": ["QB", "RB"], "market_estimate": [False, True]})
    return base.assign(**overrides)


def test_advisor_table_check():
    v.check_advisor_table(advisor_table())
    with pytest.raises(v.DataIntegrityError, match="duplicate"):
        v.check_advisor_table(advisor_table(player_id=["a", "a"]))
    with pytest.raises(v.DataIntegrityError, match="nulls in vor"):
        v.check_advisor_table(advisor_table(vor=[np.nan, 0.0]))


def test_fill_from_roster_matches_rookies_by_name_and_position_only_where_missing():
    from src.data.adp_scraper import fill_from_roster
    adp = pd.DataFrame({"merge_name": ["jeremiyah love", "kyle williams", "kept", "nobody"], "position": ["RB", "WR", "WR", "TE"],
                        "player_id": [None, None, "old_id", None]})
    roster = pd.DataFrame({"full_name": ["Jeremiyah Love", "Kyle Williams", "Kyle Williams", "Kept", "A Defender"],
                           "position": ["RB", "WR", "WR", "WR", "DB"], "gsis_id": ["g_love", "g_kw1", "g_kw2", "g_other", "g_db"]})
    out = fill_from_roster(adp, roster).set_index("merge_name")["player_id"]
    assert out["jeremiyah love"] == "g_love"
    assert pd.isna(out["kyle williams"])           # two same-name WRs are ambiguous, left unmatched
    assert out["kept"] == "old_id"                 # an id already there is never replaced
    assert pd.isna(out["nobody"])
