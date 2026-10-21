import numpy as np
import pandas as pd
import pytest
from src.features import advanced as adv


def test_line_yard_credit_follows_football_outsiders_weights():
    credit = adv._line_yard_credit(np.array([-3, 0, 4, 8, 15, 70]))
    assert credit.tolist() == pytest.approx([-3.6, 0.0, 4.0, 6.0, 7.0, 7.0])    # losses x1.2, 5-10 yds half, cap at 10


def plays():
    rows = []
    for season, team, gains, sacks in [(2020, "KC", [8, 8, 8, 8], [0, 0, 0, 0]), (2020, "DEN", [0, 0, 0, 0], [1, 1, 0, 0])]:
        for gain in gains:
            rows.append(dict(season=season, season_type="REG", posteam=team, down=1, ydstogo=10, play_type="run",
                             qb_scramble=0, qb_kneel=0, yards_gained=gain, qb_dropback=0, sack=0))
        for sack in sacks:
            rows.append(dict(season=season, season_type="REG", posteam=team, down=1, ydstogo=10, play_type="pass",
                             qb_scramble=0, qb_kneel=0, yards_gained=0, qb_dropback=1, sack=sack))
    return pd.DataFrame(rows)


def test_quality_is_relative_to_the_league_and_keyed_to_next_season():
    roster = pd.DataFrame({"gsis_id": ["a", "b"], "season": 2021, "week": 1, "position": "RB", "team": ["KC", "DEN"]})
    ol = pd.DataFrame({"player_id": ["a", "b"], "season": 2021, "ol_snap_continuity": [1.0, 0.5]})
    out = adv.build_ol_quality_features(plays(), roster, ol).set_index("player_id")
    assert out.loc["a", "ol_aly_prev"] > 0 > out.loc["b", "ol_aly_prev"]            # KC ran well, DEN did not
    assert out.loc["a", "ol_asr_prev"] < 0 < out.loc["b", "ol_asr_prev"]            # DEN gave up the sacks
    assert out.loc["b", "ol_aly_x_cont"] == pytest.approx(out.loc["b", "ol_aly_prev"] * 0.5)
    assert set(out["season"]) == {2021}
