using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class DraftStateTests
{
    static readonly LeagueSettings Tiny = new(Teams: 4, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 0);   // 4 rounds

    static List<ValuedPlayer> Pool(int count) =>
        Enumerable.Range(0, count).Select(i => Valued($"p{i}", Positions.All[i % 4], vor: 100 - i)).ToList();

    [Fact]
    public void Snake_order_reverses_every_round()
    {
        var state = new DraftState(Pool(16), Tiny);
        var order = new List<int>();
        for (var i = 0; i < 12; i++)
        {
            order.Add(state.CurrentTeam);
            Assert.True(state.Draft($"p{i}"));
        }

        Assert.Equal([0, 1, 2, 3, 3, 2, 1, 0, 0, 1, 2, 3], order);
        Assert.Equal(4, state.Round);
        Assert.Equal(12, state.OverallPick);
    }

    [Fact]
    public void Drafting_assigns_the_player_to_the_team_on_the_clock_and_removes_them_from_the_pool()
    {
        var state = new DraftState(Pool(16), Tiny);
        state.Draft("p0");
        state.Draft("p1");
        state.Draft("p2");
        state.Draft("p3");
        state.Draft("p7");      // round 2 starts with team 3

        Assert.Equal(["p7"], state.Teams[3].Picks.Skip(1).Select(p => p.Id));
        Assert.Equal(["p0"], state.Teams[0].Picks.Select(p => p.Id));
        Assert.DoesNotContain(state.Available, p => p.Id == "p7");
        Assert.Equal(11, state.Available.Count);
        var fifth = state.History[4];
        Assert.Equal((2, 0, 3), (fifth.Round, fifth.PickInRound, fifth.Team));
    }

    [Fact]
    public void An_unknown_or_taken_player_is_rejected_without_advancing_the_draft()
    {
        var state = new DraftState(Pool(16), Tiny);
        Assert.True(state.Draft("p0"));

        Assert.False(state.Draft("p0"));
        Assert.False(state.Draft("nobody"));
        Assert.Equal(1, state.OverallPick);
    }

    [Fact]
    public void The_draft_completes_after_every_roster_spot_is_picked()
    {
        var state = new DraftState(Pool(20), Tiny);
        for (var i = 0; i < 16; i++) state.Draft($"p{i}");

        Assert.True(state.IsComplete);
        Assert.All(state.Teams, team => Assert.Equal(4, team.Picks.Count));
        Assert.Throws<InvalidOperationException>(() => state.Draft("p16"));
    }
}

public class RosterTests
{
    static readonly LeagueSettings Default = new();

    static Roster With(params (string Id, Position Position)[] players)
    {
        var roster = new Roster(Default);
        foreach (var (id, position) in players) roster.Add(Valued(id, position));
        return roster;
    }

    [Fact]
    public void A_fresh_roster_needs_every_position_but_not_flex()
    {
        var (needs, bench) = new Roster(Default).GetNeeds();

        Assert.Equal([Slot.QB, Slot.RB, Slot.WR, Slot.TE], needs);
        Assert.Equal(8, bench);
    }

    [Fact]
    public void Flex_becomes_a_need_once_any_flex_position_is_full()
    {
        var roster = With(("rb1", Position.RB), ("rb2", Position.RB));

        var (needs, _) = roster.GetNeeds();

        Assert.Equal([Slot.QB, Slot.WR, Slot.TE, Slot.Flex], needs);
    }

    [Fact]
    public void Flex_counts_as_filled_when_every_rb_wr_te_starter_slot_is_filled()
    {
        // ported behavior: the FLEX need disappears when the core slots fill, before anyone is drafted "into" FLEX
        var roster = With(("rb1", Position.RB), ("rb2", Position.RB), ("wr1", Position.WR), ("wr2", Position.WR),
            ("wr3", Position.WR), ("te1", Position.TE));

        var (needs, _) = roster.GetNeeds();

        Assert.True(roster.FlexFilled);
        Assert.Equal([Slot.QB], needs);
    }

    [Fact]
    public void Bench_remaining_is_picks_beyond_the_eight_starters_including_the_ported_flex_quirk()
    {
        var roster = With(("qb1", Position.QB), ("rb1", Position.RB), ("rb2", Position.RB), ("wr1", Position.WR),
            ("wr2", Position.WR), ("wr3", Position.WR), ("te1", Position.TE));
        // ported quirk: 7 players, FLEX is already "filled", so bench use is 7 - 8 = -1 and 9 spots look free
        Assert.Equal(9, roster.GetNeeds().BenchRemaining);

        roster.Add(Valued("rb3", Position.RB));
        roster.Add(Valued("wr4", Position.WR));
        Assert.Equal(7, roster.GetNeeds().BenchRemaining);          // 9 players: 8 starters + 1 bench
    }
}
