using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class LookaheadTests
{
    // 2 teams, 1 starter each at QB/RB/WR/TE and one FLEX; replacement points: QB 200, RB 100, WR 100, TE 50
    static readonly LeagueSettings Small = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 3);
    static readonly Dictionary<Position, double> Replacement = new()
        { [Position.QB] = 200, [Position.RB] = 100, [Position.WR] = 100, [Position.TE] = 50 };

    static ValuedPlayer V(string id, Position position, double projected, double adp) =>
        new(Player(id, position, projected, adp: adp), projected - Replacement[position], 0, 0, false, 1, 0, 1);

    static readonly ReachSettings NoReach = new(0, 100);

    [Fact]
    public void Expected_best_is_the_first_survivor_in_value_order()
    {
        Assert.Equal(0, LookaheadSettings.ExpectedBest([]));
        Assert.Equal(50, LookaheadSettings.ExpectedBest([(50, 1.0), (40, 1.0)]), 9);                    // the best is certain to last
        Assert.Equal(0.5 * 50 + 0.5 * 40, LookaheadSettings.ExpectedBest([(50, 0.5), (40, 1.0)]), 9);   // else the next one
        Assert.Equal(0.5 * 50, LookaheadSettings.ExpectedBest([(50, 0.5), (40, 0.0)]), 9);              // nobody else lasts: nothing above replacement
        Assert.Equal(0, LookaheadSettings.ExpectedBest([(-5, 1.0)]), 9);                                // a below-replacement survivor adds nothing
    }

    [Fact]
    public void A_player_who_will_still_be_there_is_passed_over_for_one_who_will_not()
    {
        // my next pick is 4 of 8: the RB (adp 60) will certainly last, the TE (adp 1) very likely will not
        var state = new DraftState([V("te", Position.TE, 95, 1), V("rb", Position.RB, 150, 60)], Small);

        var oneStep = ValueRecommender.Rank(state, NoReach);
        var ranked = ValueRecommender.Rank(state, NoReach, lookahead: new LookaheadSettings(1)).ToDictionary(c => c.Player.Id);

        Assert.Equal("rb", oneStep[0].Player.Id);                                                  // 50 vs 45 on value alone
        Assert.True(ranked["te"].Score > ranked["rb"].Score);                                      // 45 + 50 vs 50 + about 5.5
        Assert.InRange(ranked["te"].NextTurn!.Value, 49.9, 50.1);
        Assert.InRange(ranked["rb"].NextTurn!.Value, 5, 6);
    }

    [Fact]
    public void The_next_turn_is_valued_with_the_player_on_the_roster()
    {
        // RB, RB and the FLEX are full with 300s; once a WR fills the WR slot a second WR adds nothing
        var state = new DraftState([V("wrA", Position.WR, 150, 1), V("wrB", Position.WR, 148, 60)], Small);
        state.Teams[0].Add(V("rb1", Position.RB, 300, 99));
        state.Teams[0].Add(V("rb2", Position.RB, 300, 99));

        var ranked = ValueRecommender.Rank(state, NoReach, new NeedSettings(0), lookahead: new LookaheadSettings(1)).ToDictionary(c => c.Player.Id);

        Assert.InRange(ranked["wrA"].NextTurn!.Value, 0, 0.5);        // wrB would add nothing after wrA
        Assert.InRange(ranked["wrB"].NextTurn!.Value, 0.2, 0.3);      // wrA (12% to last) would add 2 points over wrB
        Assert.True(ranked["wrA"].Score > ranked["wrB"].Score);       // 50 vs about 48.2
    }

    [Fact]
    public void A_beta_of_zero_or_no_later_pick_leaves_the_one_step_ranking_alone()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var state = new DraftState(pool, new LeagueSettings());
        var reach = ValueRecommender.DefaultReach;
        var plain = ValueRecommender.Rank(state, reach, NeedSettings.Default);

        var zero = ValueRecommender.Rank(state, reach, NeedSettings.Default, lookahead: new LookaheadSettings(0));
        Assert.Equal(plain.Select(c => (c.Player.Id, c.Score)), zero.Select(c => (c.Player.Id, c.Score)));

        while (state.Round < state.League.RosterSize) state.Draft(state.Available[0].Id);
        var last = ValueRecommender.Rank(state, reach, NeedSettings.Default, state.CurrentTeam, lookahead: new LookaheadSettings(1));
        Assert.All(last, c => Assert.Null(c.NextTurn));
    }

    [Fact]
    public void Only_the_best_candidates_get_the_lookahead_and_it_cannot_be_combined_with_the_waiting_bonus()
    {
        var state = new DraftState(Valuator.Value(RealisticPool(), Rmse, new LeagueSettings()), new LeagueSettings());

        var ranked = ValueRecommender.Rank(state, ValueRecommender.DefaultReach, NeedSettings.Default, lookahead: new LookaheadSettings(1, Candidates: 5));

        Assert.Equal(5, ranked.Count(c => c.NextTurn is not null));
        Assert.Throws<ArgumentException>(() => ValueRecommender.Rank(state, ValueRecommender.DefaultReach, NeedSettings.Default,
            wait: ValueRecommender.DefaultWait, lookahead: new LookaheadSettings(1)));
    }

    [Fact]
    public void The_lookahead_sweep_reports_the_beta_and_reach_arms_and_the_adopted_reference()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportLookahead(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "look b=0.5 l=0", "look b=2 l=1000", "need+wait (adopted)", "held-out gain over need+wait (adopted)" }) Assert.Contains(expected, text);
    }
}
