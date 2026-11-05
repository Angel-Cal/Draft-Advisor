import pandas as pd
import pytest
from src.data.advisor_table import compute_vor, normalize_names, rank_by_vor


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


class TestRankByVor:
    def test_sorted_descending_by_vor(self):
        df = pd.DataFrame({
            "vor":     [0.0, 100.0, 50.0],
            "adp":      [5.0,  1.0,   3.0],
        })
        result = rank_by_vor(df)
        assert result["vor"].is_monotonic_decreasing
        assert result.index.tolist() == [0, 1, 2]
