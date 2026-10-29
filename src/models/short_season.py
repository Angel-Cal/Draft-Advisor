"""Routed projection for players coming off a short season (LOG 2026-10-29, "Short-season under-projection").

A season of few games shrinks every season-total input (attempts, carries, targets, EPA, fantasy points and the changes in them), so the model
reads an injury as lower talent; draftable elite players off a short season scored 40 to 120 points above their projection. Players with at most
SHORT_SEASON_GAMES prior games are therefore projected from a rate view of the same features (totals replaced by per-game values, games and
games_delta removed, and the QB attempt share); everyone else keeps the current model, so their projections do not change.
"""
import numpy as np

SHORT_SEASON_GAMES = 9
EPA_TOTALS = ["passing_epa", "rushing_epa", "receiving_epa"]
# every input that shrinks when a player misses games: season totals and the changes in them
VOLUME_TOTALS = (["fantasy_points", "fantasy_points_ppr", "attempts", "carries", "targets", "xfp_ppr_prev", "fp_over_exp_prev",
                  "attempts_delta", "carries_delta", "targets_delta"] + EPA_TOTALS)
AVAILABILITY = ["games", "games_delta"]
# role inputs that also shrink with games missed: the backup took the rest of the attempts, so the share reads a hurt starter as a part-timer
ROLE_SHARES = ["qb_att_share_prev"]


def to_rates(x):
    """The feature frame with season totals replaced by per-game rates (last season's PPR per game, EPA per game) and availability removed."""
    x = x.copy()
    games = x["games"].replace(0, np.nan)
    for column in EPA_TOTALS:
        if column in x:
            x[f"{column}_pg"] = x[column] / games
    x["ppg_prev"] = x["fantasy_points_ppr"] / games
    return x.drop(columns=[c for c in VOLUME_TOTALS + AVAILABILITY + ROLE_SHARES if c in x])


def rate_refit(model, x_train, y_train, x_val, y_val, x_pred, params):
    """`Model.refit_predict` on the rate view of all three frames."""
    return model.refit_predict(to_rates(x_train), y_train, to_rates(x_val), y_val, to_rates(x_pred), params)


def route(base, rates, games):
    """The rate projection where the prior season had SHORT_SEASON_GAMES or fewer games, the base projection elsewhere."""
    return np.where(np.asarray(games) <= SHORT_SEASON_GAMES, rates, base)


def routed_refit(model, x_train, y_train, x_val, y_val, x_pred, params):
    """Projections for `x_pred`: the validated refit recipe, routed for short-season players (the rate model is only fit when there are any)."""
    base = model.refit_predict(x_train, y_train, x_val, y_val, x_pred, params)
    if not (x_pred["games"] <= SHORT_SEASON_GAMES).any():
        return base
    return route(base, rate_refit(model, x_train, y_train, x_val, y_val, x_pred, params), x_pred["games"])
