using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class QbTimingTests
{
    static readonly LeagueSettings League = new();
    static readonly SimSettings Settings = new(League);

    static List<ValuedPlayer> Pool() => Valuator.Value(BacktestFile().Players, BacktestFile().PositionRmse, League);

    [Fact]
    public void No_qb_is_taken_before_the_round()
    {
        // the realistic pool ranks QBs at the very top by ADP, so plain ADP takes one in round 1 from slot 1
        Assert.Equal(Position.QB, DraftSimulator.Run(Pool(), Settings, 0, new AdpStrategy(), seed: 2).MyPicks[0].Position);
        foreach (var slot in new[] { 0, 5, 11 })
        {
            var picks = DraftSimulator.Run(Pool(), Settings, slot, new QbTimingStrategy("late", new AdpStrategy(), 8), seed: 2).MyPicks;
            var firstQb = picks.Select((p, i) => (p, round: i + 1)).First(x => x.p.Position == Position.QB).round;
            Assert.True(firstQb >= 8, $"slot {slot + 1}: first QB in round {firstQb}");
        }
    }

    [Fact]
    public void A_top_ranked_qb_is_allowed_early_and_others_are_not()
    {
        var state = new DraftState(Pool(), League);
        var qbs = state.Available.Where(p => p.Position == Position.QB).OrderBy(p => p.Player.Adp).ToList();
        Assert.Equal(1, QbTimingStrategy.QbAdpRank(state, qbs[0]));
        Assert.Equal(3, QbTimingStrategy.QbAdpRank(state, qbs[2]));

        var legal = DraftRules.LegalPicks(state, 0, Settings);
        Assert.Equal(qbs[0].Id, new QbTimingStrategy("barbell", new AdpStrategy(), 8, allowTopRanks: 2).Pick(state, 0, legal).Id);
        var withoutTop = legal.Where(p => p.Id != qbs[0].Id && p.Id != qbs[1].Id).ToList();
        Assert.NotEqual(Position.QB, new QbTimingStrategy("barbell", new AdpStrategy(), 8, allowTopRanks: 2).Pick(state, 0, withoutTop).Position);
    }

    [Fact]
    public void The_rule_is_dropped_when_only_qbs_are_legal()
    {
        var onlyQbs = Pool().Where(p => p.Position == Position.QB).Take(3).ToList();
        var state = new DraftState(onlyQbs, League);
        Assert.Equal(Position.QB, new QbTimingStrategy("late", new AdpStrategy(), 8).Pick(state, 0, onlyQbs).Position);
    }
}
