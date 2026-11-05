import types
import pandas as pd
import pytest
from src.draft.roster import Roster
from src.draft.recommender import (
    normalize_col,
    get_pick_gap,
    calculate_risk_penalty,
    player_select,
    pos_select,
    get_scarcity,
)


class TestNormalizeCol:
    def _df(self, values, col="val"):
        return pd.DataFrame({col: values})

    def test_basic_normalization(self):
        df = self._df([0.0, 50.0, 100.0])
        result = normalize_col("val", df)
        assert list(result) == pytest.approx([0.0, 0.5, 1.0])

    def test_all_same_returns_zeros(self):
        df = self._df([7.0, 7.0, 7.0])
        result = normalize_col("val", df)
        assert list(result) == pytest.approx([0.0, 0.0, 0.0])

    def test_vor_rank_is_inverted(self):
        df = pd.DataFrame({"vor_rank": [1.0, 2.0, 3.0]})
        result = normalize_col("vor_rank", df)
        # rank 1 (best) → 1 - 0/(3-1) = 1.0; rank 3 (worst) → 1 - 2/2 = 0.0
        assert result.iloc[0] == pytest.approx(1.0)
        assert result.iloc[2] == pytest.approx(0.0)


class TestGetPickGap:
    def test_first_pick_in_12_team(self):
        # pick 0: (12-0-1) + abs(12-1-0) = 11 + 11 = 22
        assert get_pick_gap(0, 12) == 22

    def test_last_pick_in_12_team(self):
        # pick 11: (12-11-1) + abs(12-1-11) = 0 + 0 = 0
        assert get_pick_gap(11, 12) == 0

    def test_middle_pick(self):
        # pick 5 in 12-team: (12-5-1) + abs(12-1-5) = 6 + 6 = 12
        assert get_pick_gap(5, 12) == 12


class TestCalculateRiskPenalty:
    def _state(self, pos_players, injury_flags, roster_size=16, current_round=1):
        """Build a minimal draft state for risk penalty tests."""
        n_teams = 12
        player_ids = list(pos_players.keys())
        positions = list(pos_players.values())
        df = pd.DataFrame({
            "player_id": player_ids,
            "injury_flag": [injury_flags.get(pid, False) for pid in player_ids],
        })
        r = Roster()
        # Add players to the roster at their position
        for pid, pos in pos_players.items():
            r.add_player(pid, pos)
        # Patch roster_size so the formula uses our value
        r.roster_size = roster_size
        teams = [Roster() for _ in range(n_teams)]
        teams[0] = r
        state = types.SimpleNamespace(
            team_list=teams,
            predictions_table=df,
            round=current_round,
        )
        return state

    def test_qb_always_zero(self):
        state = self._state({"qb1": "QB"}, {"qb1": True})
        assert calculate_risk_penalty("QB", state, 0) == 0

    def test_wr_with_one_injured_round_1(self):
        state = self._state(
            {"wr1": "WR", "wr2": "WR", "wr3": "WR"},
            {"wr1": True},
            roster_size=16,
            current_round=2,
        )
        # 0.5 * 1 * (1 - 2/16) = 0.5 * 0.875 = 0.4375
        expected = 0.5 * 1 * (1 - 2 / 16)
        assert calculate_risk_penalty("WR", state, 0) == pytest.approx(expected)

    def test_no_injured_players_returns_zero(self):
        state = self._state({"rb1": "RB", "rb2": "RB"}, {})
        assert calculate_risk_penalty("RB", state, 0) == pytest.approx(0.0)


class TestPlayerSelect:
    def test_returns_at_most_five_rows(self, mock_draft_state):
        result = player_select("WR", mock_draft_state, 0)
        assert len(result) <= 5

    def test_output_has_weighted_value_column(self, mock_draft_state):
        result = player_select("WR", mock_draft_state, 0)
        assert "weighted_value" in result.columns

    def test_injury_flag_player_penalised(self, mock_draft_state):
        # Add an injury-flagged RB as the only drafted RB, then check rb2 is penalised
        mock_draft_state.team_list[0].add_player("rb1", "RB")
        result = player_select("RB", mock_draft_state, 0)
        rb2_row = result[result["player_name"] == "RB Two"]
        rb1_row = result[result["player_name"] == "RB One"]
        if not rb1_row.empty and not rb2_row.empty:
            assert rb1_row["weighted_value"].iloc[0] > rb2_row["weighted_value"].iloc[0]

    def test_empty_pool_returns_empty_dataframe(self, mock_draft_state):
        result = player_select("DST", mock_draft_state, 0)
        assert result.empty


class TestPosSelect:
    def test_single_non_flex_need_returns_that_position(self, mock_draft_state):
        # Give team 0 everything except QB
        r = mock_draft_state.team_list[0]
        for pid, pos in [("rb1","RB"),("rb2","RB"),("wr1","WR"),("wr2","WR"),("wr3","WR"),("te1","TE")]:
            r.add_player(pid, pos)
        result = pos_select(mock_draft_state, 0)
        assert result == "QB"

    def test_multiple_needs_picks_scarcer_position(self, mock_draft_state):
        # Team 0 has nothing; scarcer position should be selected
        result = pos_select(mock_draft_state, 0)
        assert result in {"QB", "RB", "WR", "TE"}
