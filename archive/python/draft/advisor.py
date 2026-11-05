import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.draft.draft_state import DraftState
from src.draft.recommender import recommend


def find_player(name, available):
    return available[available["player_name"].str.lower().str.contains(name.lower(), na=False)]


def run():
    draft_pos = int(input("Enter your draft position (1-12): ")) - 1
    state = DraftState()
    roster = state.team_list[0]
    total_rounds = roster.roster_size

    while state.round <= total_rounds:
        current_team = state.get_current_pick()
        print(f"\nRound {state.round}, Pick {state.pick_number + 1} — Team {current_team + 1} is on the clock")

        if current_team == draft_pos:
            pos, recs = recommend(state, draft_pos)
            print(f"\n  Recommended position: {pos}")
            print(recs.to_string(index=False))

        name = input("\nWho was drafted? (type name): ").strip()
        if not name:
            continue

        matches = find_player(name, state.available_players)

        if matches.empty:
            print("  Player not found or already drafted. Try again.")
            continue

        if len(matches) > 1:
            print("  Multiple matches:")
            print(matches[["player_name", "position", "projected_ppr"]].to_string(index=False))
            name = input("  Enter exact name: ").strip()
            matches = find_player(name, state.available_players)
            if matches.empty:
                print("  No match found. Try again.")
                continue

        player_id = matches.iloc[0]["player_id"]
        player_name = matches.iloc[0]["player_name"]
        result = state.draft_player(player_id)
        if result is None:
            print("  Player already drafted.")
        else:
            print(f"  Drafted: {player_name}")

    print("\nDraft complete!")


if __name__ == "__main__":
    run()
