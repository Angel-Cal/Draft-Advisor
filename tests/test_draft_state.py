import pandas as pd
import pytest
from unittest.mock import patch
from tests.conftest import make_predictions_df


def _make_state(df=None, n_teams=12):
    """Create a DraftState with a mocked parquet read."""
    if df is None:
        df = make_predictions_df()
    with patch("src.draft.draft_state.pd.read_parquet", return_value=df):
        from src.draft.draft_state import DraftState
        return DraftState(n_teams=n_teams)


class TestGetCurrentPick:
    def test_round_1_pick_0_returns_0(self):
        state = _make_state()
        state.round = 1
        state.pick_number = 0
        assert state.get_current_pick() == 0

    def test_round_1_pick_5_returns_5(self):
        state = _make_state()
        state.round = 1
        state.pick_number = 5
        assert state.get_current_pick() == 5

    def test_round_2_pick_0_returns_11(self):
        state = _make_state()
        state.round = 2
        state.pick_number = 0
        assert state.get_current_pick() == abs(12 - 1 - 0)  # 11

    def test_round_2_pick_11_returns_0(self):
        state = _make_state()
        state.round = 2
        state.pick_number = 11
        assert state.get_current_pick() == abs(12 - 1 - 11)  # 0


class TestDraftPlayer:
    def test_returns_none_for_already_drafted_player(self):
        state = _make_state()
        state.draft_player("qb1")
        result = state.draft_player("qb1")
        assert result is None

    def test_returns_true_on_success(self):
        state = _make_state()
        result = state.draft_player("qb1")
        assert result is True

    def test_removes_player_from_available(self):
        state = _make_state()
        state.draft_player("qb1")
        assert not (state.available_players["player_id"] == "qb1").any()

    def test_adds_player_to_correct_team(self):
        state = _make_state()
        state.round = 1
        state.pick_number = 0   # team 0 picks first
        state.draft_player("qb1")
        assert "qb1" in state.team_list[0].get_picks()

    def test_pick_number_increments(self):
        state = _make_state()
        state.draft_player("qb1")
        assert state.pick_number == 1

    def test_round_increments_when_pick_number_wraps(self):
        state = _make_state(n_teams=2)
        df = make_predictions_df()
        state.available_players = df.copy()
        state.pick_number = 1   # one more pick → wraps to 0, round → 2
        state.round = 1
        state.draft_player("rb1")
        assert state.round == 2
        assert state.pick_number == 0
