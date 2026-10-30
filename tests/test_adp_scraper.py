import pandas as pd

from src.data.adp_scraper import parse_adp_csv, source_dates


def test_an_export_row_may_carry_a_team_and_bye_a_team_alone_or_neither(tmp_path):
    path = tmp_path / "export.csv"
    pd.DataFrame({"Rank": [1, 2, 3, 4, 5], "Player (Bye)": ["Adrian Peterson", "Odell Beckham Jr. MIN (6)", "Kirk Cousins LV", "Robert Griffin III", "Phillip Dorsett II LV"],
                  "POS": ["RB1", "WR2", "QB3", "QB4", "WR5"], "AVG": [1.0, 2.7, 3.0, 4.0, 5.0]}).to_csv(path, index=False)

    out = parse_adp_csv(path, 2016, "preseason").set_index("rank")

    assert out["Player"].to_dict() == {1: "Adrian Peterson", 2: "Odell Beckham Jr.", 3: "Kirk Cousins", 4: "Robert Griffin III", 5: "Phillip Dorsett II"}
    assert out["team"].isna().to_dict() == {1: True, 2: False, 3: False, 4: True, 5: False}      # a name suffix is not a team
    assert out["position"].to_dict() == {1: "RB", 2: "WR", 3: "QB", 4: "QB", 5: "WR"}


def test_the_dates_a_page_prints_for_its_sources_are_read_off_the_text():
    html = "<td>ADP ESPN 9/04</td><td>MyFantasyLeague.com 9/04</td><td>Fantrax  9/06</td>"

    assert source_dates(html) == ["9/04", "9/06"]
