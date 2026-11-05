def recommend(draft_state, user_team_idx):
    pos = pos_select(draft_state, user_team_idx)
    return pos, player_select(pos, draft_state, user_team_idx)


def pos_select(draft_state, user_team_idx):
    user_team = draft_state.team_list[user_team_idx]
    needs, bench_remaining = user_team.get_needs()

    if len(needs) == 1:
        if needs[0] == "FLEX":
            flex_pos = ["WR", "RB", "TE"]
            scarcity = {pos: get_scarcity(draft_state, pos) for pos in flex_pos}
            return max(scarcity, key=scarcity.get)
        else:
            return needs[0]

    elif len(needs) > 1:
        if "FLEX" in needs:
            needs = list(set(needs) - {"FLEX"} | {"WR", "RB", "TE"})
        scarcity = {pos: get_scarcity(draft_state, pos) for pos in needs}
        return max(scarcity, key=scarcity.get)

    else:
        # No starter needs — bench strategy
        all_pos = ["QB", "RB", "WR", "TE"]
        scarcity = {pos: get_scarcity(draft_state, pos) for pos in all_pos}
        # Risk stabilization: boost positions with 2+ injury-flagged starters
        roster = draft_state.team_list[user_team_idx]
        pos_lists = {
            "QB": roster.qb_list, "RB": roster.rb_list,
            "WR": roster.wr_list, "TE": roster.te_list,
        }
        for pos, drafted in pos_lists.items():
            flagged = sum(
                1 for pid in drafted
                if draft_state.predictions_table.loc[
                    draft_state.predictions_table["player_id"] == pid, "injury_flag"
                ].values[0]
            )
            if flagged >= 2:
                scarcity[pos] *= 1.2
        return max(scarcity, key=scarcity.get)


def get_scarcity(draft_state, pos):
    remaining_demand = 0
    for team in draft_state.team_list:
        pos_map = {
            "WR": (team.wr_ct, team.wr_list),
            "RB": (team.rb_ct, team.rb_list),
            "QB": (team.qb_ct, team.qb_list),
            "TE": (team.te_ct, team.te_list),
        }
        if pos in pos_map:
            ct, lst = pos_map[pos]
            remaining_demand += max(0, ct - len(lst))

    pos_pool = draft_state.available_players[
        draft_state.available_players["position"] == pos
    ]
    if pos_pool.empty:
        return 0
    highest_tier = pos_pool["tier"].min()
    supply = len(pos_pool[pos_pool["tier"] == highest_tier])
    if supply == 0:
        return 0
    return remaining_demand / supply


def normalize_col(col, df):
    col_min = df[col].min()
    col_max = df[col].max()
    if col_max == col_min:
        return df[col] * 0  # all same value → all 0
    if col == "vor_rank":
        return 1 - (df[col] - col_min) / (col_max - col_min)
    return (df[col] - col_min) / (col_max - col_min)


def calculate_risk_penalty(pos, draft_state, user_team_idx):
    if pos == "QB":
        return 0
    roster = draft_state.team_list[user_team_idx]
    pos_map = {"WR": roster.wr_list, "RB": roster.rb_list, "TE": roster.te_list}
    drafted_at_pos = pos_map.get(pos, [])
    flagged_count = sum(
        1 for pid in drafted_at_pos
        if draft_state.predictions_table.loc[
            draft_state.predictions_table["player_id"] == pid, "injury_flag"
        ].values[0]
    )
    total_rounds = roster.roster_size
    return 0.5 * flagged_count * (1 - draft_state.round / total_rounds)


def player_select(pos, draft_state, user_team_idx):
    pool = draft_state.available_players[
        draft_state.available_players["position"] == pos
    ].copy()
    if pool.empty:
        return pool

    pool["norm_vor_rank"] = normalize_col("vor_rank", pool)
    pool["norm_value_gap"] = normalize_col("value_gap", pool)
    risk_penalty = calculate_risk_penalty(pos, draft_state, user_team_idx)
    pool["weighted_value"] = (
        0.5 * pool["norm_vor_rank"]
        + 0.5 * pool["norm_value_gap"]
        - risk_penalty * pool["injury_flag"].astype(float)
    )
    return pool.nlargest(5, "weighted_value")[
        ["player_name", "position", "projected_ppr", "vor", "tier",
         "value_gap", "injury_flag", "weighted_value"]
    ]


def get_pick_gap(pick_number, n_teams):
    return (n_teams - pick_number - 1) + abs(n_teams - 1 - pick_number)
