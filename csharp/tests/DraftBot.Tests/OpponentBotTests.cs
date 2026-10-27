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
}
