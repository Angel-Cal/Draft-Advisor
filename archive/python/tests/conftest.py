import types
import pandas as pd
import pytest
from src.draft.roster import Roster


def make_predictions_df(rows=None):
    """Minimal predictions DataFrame matching the real pipeline schema."""
    if rows is None:
        rows = [
            {"player_id": "qb1", "player_name": "QB One",   "position": "QB", "projected_ppr": 350.0, "vor": 100.0, "vor_rank": 1.0, "value_gap": 5.0,  "injury_flag": False, "tier": 1},
            {"player_id": "rb1", "player_name": "RB One",   "position": "RB", "projected_ppr": 280.0, "vor":  80.0, "vor_rank": 2.0, "value_gap": 3.0,  "injury_flag": False, "tier": 2},
            {"player_id": "rb2", "player_name": "RB Two",   "position": "RB", "projected_ppr": 260.0, "vor":  60.0, "vor_rank": 3.0, "value_gap": 2.0,  "injury_flag": True,  "tier": 2},
            {"player_id": "wr1", "player_name": "WR One",   "position": "WR", "projected_ppr": 240.0, "vor":  40.0, "vor_rank": 4.0, "value_gap": 1.0,  "injury_flag": False, "tier": 3},
            {"player_id": "wr2", "player_name": "WR Two",   "position": "WR", "projected_ppr": 220.0, "vor":  20.0, "vor_rank": 5.0, "value_gap": -1.0, "injury_flag": False, "tier": 3},
            {"player_id": "wr3", "player_name": "WR Three", "position": "WR", "projected_ppr": 200.0, "vor":   0.0, "vor_rank": 6.0, "value_gap": -2.0, "injury_flag": False, "tier": 4},
            {"player_id": "te1", "player_name": "TE One",   "position": "TE", "projected_ppr": 180.0, "vor": -20.0, "vor_rank": 7.0, "value_gap": -3.0, "injury_flag": False, "tier": 5},
        ]
    return pd.DataFrame(rows)


@pytest.fixture
def mock_draft_state():
    """SimpleNamespace DraftState for recommender tests (no disk I/O)."""
    df = make_predictions_df()
    teams = [Roster() for _ in range(12)]
    state = types.SimpleNamespace(
        available_players=df.copy(),
        predictions_table=df.copy(),
        team_list=teams,
        round=1,
        n_teams=12,
    )
    return state
