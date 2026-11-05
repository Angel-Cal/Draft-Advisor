from src.draft.roster import Roster
from src.data.pipeline import PROCESSED_DIR
import pandas as pd


class DraftState:
    def __init__(self, n_teams=12):
        self.predictions_table = pd.read_parquet(PROCESSED_DIR / "predictions_table.parquet")
        self.available_players = self.predictions_table.copy()
        self.team_list = []
        self.pick_number = 0
        self.round =1
        self.n_teams = n_teams
        for n in range(n_teams):
            team = Roster()   # using defaults for now
            self.team_list.append(team)        

    def get_current_pick(self):
        if (self.round % 2) == 0:
            return abs(self.n_teams - 1 - self.pick_number)
        else:
            return self.pick_number

    def draft_player(self, player_id):
        if(not (self.available_players["player_id"] == player_id).any()):
            return None

        pick = self.get_current_pick()
        pos = self.available_players[self.available_players["player_id"] == player_id]
        pos = pos["position"].iloc[0]
        self.team_list[pick].add_player(player_id, pos)

        self.pick_number += 1
        if(self.pick_number >= self.n_teams):
            self.pick_number =0
            self.round +=1
        self.available_players.drop(
            self.available_players[self.available_players["player_id"] == player_id].index,
            inplace=True
        )
        return True

