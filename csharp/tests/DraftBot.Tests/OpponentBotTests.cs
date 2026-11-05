using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class OpponentBotTests
{
    [Fact]
    public void An_opponents_preferences_do_not_depend_on_the_order_of_the_pool()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var settings = new SimSettings(new LeagueSettings());
        // different projections reorder the pool (it is sorted by VOR); the opponents must not change with it
        var reordered = pool.AsEnumerable().Reverse().ToList();

        foreach (var team in new[] { 0, 3, 11 })
        {
            var a = OpponentBot.Create(pool, settings, seed: 7, team);
            var b = OpponentBot.Create(reordered, settings, seed: 7, team);
            var remaining = pool.ToList();
            while (remaining.Count > 0)
            {
                var pick = a.Pick(remaining);
                Assert.Equal(pick.Id, b.Pick(remaining).Id);
                remaining.Remove(pick);
            }
        }
    }

    [Fact]
    public void The_default_style_changes_nothing_and_a_position_shift_moves_that_position_up()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var plain = new SimSettings(new LeagueSettings());
        var neutral = plain with { Style = new OpponentStyle() };
        var rbHungry = plain with { Style = new OpponentStyle(RbEarlier: 1000) };

        var remaining = pool.ToList();
        Assert.Equal(OpponentBot.Create(pool, plain, 7, 2).Pick(remaining).Id, OpponentBot.Create(pool, neutral, 7, 2).Pick(remaining).Id);
        Assert.Equal(Position.RB, OpponentBot.Create(pool, rbHungry, 7, 2).Pick(remaining).Position);
    }

    [Fact]
    public void A_run_and_an_open_starter_slot_pull_a_position_earlier_only_when_the_state_is_given()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var settings = new SimSettings(new LeagueSettings(), Style: new OpponentStyle(RunPull: 1000, RunWindow: 3));
        var state = new DraftState(pool, new LeagueSettings());
        var bot = OpponentBot.Create(pool, settings, 7, 5);
        var firstTe = pool.First(p => p.Position == Position.TE);
        state.Draft(firstTe.Id);

        var legal = state.Available;
        Assert.Equal(Position.TE, bot.Pick(legal, state).Position);              // one pick at TE just now: the run pulls the next TE up
        Assert.NotEqual(Position.TE, OpponentBot.Create(pool, plainStyleFree(), 7, 5).Pick(legal, state).Position);

        static SimSettings plainStyleFree() => new(new LeagueSettings());
    }
}
