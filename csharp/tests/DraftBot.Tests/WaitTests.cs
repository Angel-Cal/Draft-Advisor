using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class WaitTests
{
    // 2 teams, 1 starter each at QB/RB/WR/TE and one FLEX; replacement points: QB 200, RB 100, WR 100, TE 50
    static readonly LeagueSettings Small = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 3);
    static readonly Dictionary<Position, double> Replacement = new()
        { [Position.QB] = 200, [Position.RB] = 100, [Position.WR] = 100, [Position.TE] = 50 };

    static ValuedPlayer V(string id, Position position, double projected, double adp) =>
        new(Player(id, position, projected, adp: adp), projected - Replacement[position], 0, 0, false, 1, 0, 1);

    [Fact]
    public void The_next_pick_follows_the_snake()
    {
        var state = new DraftState(RealisticValued(), new LeagueSettings());      // 12 teams

        Assert.Equal(24, state.NextPick(0));         // on the clock at pick 1, back at 24
        Assert.Equal(6, state.NextPick(5));          // not yet on the clock: the next pick is the first one
        for (var i = 0; i < 5; i++) state.Draft(state.Available[0].Id);
        Assert.Equal(19, state.NextPick(5));         // on the clock at pick 6, back at 19
        for (var i = 0; i < 6; i++) state.Draft(state.Available[0].Id);
        Assert.Equal(13, state.NextPick(11));        // on the clock at pick 12, back at 13
    }

    [Fact]
    public void A_team_has_no_next_pick_in_the_last_round()
    {
        var state = new DraftState(RealisticValued(), new LeagueSettings());
        while (state.Round < state.League.RosterSize) Assert.True(state.Draft(state.Available[0].Id));

        Assert.Null(state.NextPick(state.CurrentTeam));
        Assert.NotNull(state.NextPick(state.League.Teams - 1 - state.CurrentTeam));       // the other end of the snake still has one
    }

    [Fact]
    public void Survival_falls_as_the_adp_gets_earlier_than_the_pick()
    {
        var reach = new ReachSettings(1000, 4);

        Assert.True(WaitSettings.Survival(Player("late", Position.WR, 100, adp: 60), 24, reach) > 0.99);
        Assert.InRange(WaitSettings.Survival(Player("due", Position.WR, 100, adp: 24), 24, reach), 0.45, 0.6);
        Assert.True(WaitSettings.Survival(Player("early", Position.WR, 100, adp: 5), 24, reach) < 0.01);
        Assert.Equal(1, WaitSettings.Survival(Player("unranked", Position.WR, 100), 24, reach));
    }

    [Fact]
    public void Expected_shortfall_is_the_points_lost_by_waiting_when_the_replacement_may_be_gone()
    {
        Assert.Equal(0, WaitSettings.ExpectedShortfall(50, [(60, 1.0)]), 9);                  // a better one is certain to last
        Assert.Equal(0, WaitSettings.ExpectedShortfall(50, [(50, 1.0)]), 9);                  // an equal one is certain to last
        Assert.Equal(50, WaitSettings.ExpectedShortfall(50, []), 9);                          // nobody is left: all of it is lost
        Assert.Equal(50, WaitSettings.ExpectedShortfall(50, [(40, 0.0)]), 9);                 // the alternative is gone for sure
        Assert.Equal(0.5 * 60 + 0.5 * 100, WaitSettings.ExpectedShortfall(100, [(40, 0.5)]), 9);
        // first alternative lasts 50%; if not, the next lasts 100%: 0.5 x (100-80) + 0.5 x (100-30)
        Assert.Equal(0.5 * 20 + 0.5 * 70, WaitSettings.ExpectedShortfall(100, [(80, 0.5), (30, 1.0)]), 9);
    }

    [Fact]
    public void A_scarce_position_wins_when_waiting_would_cost_a_tier_and_loses_when_an_equal_player_will_last()
    {
        // pick 1 of 2 teams, so my next pick is 4. WR B (adp 5) will probably last; the second TE (adp 30) is far worse than the first.
        var state = new DraftState([V("te1", Position.TE, 90, 1), V("te2", Position.TE, 55, 30),
                                    V("wrA", Position.WR, 150, 2), V("wrB", Position.WR, 148, 5)], Small);
        var reach = new ReachSettings(0, 100);

        Assert.Equal("wrA", ValueRecommender.Rank(state, reach)[0].Player.Id);            // plain VOR: 50 vs 40
        var waited = ValueRecommender.Rank(state, reach, wait: new WaitSettings(1)).ToDictionary(c => c.Player.Id);

        Assert.True(waited["te1"].Score > waited["wrA"].Score);
        Assert.InRange(waited["te1"].WaitBonus!.Value, 34.9, 35.1);                         // te2 is worth 5 and certain to last: lose 35
        Assert.InRange(waited["wrA"].WaitBonus!.Value, 15, 17);                             // wrB lasts about 70% of the time
        Assert.Equal(waited["te1"].BaseValue + waited["te1"].WaitBonus, waited["te1"].Score);
    }

    [Fact]
    public void A_free_zone_in_picks_is_the_same_number_of_picks_at_every_point_in_the_draft()
    {
        // pick 1: wrB (adp 3.5) is 2.5 picks early, so a 1-pick free zone leaves 1.5 picks charged, in sigmas of that pick
        var state = new DraftState([V("wrA", Position.WR, 150, 2), V("wrB", Position.WR, 148, 3.5)], Small);
        double Penalty(string id, double picks) =>
            ValueRecommender.Rank(state, new ReachSettings(1000, 4, FreePicks: picks)).Single(c => c.Player.Id == id).ReachPenalty;
        var sigma = new ReachSettings(1000, 4).Sigma(1);

        Assert.Equal(0, Penalty("wrA", 1), 9);                                                    // 1 pick early: free
        Assert.Equal(1000 * Math.Pow(1.5 / sigma, 2), Penalty("wrB", 1), 6);                      // 2.5 - 1 picks beyond the free zone
        var late = new ReachSettings(1000, 4);
        Assert.Equal(1.0 / late.Sigma(1), late.Reach(V("x", Position.WR, 1, 2).Player, 1), 9);   // the plain reach of a player 1 pick early
        Assert.Equal(0, new ReachSettings(1000, 4, FreePicks: 1).Charged(V("x", Position.WR, 1, 101).Player, 100), 9);   // the same 1 pick is free at pick 100 too
    }

    [Fact]
    public void Alternatives_outside_the_recommendable_window_still_count()
    {
        // te2 (adp 12) is beyond the 4-sigma reach cap at pick 1 (5.1 sigma), so it cannot be recommended now, but at pick 4 it is inside the cap (3.0 sigma) and 98.5% likely to be there
        var state = new DraftState([V("te1", Position.TE, 90, 1), V("te2", Position.TE, 55, 12), V("wrA", Position.WR, 150, 2)], Small);

        var ranked = ValueRecommender.Rank(state, new ReachSettings(1000, 4), wait: new WaitSettings(1));

        Assert.DoesNotContain(ranked, c => c.Player.Id == "te2");
        Assert.InRange(ranked.Single(c => c.Player.Id == "te1").WaitBonus!.Value, 34.9, 35.2);      // about the 35 te2 falls short, not the full 40
    }

    [Fact]
    public void A_zero_weight_or_no_later_pick_leaves_the_scores_alone()
    {
        var state = new DraftState(RealisticValued(), new LeagueSettings());
        var reach = ValueRecommender.DefaultReach;
        var plain = ValueRecommender.Rank(state, reach, NeedSettings.Default);

        var zero = ValueRecommender.Rank(state, reach, NeedSettings.Default, wait: new WaitSettings(0));
        Assert.Equal(plain.Select(c => (c.Player.Id, c.Score)), zero.Select(c => (c.Player.Id, c.Score)));
        Assert.All(zero, c => Assert.Null(c.WaitBonus));

        while (state.Round < state.League.RosterSize) state.Draft(state.Available[0].Id);
        var last = ValueRecommender.Rank(state, reach, NeedSettings.Default, state.CurrentTeam, new WaitSettings(1));
        Assert.All(last, c => Assert.Null(c.WaitBonus));
    }

    [Fact]
    public void Upcoming_picks_follow_the_snake_and_stop_when_the_draft_ends()
    {
        var state = new DraftState(RealisticValued(), new LeagueSettings());           // 12 teams

        Assert.Equal([24, 25, 48, 49], state.UpcomingPicks(0, 4));                      // the turn of the snake gives back-to-back picks
        Assert.Equal([24], state.UpcomingPicks(0, 1));
        Assert.Empty(state.UpcomingPicks(0, 0));
        Assert.Equal(24, state.NextPick(0));
        var all = state.UpcomingPicks(0, 1000);
        Assert.Equal(state.League.RosterSize - 1, all.Count);                           // every round but the one on the clock
    }

    [Fact]
    public void The_mock_draft_explains_and_shows_the_cost_of_waiting_when_it_is_on()
    {
        string Run(WaitSettings? wait)
        {
            var output = new StringWriter();
            new MockDraft(BacktestFile(), new SimSettings(new LeagueSettings()), 5, 0, false, new StringReader(string.Concat(Enumerable.Repeat("\n", 16))), output,
                ValueRecommender.DefaultReach, singleScore: true, need: NeedSettings.Default, wait: wait).Run();
            return output.ToString();
        }

        var withWait = Run(ValueRecommender.DefaultWait);
        var without = Run(null);

        Assert.Equal(4, ValueRecommender.DefaultWait.Weight);
        Assert.Contains("cost of waiting", withWait);
        Assert.Contains("need+wait", withWait);
        Assert.DoesNotContain("cost of waiting", without);
    }

    [Fact]
    public void The_fallback_is_the_best_alternative_likely_to_last_that_the_recommender_could_take_at_the_next_pick()
    {
        // 4 teams: I pick 1st and 8th. "gone" is better than "near" but will not last to pick 8; "far" will last but is far past his ADP there
        var league = new LeagueSettings(Teams: 4, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);
        ValuedPlayer V(string id, Position position, double projected, double adp) => new(Player(id, position, projected, adp: adp), projected - 100, 0, 0, false, 1, 0, 1, 50);
        ValuedPlayer[] Fillers() => Enumerable.Range(1, 30).Select(i => V($"f{i}", Position.WR, 100, 100 + i)).ToArray();
        var state = new DraftState([V("star", Position.RB, 250, 2), V("gone", Position.RB, 245, 3), V("far", Position.RB, 240, 60), V("near", Position.RB, 160, 9),
                                    V("near2", Position.RB, 150, 12), V("near3", Position.RB, 140, 14), .. Fillers()], league);
        var reach = ValueRecommender.DefaultReach;

        ValueCandidate Star(WaitSettings wait) => ValueRecommender.Rank(state, reach, NeedSettings.Default, 0, wait).Single(c => c.Player.Id == "star");

        var star = Star(ValueRecommender.DefaultWait);
        Assert.Equal("near", star.WaitFallback!.Player.Id);
        Assert.Equal(["near", "near2"], star.WaitAlternatives!.Select(a => a.Candidate.Player.Id));          // best first, at most two
        Assert.All(star.WaitAlternatives!, a => Assert.True(a.Survival >= 0.5));
        Assert.Equal(star.WaitBonus!.Value, star.WaitShortfall!.Value * 4, 6);
        Assert.DoesNotContain(star.WaitAlternatives!, a => a.Candidate.Player.Id == "far");                // certain to last, but 16 spreads past his ADP at pick 8: not a pick the advisor would make

        var alone = new DraftState([V("star", Position.RB, 250, 2), .. Fillers()], league);
        var onlyHim = ValueRecommender.Rank(alone, reach, NeedSettings.Default, 0, ValueRecommender.DefaultWait).Single(c => c.Player.Id == "star");
        Assert.True(onlyHim.WaitBonus > 0);
        Assert.Null(onlyHim.WaitFallback);
        Assert.All(ValueRecommender.Rank(state, reach, NeedSettings.Default, 0), c => Assert.Null(c.WaitFallback));
    }

    static List<ValuedPlayer> RealisticValued() => Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
}
