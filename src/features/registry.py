"""Which engineered columns each position's model uses. The pipeline builds the union for every row;
split_positions drops the columns that belong to other positions."""

from src.features.team_context import RB_FEATURES, QB_MODEL_FEATURES
from src.features.advanced import ADVANCED_GROUPS

POSITION_FEATURES = {
    "QB": QB_MODEL_FEATURES,
    "RB": RB_FEATURES + ADVANCED_GROUPS["depth"] + ADVANCED_GROUPS["xfp"],
    "WR": ADVANCED_GROUPS["depth"] + ADVANCED_GROUPS["role"],
    "TE": ADVANCED_GROUPS["xfp"] + [c for c in ADVANCED_GROUPS["ngs"] if c.startswith("ngs_rece_")],
}
ADVANCED_MODEL_COLUMNS = sorted({c for features in POSITION_FEATURES.values() for c in features}
                                & {c for columns in ADVANCED_GROUPS.values() for c in columns})


def other_position_features(position):
    everything = {c for features in POSITION_FEATURES.values() for c in features}
    return sorted(everything - set(POSITION_FEATURES[position]))
