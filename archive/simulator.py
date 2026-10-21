"""Draft simulation module."""

import pandas as pd
import numpy as np
from typing import Optional, Callable
import logging
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DraftPick:
    """Represents a single draft pick."""
    round_num: int
    pick_num: int
    overall_pick: int
    team_id: int
    player: str
    position: str
    projected_points: float


@dataclass
class DraftState:
    """Represents the current state of a draft."""
    available_players: pd.DataFrame
    picks: list[DraftPick] = field(default_factory=list)
    rosters: dict[int, dict[str, list[str]]] = field(default_factory=dict)
    current_round: int = 1
    current_pick: int = 1

    def get_roster(self, team_id: int) -> dict[str, list[str]]:
        """Get a team's current roster."""
        if team_id not in self.rosters:
            self.rosters[team_id] = {"QB": [], "RB": [], "WR": [], "TE": [], "K": [], "DST": []}
        return self.rosters[team_id]


class DraftSimulator:
    """
    Simulate fantasy football drafts.

    Supports snake drafts and can simulate opponent picks using ADP.
    """

    def __init__(
        self,
        team_count: int = 12,
        rounds: int = 15,
        snake: bool = True
    ):
        """
        Initialize draft simulator.

        Args:
            team_count: Number of teams in league
            rounds: Number of draft rounds
            snake: Whether to use snake draft order
        """
        self.team_count = team_count
        self.rounds = rounds
        self.snake = snake

    def create_draft_order(self) -> list[int]:
        """
        Create the full draft order.

        Returns:
            List of team IDs in pick order
        """
        order = []
        for round_num in range(1, self.rounds + 1):
            round_order = list(range(1, self.team_count + 1))

            # Reverse odd rounds for snake draft
            if self.snake and round_num % 2 == 0:
                round_order = round_order[::-1]

            order.extend(round_order)

        return order

    def get_pick_info(self, overall_pick: int) -> tuple[int, int, int]:
        """
        Get round, pick within round, and team for an overall pick number.

        Args:
            overall_pick: Overall pick number (1-indexed)

        Returns:
            Tuple of (round_num, pick_in_round, team_id)
        """
        round_num = (overall_pick - 1) // self.team_count + 1
        pick_in_round = (overall_pick - 1) % self.team_count + 1

        if self.snake and round_num % 2 == 0:
            team_id = self.team_count - pick_in_round + 1
        else:
            team_id = pick_in_round

        return round_num, pick_in_round, team_id

    def simulate_opponent_pick(
        self,
        state: DraftState,
        team_id: int,
        adp_col: str = "adp"
    ) -> str:
        """
        Simulate an opponent's pick based on ADP.

        Args:
            state: Current draft state
            team_id: Team making the pick
            adp_col: Column with ADP values

        Returns:
            Name of picked player
        """
        available = state.available_players

        if adp_col in available.columns:
            # Add some randomness to ADP-based picks
            available = available.copy()
            available["pick_prob"] = 1 / (available[adp_col] + np.random.normal(0, 5, len(available)))
            available["pick_prob"] = available["pick_prob"].clip(lower=0)

            # Normalize probabilities
            available["pick_prob"] = available["pick_prob"] / available["pick_prob"].sum()

            # Sample based on probability
            player = np.random.choice(
                available["player"],
                p=available["pick_prob"]
            )
        else:
            # If no ADP, pick best available by projected points
            player = available.nlargest(1, "projected_points")["player"].iloc[0]

        return player

    def make_pick(
        self,
        state: DraftState,
        player_name: str,
        team_id: int,
        overall_pick: int
    ) -> DraftState:
        """
        Record a draft pick and update state.

        Args:
            state: Current draft state
            player_name: Name of player being picked
            team_id: Team making the pick
            overall_pick: Overall pick number

        Returns:
            Updated draft state
        """
        # Find player in available players
        player_row = state.available_players[
            state.available_players["player"] == player_name
        ]

        if len(player_row) == 0:
            raise ValueError(f"Player {player_name} not available")

        player_data = player_row.iloc[0]
        round_num, pick_in_round, _ = self.get_pick_info(overall_pick)

        # Create pick record
        pick = DraftPick(
            round_num=round_num,
            pick_num=pick_in_round,
            overall_pick=overall_pick,
            team_id=team_id,
            player=player_name,
            position=player_data["position"],
            projected_points=player_data.get("projected_points", 0)
        )

        # Update state
        state.picks.append(pick)

        # Add to team roster
        roster = state.get_roster(team_id)
        position = player_data["position"]
        roster[position].append(player_name)

        # Remove from available players
        state.available_players = state.available_players[
            state.available_players["player"] != player_name
        ]

        return state

    def simulate_draft(
        self,
        projections: pd.DataFrame,
        user_team: int,
        pick_strategy: Callable[[DraftState, int], str],
        adp_col: str = "adp"
    ) -> DraftState:
        """
        Simulate a complete draft.

        Args:
            projections: DataFrame with player projections
            user_team: User's team ID (1-indexed)
            pick_strategy: Function to determine user's picks
            adp_col: Column with ADP for opponent simulation

        Returns:
            Final draft state
        """
        # Initialize state
        state = DraftState(available_players=projections.copy())
        draft_order = self.create_draft_order()

        total_picks = self.team_count * self.rounds

        for overall_pick in range(1, total_picks + 1):
            round_num, pick_in_round, team_id = self.get_pick_info(overall_pick)

            if team_id == user_team:
                # User's pick
                player = pick_strategy(state, overall_pick)
            else:
                # Simulate opponent pick
                player = self.simulate_opponent_pick(state, team_id, adp_col)

            state = self.make_pick(state, player, team_id, overall_pick)

            if overall_pick % self.team_count == 0:
                logger.debug(f"Completed round {round_num}")

        logger.info(f"Draft simulation complete. {len(state.picks)} picks made.")
        return state

    def run_monte_carlo(
        self,
        projections: pd.DataFrame,
        user_team: int,
        pick_strategy: Callable[[DraftState, int], str],
        n_simulations: int = 100,
        adp_col: str = "adp"
    ) -> pd.DataFrame:
        """
        Run Monte Carlo simulations to evaluate draft strategies.

        Args:
            projections: DataFrame with player projections
            user_team: User's team ID
            pick_strategy: Function to determine user's picks
            n_simulations: Number of simulations to run
            adp_col: Column with ADP values

        Returns:
            DataFrame with simulation results
        """
        results = []

        for sim in range(n_simulations):
            if sim % 10 == 0:
                logger.info(f"Running simulation {sim + 1}/{n_simulations}")

            state = self.simulate_draft(
                projections.copy(),
                user_team,
                pick_strategy,
                adp_col
            )

            # Calculate team score
            user_picks = [p for p in state.picks if p.team_id == user_team]
            total_points = sum(p.projected_points for p in user_picks)

            results.append({
                "simulation": sim + 1,
                "total_projected_points": total_points,
                "picks": [p.player for p in user_picks]
            })

        results_df = pd.DataFrame(results)
        logger.info(f"Monte Carlo complete. Mean points: {results_df['total_projected_points'].mean():.1f}")

        return results_df


if __name__ == "__main__":
    # Example usage
    sample_players = pd.DataFrame({
        "player": [f"Player_{i}" for i in range(1, 201)],
        "position": np.random.choice(["QB", "RB", "WR", "TE"], 200, p=[0.1, 0.3, 0.4, 0.2]),
        "projected_points": np.random.normal(150, 50, 200).clip(min=50),
        "adp": list(range(1, 201))
    })

    simulator = DraftSimulator(team_count=12, rounds=15)

    # Simple strategy: always pick highest projected points
    def best_available(state: DraftState, pick: int) -> str:
        return state.available_players.nlargest(1, "projected_points")["player"].iloc[0]

    # Run single simulation
    result = simulator.simulate_draft(
        sample_players,
        user_team=5,
        pick_strategy=best_available
    )

    print("User's picks:")
    for pick in result.picks:
        if pick.team_id == 5:
            print(f"  Round {pick.round_num}: {pick.player} ({pick.position})")
