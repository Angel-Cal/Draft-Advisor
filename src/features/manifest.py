"""Declares when each training column's value is known, so a new column cannot slip in unclassified.

prior_season:      a statistic from the season BEFORE the season being predicted (lagged), or a change between
                   the two prior seasons.
preseason_known:   known before the season starts (biography, draft, prior-season team totals, start-of-season roster).
Any column not listed here fails tests/test_data_integrity.py; that is the point.
"""

from src.features.build_features import LAG_COLS, DELTA_SHIFT_COLS
from src.features.team_context import RB_FEATURES, QB_MODEL_FEATURES

KEYS = {"player_id", "player_name", "season"}
TARGET = {"target_ppr"}
PRIOR_SEASON = set(LAG_COLS) | {f"{c}_delta" for c in DELTA_SHIFT_COLS}
PRESEASON_KNOWN = {"position", "height", "weight", "years_exp", "rookie_year", "draft_number", "age",
                   "implied_total"} | set(RB_FEATURES) | set(QB_MODEL_FEATURES)
PREDICTION_ONLY = {"injury_flag"}


def basis(column):
    for name, columns in [("key", KEYS), ("target", TARGET), ("prior_season", PRIOR_SEASON),
                          ("preseason_known", PRESEASON_KNOWN), ("prediction_only", PREDICTION_ONLY)]:
        if column in columns:
            return name
    return None


def undeclared(columns):
    return [c for c in columns if basis(c) is None]
