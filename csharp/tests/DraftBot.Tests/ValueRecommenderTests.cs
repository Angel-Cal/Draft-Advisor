using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class ValueRecommenderTests
{
    // 2 teams, 1 starter at each position, no FLEX, 2 bench spots; a fresh draft is at pick 1 (sigma 2.16)
    static readonly LeagueSettings Small = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 2);

    static ValuedPlayer V(string id, Position position, double adp, double vor) =>
        new(Player(id, position, 200, adp: adp), vor, 0, 0, false, 1, 0, 1);

    static DraftState State(params ValuedPlayer[] pool) => new(pool, Small);

    [Fact]
    public void Score_is_vor_minus_lambda_times_z_squared_and_compares_players_across_positions()
    {
        // pick 1: sigma 2.16. The WR is 5 picks past the pick (z = 2.31), the RB sits right at it.
        var state = State(V("wr", Position.WR, adp: 6, vor: 120), V("rb", Position.RB, adp: 1, vor: 80));

        var ranked = ValueRecommender.Rank(state, new ReachSettings(Lambda: 10, CapSigmas: 4)).ToDictionary(c => c.Player.Id);

        var z = 5 / (2 + 0.16);
        Assert.Equal(z, ranked["wr"].ReachSigmas, 9);
        Assert.Equal(10 * z * z, ranked["wr"].ReachPenalty, 9);
        Assert.Equal(120 - 10 * z * z, ranked["wr"].Score, 9);      // 66.6
        Assert.Equal(80, ranked["rb"].Score);                          // no reach, no penalty
        Assert.Equal("rb", ValueRecommender.Recommend(state, new ReachSettings(10, 4))[0].Player.Id);
        Assert.Equal("wr", ValueRecommender.Recommend(state, new ReachSettings(1, 4))[0].Player.Id);        // cheap reach: value wins
    }

    [Fact]
    public void Without_a_reach_cost_it_is_pure_vor_inside_the_cap()
    {
        var state = State(V("a", Position.QB, adp: 1, vor: 30), V("b", Position.TE, adp: 2, vor: 90), V("c", Position.WR, adp: 60, vor: 500));

        var ranked = ValueRecommender.Rank(state, new ReachSettings(Lambda: 0, CapSigmas: 4));

        Assert.Equal(["b", "a"], ranked.Select(c => c.Player.Id));       // c is 27 sigma out, beyond the cap
    }

    [Fact]
    public void A_player_who_slid_is_never_penalized()
    {
        var state = State(V("slid", Position.WR, adp: 1, vor: 40));          // ADP at or before the pick

        var only = ValueRecommender.Rank(state, new ReachSettings(1e6, 4)).Single();

        Assert.Equal(0, only.ReachSigmas);
        Assert.Equal(40, only.Score);
    }

    [Fact]
    public void An_empty_window_falls_back_to_everyone()
    {
        var state = State(V("late-1", Position.WR, adp: 90, vor: 10), V("late-2", Position.RB, adp: 95, vor: 20));

        Assert.Equal(2, ValueRecommender.Rank(state, new ReachSettings(10, 4)).Count);
    }

    [Fact]
    public void The_strategy_takes_the_best_legal_suggestion_not_just_the_top_five()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var state = new DraftState(pool, new LeagueSettings());
        var reach = new ReachSettings(10, 6);
        var topFive = ValueRecommender.Recommend(state, reach).Select(c => c.Player.Id).ToHashSet();
        var legal = state.Available.Where(p => !topFive.Contains(p.Id)).ToList();         // every top suggestion is blocked

        var pick = new ValueRecommenderStrategy("v", reach).Pick(state, 0, legal);

        Assert.Equal(ValueRecommender.Rank(state, reach).First(c => !topFive.Contains(c.Player.Id)).Player.Id, pick.Id);
    }

    [Fact]
    public void The_value_strategy_is_a_valid_drafter()
    {
        var file = BacktestFile();
        var pool = Valuator.Value(file.Players, file.PositionRmse, new LeagueSettings());

        var result = DraftSimulator.Run(pool, new SimSettings(new LeagueSettings()), 7, new ValueRecommenderStrategy("v", ValueRecommender.DefaultReach), seed: 1);

        Assert.InRange(result.Finish, 1, 12);
        Assert.Equal(16, result.MyPicks.Count);
    }

    [Fact]
    public void The_mock_draft_can_run_the_single_score_recommender()
    {
        var output = new StringWriter();
        var finished = new MockDraft(BacktestFile(), new SimSettings(new LeagueSettings()), 5, 0, false,
            new StringReader(string.Concat(Enumerable.Repeat("\n", 16))), output, ValueRecommender.DefaultReach, singleScore: true).Run();
        var text = output.ToString();

        Assert.True(finished);
        Assert.Contains("Single-score recommender", text);
        Assert.DoesNotContain("step 1: which position", text);
        Assert.Contains("value", text.Substring(text.IndexOf("Same slot and opponents", StringComparison.Ordinal)));
    }

    [Fact]
    public void The_single_score_mock_draft_needs_reach_settings()
    {
        Assert.Throws<ArgumentException>(() => new MockDraft(BacktestFile(), new SimSettings(new LeagueSettings()), 0, 0, false,
            new StringReader(""), new StringWriter(), reach: null, singleScore: true));
    }

    [Fact]
    public void The_arm_sweep_reports_each_arm_and_a_leave_one_season_out_check()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };
        IDraftStrategy[] arms = [new ValueRecommenderStrategy("a1", new ReachSettings(10, 4)), new ValueRecommenderStrategy("a2", new ReachSettings(1000, 4))];

        var text = ArmSweep.Report(files, new SimSettings(new LeagueSettings()), 1, arms, [new AdpStrategy(), new VorStrategy()], headline: "vor");

        foreach (var expected in new[] { "a1", "a2", "adp", "vor", "leave-one-season-out", "held-out gain over vor", "2023", "2024" })
            Assert.Contains(expected, text);
    }
}
