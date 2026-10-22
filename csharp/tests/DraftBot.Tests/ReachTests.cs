using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class ReachTests
{
    // 2 teams, 1 starter at each position, no FLEX, 2 bench spots; a fresh draft is at pick 1
    static readonly LeagueSettings Small = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 2);
    static readonly ReachSettings Reach = new(Lambda: 0.3, CapSigmas: 4);

    static ValuedPlayer V(string id, Position position, double adp, double vorRank, double valueGap, int tier = 1) =>
        new(Player(id, position, 200, adp: adp), 50, 0, 0, false, vorRank, valueGap, tier);

    static DraftState State(params ValuedPlayer[] pool) => new(pool, Small);

    [Fact]
    public void Reach_is_measured_in_sigmas_past_the_current_pick_and_sigma_grows_with_the_pick()
    {
        Assert.Equal(2 + 0.16 * 6, Reach.Sigma(6), 12);
        Assert.Equal(6 / Reach.Sigma(6), Reach.Reach(Player("a", Position.WR, 100, adp: 12), pick: 6), 12);
        Assert.Equal(0, Reach.Reach(Player("b", Position.WR, 100, adp: 6), pick: 6));       // right at the pick
        Assert.Equal(0, Reach.Reach(Player("c", Position.WR, 100, adp: 3), pick: 6));       // slid: never a reach
        Assert.Equal(double.PositiveInfinity, Reach.Reach(Player("d", Position.WR, 100, adp: null), pick: 6));
        Assert.True(Reach.Sigma(100) > 5 * Reach.Sigma(6) / 2);
    }

    [Fact]
    public void The_cap_removes_far_reaches_that_the_baseline_would_pick()
    {
        var state = State(V("near", Position.WR, adp: 1, vorRank: 3, valueGap: -2), V("far", Position.WR, adp: 50, vorRank: 1, valueGap: 49));

        Assert.Equal("far", BaselineRecommender.SelectPlayers(Position.WR, state, 0).First().Player.Id);
        var windowed = BaselineRecommender.SelectPlayers(Position.WR, state, 0, Reach);

        Assert.Equal(["near"], windowed.Select(c => c.Player.Id));
    }

    [Fact]
    public void A_modest_reach_can_win_but_a_costly_one_cannot()
    {
        // pick 1: sigma 2.16. "mid" is 5 picks past the pick (z = 2.31) but much better by VOR rank and gap.
        var state = State(V("near", Position.WR, adp: 1, vorRank: 5, valueGap: -4), V("mid", Position.WR, adp: 6, vorRank: 1, valueGap: 5));

        var gentle = BaselineRecommender.SelectPlayers(Position.WR, state, 0, new ReachSettings(0.05, 4)).ToDictionary(c => c.Player.Id);
        var harsh = BaselineRecommender.SelectPlayers(Position.WR, state, 0, new ReachSettings(1.0, 4));

        var z = 5 / (2 + 0.16 * 1);
        Assert.Equal(z, gentle["mid"].ReachSigmas, 9);
        Assert.Equal(0.05 * z * z, gentle["mid"].ReachPenalty, 9);
        Assert.Equal(1.0 - 0.05 * z * z, gentle["mid"].WeightedValue, 9);      // rank 0.5 + gap 0.5 - penalty
        Assert.Equal(0, gentle["near"].WeightedValue, 9);
        Assert.Equal("mid", BaselineRecommender.SelectPlayers(Position.WR, state, 0, new ReachSettings(0.05, 4)).First().Player.Id);
        Assert.Equal("near", harsh.First().Player.Id);
    }

    [Fact]
    public void A_position_with_nobody_inside_the_window_cannot_be_chosen()
    {
        var state = State(
            V("wr-far", Position.WR, adp: 60, vorRank: 1, valueGap: 59, tier: 1),
            V("rb-1", Position.RB, adp: 1, vorRank: 2, valueGap: 0, tier: 1), V("rb-2", Position.RB, adp: 2, vorRank: 3, valueGap: 0, tier: 1));

        // WR has one player in its best tier (scarcity 2), RB has two (scarcity 1): the baseline wants the WR
        Assert.Equal(Position.WR, BaselineRecommender.SelectPosition(state, 0));
        var choice = BaselineRecommender.ChoosePosition(state, 0, Reach);

        Assert.Equal(Position.RB, choice.Position);
        Assert.False(choice.Scarcity.Single(s => s.Position == Position.WR).Considered);
        Assert.Equal(0, choice.Scarcity.Single(s => s.Position == Position.WR).Supply);     // supply counts only the window
    }

    [Fact]
    public void Turning_off_the_gap_term_drops_it_from_the_score()
    {
        var state = State(V("a", Position.WR, adp: 1, vorRank: 1, valueGap: 0), V("b", Position.WR, adp: 2, vorRank: 2, valueGap: 8));

        var withGap = BaselineRecommender.SelectPlayers(Position.WR, state, 0, new ReachSettings(0, 4)).ToDictionary(c => c.Player.Id);
        var without = BaselineRecommender.SelectPlayers(Position.WR, state, 0, new ReachSettings(0, 4, UseGapTerm: false)).ToDictionary(c => c.Player.Id);

        Assert.Equal(0.5, withGap["b"].GapTerm);
        Assert.Equal(0, without["b"].GapTerm);
        Assert.Equal(0.5, without["a"].WeightedValue);       // only the rank term remains
    }

    [Fact]
    public void An_empty_window_falls_back_to_everyone_rather_than_leaving_no_recommendation()
    {
        var state = State(V("late-1", Position.WR, adp: 90, vorRank: 1, valueGap: 0), V("late-2", Position.RB, adp: 95, vorRank: 2, valueGap: 0));

        Assert.Equal(2, BaselineRecommender.RecommendablePool(state, Reach).Count);
        Assert.NotEmpty(BaselineRecommender.Recommend(state, 0, Reach).Candidates);
    }

    [Fact]
    public void The_windowed_strategy_never_reaches_far_past_the_pick_in_a_realistic_pool()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var state = new DraftState(pool, new LeagueSettings());
        var pick = new WindowedRecommenderStrategy("w", Reach).Pick(state, 0, DraftRules.LegalPicks(state, 0, new SimSettings(new LeagueSettings())));

        Assert.True(pick.Player.Adp <= 1 + 4 * Reach.Sigma(1) + 1e-9, $"picked ADP {pick.Player.Adp} at pick 1");
    }

    [Fact]
    public void The_windowed_strategy_is_a_valid_drafter()
    {
        var file = BacktestFile();
        var pool = Valuator.Value(file.Players, file.PositionRmse, new LeagueSettings());

        var result = DraftSimulator.Run(pool, new SimSettings(new LeagueSettings()), 4, new WindowedRecommenderStrategy("w", Reach), seed: 2);

        Assert.InRange(result.Finish, 1, 12);
        Assert.True(result.Points > 0);
    }

    [Fact]
    public void The_mock_draft_shows_the_reach_control_and_the_windowed_strategy()
    {
        var output = new StringWriter();
        var finished = new MockDraft(BacktestFile(), new SimSettings(new LeagueSettings()), 5, 0, false,
            new StringReader(string.Concat(Enumerable.Repeat("\n", 16))), output, Reach).Run();
        var text = output.ToString();

        Assert.True(finished);
        Assert.Contains("Reach control on", text);
        Assert.Contains("reach penalty", text);
        Assert.Contains("windowed", text);
    }
}
