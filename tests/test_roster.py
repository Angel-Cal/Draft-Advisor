import pytest
from src.draft.roster import Roster


class TestRosterInit:
    def test_default_roster_size(self):
        r = Roster()
        assert r.roster_size == 3 + 2 + 1 + 1 + 1 + 8  # 16

    def test_all_lists_start_empty(self):
        r = Roster()
        assert r.qb_list == []
        assert r.rb_list == []
        assert r.wr_list == []
        assert r.te_list == []
        assert r.pick_list == []

    def test_flex_not_filled_at_init(self):
        r = Roster()
        assert not r.flex_filled


class TestAddPlayer:
    def test_qb_added_to_correct_list_and_pick_list(self):
        r = Roster()
        r.add_player("qb1", "QB")
        assert r.qb_list == ["qb1"]
        assert r.pick_list == ["qb1"]

    def test_rb_wr_te_added_to_correct_lists(self):
        r = Roster()
        r.add_player("rb1", "RB")
        r.add_player("wr1", "WR")
        r.add_player("te1", "TE")
        assert r.rb_list == ["rb1"]
        assert r.wr_list == ["wr1"]
        assert r.te_list == ["te1"]

    def test_flex_filled_when_all_starter_slots_met(self):
        r = Roster()
        r.add_player("rb1", "RB")
        r.add_player("rb2", "RB")
        r.add_player("wr1", "WR")
        r.add_player("wr2", "WR")
        r.add_player("wr3", "WR")
        assert not r.flex_filled  # TE still empty
        r.add_player("te1", "TE")
        assert r.flex_filled

    def test_flex_not_filled_until_all_three_met(self):
        r = Roster()
        r.add_player("rb1", "RB")
        r.add_player("rb2", "RB")
        assert not r.flex_filled  # WR and TE still short


class TestGetNeeds:
    def test_empty_roster_needs_all_starters_no_flex(self):
        r = Roster()
        needs, _ = r.get_needs()
        assert set(needs) == {"QB", "RB", "WR", "TE"}
        assert "FLEX" not in needs

    def test_flex_appears_once_one_slot_minimum_met(self):
        r = Roster()
        r.add_player("rb1", "RB")
        r.add_player("rb2", "RB")
        needs, _ = r.get_needs()
        assert "FLEX" in needs
        assert "RB" not in needs  # RB starter slot satisfied

    def test_all_starters_filled_returns_empty_needs(self):
        r = Roster()
        r.add_player("qb1", "QB")
        r.add_player("rb1", "RB")
        r.add_player("rb2", "RB")
        r.add_player("wr1", "WR")
        r.add_player("wr2", "WR")
        r.add_player("wr3", "WR")
        r.add_player("te1", "TE")
        needs, _ = r.get_needs()
        assert needs == []

    def test_bench_remaining_decrements_after_flex_filled(self):
        r = Roster()
        # Fill all starter + flex slots (8 picks): QB, 2RB, 3WR, TE, FLEX-WR
        for pid, pos in [("qb1","QB"),("rb1","RB"),("rb2","RB"),
                         ("wr1","WR"),("wr2","WR"),("wr3","WR"),
                         ("te1","TE"),("flex1","WR")]:
            r.add_player(pid, pos)
        # bench_used = 8 picks - (3+2+1+1+1) starter+flex slots = 0
        _, bench_after_starters = r.get_needs()
        assert bench_after_starters == 8

        r.add_player("bench1", "QB")  # first actual bench pick
        _, bench_remaining = r.get_needs()
        assert bench_remaining == 7


class TestGetPicks:
    def test_returns_all_picks_in_order(self):
        r = Roster()
        r.add_player("qb1", "QB")
        r.add_player("rb1", "RB")
        r.add_player("wr1", "WR")
        assert r.get_picks() == ["qb1", "rb1", "wr1"]
