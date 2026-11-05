"""Value-Based Drafting (VBD) implementation."""

import pandas as pd
import numpy as np
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ValueBasedDrafter:
    """
    Implement Value-Based Drafting strategy.

    VBD calculates player value relative to a "replacement level" player
    at each position, allowing comparison across positions.
    """

    # Default baseline ranks (replacement level players)
    # These represent the rank of a "replacement level" player at each position
    DEFAULT_BASELINES = {
        "QB": 12,   # QB12 is replacement level
        "RB": 24,   # RB24 is replacement level
        "WR": 30,   # WR30 is replacement level
        "TE": 12,   # TE12 is replacement level
        "K": 12,    # K12 is replacement level
        "DST": 12,  # DST12 is replacement level
    }

    def __init__(
        self,
        baselines: Optional[dict[str, int]] = None,
        team_count: int = 12
    ):
        """
        Initialize VBD calculator.

        Args:
            baselines: Position -> replacement rank mapping
            team_count: Number of teams in league
        """
        self.baselines = baselines or self.DEFAULT_BASELINES.copy()
        self.team_count = team_count
        self.replacement_values: dict[str, float] = {}

    def calculate_replacement_values(
        self,
        projections: pd.DataFrame,
        points_col: str = "projected_points",
        position_col: str = "position"
    ) -> dict[str, float]:
        """
        Calculate replacement level value for each position.

        Args:
            projections: DataFrame with player projections
            points_col: Column with projected points
            position_col: Position column

        Returns:
            Dictionary of position -> replacement value
        """
        replacement_values = {}

        for position, baseline_rank in self.baselines.items():
            position_players = projections[projections[position_col] == position]

            if len(position_players) >= baseline_rank:
                # Get the value of the replacement-level player
                sorted_players = position_players.sort_values(points_col, ascending=False)
                replacement_value = sorted_players.iloc[baseline_rank - 1][points_col]
            else:
                # Not enough players, use minimum
                replacement_value = position_players[points_col].min() if len(position_players) > 0 else 0

            replacement_values[position] = replacement_value
            logger.debug(f"{position} replacement value: {replacement_value:.1f}")

        self.replacement_values = replacement_values
        return replacement_values

    def calculate_vbd(
        self,
        projections: pd.DataFrame,
        points_col: str = "projected_points",
        position_col: str = "position"
    ) -> pd.DataFrame:
        """
        Calculate Value Over Replacement (VOR) for all players.

        Args:
            projections: DataFrame with player projections
            points_col: Column with projected points
            position_col: Position column

        Returns:
            DataFrame with VBD values added
        """
        df = projections.copy()

        # Calculate replacement values if not already done
        if not self.replacement_values:
            self.calculate_replacement_values(df, points_col, position_col)

        # Calculate VOR for each player
        df["replacement_value"] = df[position_col].map(self.replacement_values)
        df["vor"] = df[points_col] - df["replacement_value"]

        # Rank by VOR
        df["vbd_rank"] = df["vor"].rank(ascending=False, method="min").astype(int)

        # Sort by VOR
        df = df.sort_values("vor", ascending=False).reset_index(drop=True)

        return df

    def get_positional_scarcity(
        self,
        projections: pd.DataFrame,
        position_col: str = "position"
    ) -> pd.DataFrame:
        """
        Calculate positional scarcity metrics.

        Args:
            projections: DataFrame with VBD calculated
            position_col: Position column

        Returns:
            DataFrame with scarcity metrics by position
        """
        if "vor" not in projections.columns:
            raise ValueError("VBD must be calculated first")

        scarcity = []

        for position in self.baselines.keys():
            pos_players = projections[projections[position_col] == position]

            if len(pos_players) == 0:
                continue

            # Calculate metrics
            top_5_avg = pos_players.nlargest(5, "vor")["vor"].mean()
            top_12_avg = pos_players.nlargest(12, "vor")["vor"].mean()
            std_dev = pos_players["vor"].std()
            dropoff = top_5_avg - top_12_avg

            scarcity.append({
                "position": position,
                "top_5_vor_avg": top_5_avg,
                "top_12_vor_avg": top_12_avg,
                "vor_std": std_dev,
                "dropoff": dropoff,
                "replacement_value": self.replacement_values.get(position, 0)
            })

        return pd.DataFrame(scarcity).sort_values("dropoff", ascending=False)

    def suggest_pick(
        self,
        available_players: pd.DataFrame,
        roster: dict[str, list[str]],
        roster_requirements: dict[str, int]
    ) -> pd.DataFrame:
        """
        Suggest best available picks based on VBD and roster needs.

        Args:
            available_players: DataFrame of available players with VBD
            roster: Current roster {position: [player_names]}
            roster_requirements: Required slots per position

        Returns:
            Top suggestions with reasoning
        """
        if "vor" not in available_players.columns:
            raise ValueError("VBD must be calculated first")

        df = available_players.copy()

        # Calculate roster needs
        needs = {}
        for pos, required in roster_requirements.items():
            current = len(roster.get(pos, []))
            needs[pos] = max(0, required - current)

        # Add need-based boost
        df["need_multiplier"] = df["position"].map(
            lambda p: 1.2 if needs.get(p, 0) > 0 else 1.0
        )
        df["adjusted_vor"] = df["vor"] * df["need_multiplier"]

        # Get top suggestions
        suggestions = df.nlargest(5, "adjusted_vor")[
            ["player", "position", "projected_points", "vor", "vbd_rank", "need_multiplier"]
        ].copy()

        suggestions["reason"] = suggestions.apply(
            lambda x: f"Best VOR available" if x["need_multiplier"] == 1.0
            else f"Fills {x['position']} need",
            axis=1
        )

        return suggestions


if __name__ == "__main__":
    # Example usage
    sample_projections = pd.DataFrame({
        "player": [
            "CMC", "Tyreek", "Kelce", "Mahomes", "Henry",
            "Jefferson", "Andrews", "Allen", "Barkley", "Chase"
        ],
        "position": ["RB", "WR", "TE", "QB", "RB", "WR", "TE", "QB", "RB", "WR"],
        "projected_points": [350, 280, 240, 380, 300, 290, 200, 400, 280, 270]
    })

    vbd = ValueBasedDrafter()
    rankings = vbd.calculate_vbd(sample_projections)

    print("VBD Rankings:")
    print(rankings[["player", "position", "projected_points", "vor", "vbd_rank"]])

    print("\nPositional Scarcity:")
    print(vbd.get_positional_scarcity(rankings))
