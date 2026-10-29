import numpy as np
import pandas as pd
import pytest
from src.draft.vor import compute_vor, compute_ceiling_floor, compute_value_gap, compute_tiers, normalize_names


def _players(n=16):
    """Return a DataFrame of n players with distinct projected_ppr values."""
    return pd.DataFrame({
        "player_id":    [f"p{i}" for i in range(n)],
        "projected_ppr": [float(100 + i * 10) for i in range(n)],
    })


class TestNormalizeNames:
    def test_lowercases_and_strips_punctuation(self):
        df = pd.DataFrame({"Player": ["Tom Brady", "A.J. Brown", "Ja'Marr Chase", "Calvin Johnson Jr.", "Tony Gonzalez III"]})
        result = normalize_names(df)
        assert result["merge_name"].tolist() == [
            "tom brady",
            "aj brown",
            "jamarr chase",
            "calvin johnson",
            "tony gonzalez",
        ]

    def test_strip_leaves_original_player_column_unchanged(self):
        df = pd.DataFrame({"Player": ["CeeDee Lamb"]})
        result = normalize_names(df)
        assert result["Player"].iloc[0] == "CeeDee Lamb"


class TestComputeVor:
    def test_baseline_player_has_zero_vor(self):
        df = _players(10)
        baseline_pos = 4
        result = compute_vor(df, baseline_pos)
        assert result["vor"].iloc[baseline_pos] == pytest.approx(0.0)

    def test_players_above_baseline_have_positive_vor(self):
        df = _players(10)
        result = compute_vor(df, 4)
        assert (result["vor"].iloc[:4] > 0).all()

    def test_players_below_baseline_have_negative_vor(self):
        df = _players(10)
        result = compute_vor(df, 4)
        assert (result["vor"].iloc[5:] < 0).all()

    def test_output_sorted_descending_by_projected_ppr(self):
        df = _players(10).sample(frac=1, random_state=42)  # shuffle
        result = compute_vor(df, 3)
        assert result["projected_ppr"].is_monotonic_decreasing


class TestComputeCeilingFloor:
    RMSE = 50.0

    def _healthy(self, proj=200.0):
        return pd.DataFrame({
            "projected_ppr": [proj],
            "games": [17],
            "games_delta": [0],
        })

    def _injured(self, proj=200.0, games=8, delta=-9):
        return pd.DataFrame({
            "projected_ppr": [proj],
            "games": [games],
            "games_delta": [delta],
        })

    def test_healthy_player_ceiling_equals_proj_plus_rmse(self):
        result = compute_ceiling_floor(self._healthy(200.0), self.RMSE)
        assert result["ceiling"].iloc[0] == pytest.approx(250.0)

    def test_healthy_player_floor_equals_proj_minus_rmse(self):
        result = compute_ceiling_floor(self._healthy(200.0), self.RMSE)
        assert result["floor"].iloc[0] == pytest.approx(150.0)

    def test_floor_clipped_at_zero(self):
        result = compute_ceiling_floor(self._healthy(30.0), self.RMSE)
        assert result["floor"].iloc[0] == pytest.approx(0.0)

    def test_healthy_availability_flag_false(self):
        result = compute_ceiling_floor(self._healthy(), self.RMSE)
        assert not result["availability_flag"].iloc[0]

    def test_injured_availability_flag_true(self):
        result = compute_ceiling_floor(self._injured(), self.RMSE)
        assert result["availability_flag"].iloc[0]

    def test_injured_ceiling_at_least_rmse_ceiling(self):
        proj = 100.0
        result = compute_ceiling_floor(self._injured(proj=proj, games=8, delta=-9), self.RMSE)
        rmse_ceiling = proj + self.RMSE
        assert result["ceiling"].iloc[0] >= rmse_ceiling


class TestComputeValueGap:
    def test_value_gap_equals_adp_minus_vor_rank(self):
        df = pd.DataFrame({
            "vor":     [100.0, 50.0, 0.0],
            "adp":      [1.0,   3.0,  5.0],
        })
        result = compute_value_gap(df)
        expected = result["adp"] - result["vor_rank"]
        pd.testing.assert_series_equal(result["value_gap"], expected, check_names=False)

    def test_sorted_descending_by_vor(self):
        df = pd.DataFrame({
            "vor":     [0.0, 100.0, 50.0],
            "adp":      [5.0,  1.0,   3.0],
        })
        result = compute_value_gap(df)
        assert result["vor"].is_monotonic_decreasing


class TestComputeTiers:
    def test_eight_tiers_assigned(self):
        df = pd.DataFrame({"vor": [float(i) for i in range(16)]})
        result = compute_tiers(df)
        assert set(result["tier"].dropna().astype(int).unique()) == set(range(1, 9))

    def test_highest_vor_gets_tier_one(self):
        df = pd.DataFrame({"vor": [float(i) for i in range(16)]})
        result = compute_tiers(df)
        best_tier = result.loc[result["vor"].idxmax(), "tier"]
        assert int(best_tier) == 1
