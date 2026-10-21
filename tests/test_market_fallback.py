import numpy as np
import pandas as pd
import pytest
from src.data import validate as v
from src.draft.market_fallback import fit_position_curves, market_projections, SYNTHETIC_PREFIX
from src.draft.vor import add_player_id


def history():
    ranks = np.arange(1, 21)
    return pd.concat([pd.DataFrame({"position": position, "position_rank": ranks, "actual_ppr": top - 10.0 * ranks})
                      for position, top in [("QB", 400.0), ("RB", 350.0), ("WR", 300.0), ("TE", 250.0)]])


def adp_table(rows):
    frame = pd.DataFrame(rows, columns=["Player", "Position", "ADP", "Underdog", "player_id"])
    frame["merge_name"] = frame["Player"].str.lower()
    return frame


def test_curves_are_monotone_and_ranked_per_position():
    curves = fit_position_curves(history())
    assert curves["QB"].predict([1])[0] > curves["QB"].predict([10])[0] > curves["QB"].predict([20])[0]
    assert curves["QB"].predict([1])[0] > curves["WR"].predict([1])[0]


def test_fallback_only_for_unmodeled_players_and_rank_counts_everyone():
    table = adp_table([("Star WR", "WR-01", 1, 1, "a"), ("Rookie WR", "WR-02", 2, 2, None),
                       ("Vet WR", "WR-03", 3, 3, "b"), ("Star RB", "RB-01", 4, 4, "c")])
    out = market_projections(table, model_player_ids={"a", "b", "c"}, curves=fit_position_curves(history()))
    assert list(out["player_name"]) == ["Rookie WR"]
    row = out.iloc[0]
    assert row["player_id"] == SYNTHETIC_PREFIX + "rookie wr" and bool(row["market_estimate"])
    assert row["projected_ppr"] == pytest.approx(300.0 - 10.0 * 2)       # WR #2 by ADP, though modeled WRs sit around it


def test_fallback_players_with_real_ids_keep_them():
    table = adp_table([("Returning Vet", "RB-01", 1, 1, "x1")])
    out = market_projections(table, model_player_ids=set(), curves=fit_position_curves(history()))
    assert out.iloc[0]["player_id"] == "x1"


def ids_table():
    return pd.DataFrame({
        "gsis_id": ["g_new", None, "g_wr", "g_rb", "g_old"],
        "merge_name": ["michael pittman", "michael pittman", "kyle williams", "kyle williams", "taysom hill"],
        "position": ["WR", "RB", "WR", "RB", "TE"],
        "draft_year": [2020.0, 1998.0, 2025.0, 2010.0, 2017.0],
        "db_season": [2025, 2025, 2025, 2025, 2025]})


def test_player_id_matching_is_unique_and_position_aware():
    adp = adp_table([("michael pittman", "WR-44", 95, 95, None), ("kyle williams", "RB-60", 200, 200, None),
                     ("taysom hill", "QB-30", 160, 160, None), ("brand new rookie", "WR-60", 170, 170, None)])
    out = add_player_id(adp.drop(columns="player_id"), ids_table())
    assert len(out) == 4
    by_name = out.set_index("merge_name")["player_id"]
    assert by_name["michael pittman"] == "g_new"        # the id-less 1998 RB never matches
    assert by_name["kyle williams"] == "g_rb"           # position decides between same-name players
    assert by_name["taysom hill"] == "g_old"            # position disagreement falls back to the unique active name
    assert pd.isna(by_name["brand new rookie"])


def advisor_table(**overrides):
    base = pd.DataFrame({"player_id": ["a", "b"], "projected_ppr": [200.0, 150.0], "vor": [50.0, 0.0], "tier": [1, 2],
                         "underdog": [1, 2], "position": ["QB", "RB"], "market_estimate": [False, True]})
    return base.assign(**overrides)


def test_advisor_table_check():
    v.check_advisor_table(advisor_table())
    with pytest.raises(v.DataIntegrityError, match="duplicate"):
        v.check_advisor_table(advisor_table(player_id=["a", "a"]))
    with pytest.raises(v.DataIntegrityError, match="nulls in vor"):
        v.check_advisor_table(advisor_table(vor=[np.nan, 0.0]))
