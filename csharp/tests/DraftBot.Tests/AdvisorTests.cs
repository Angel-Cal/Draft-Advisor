using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class AdvisorTests
{
    // 4 teams, 1 starter each at QB/RB/WR/TE, 3 bench spots: team 0 picks 1st and 8th; every position's replacement level is 100 points
    static readonly LeagueSettings Four = new(Teams: 4, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);

    static ValuedPlayer V(string id, Position position, double projected, double adp) =>
        new(Player(id, position, projected, adp: adp), projected - 100, 0, 0, false, 1, 0, 1, 50);

    // five players at ADP 1 (no reach cost at pick 1) make up the top five; "wall" is a strong receiver 2.5 picks past the pick, "stretch" is further out; "far" is never recommendable
    static Advice AdviceAtPickOne() => DraftAdvisor.Advise(new DraftState([
        V("star", Position.RB, 250, 1), V("w1", Position.WR, 150, 1), V("w2", Position.WR, 148, 1), V("q1", Position.QB, 220, 1), V("t1", Position.TE, 180, 1),
        V("wall", Position.WR, 240, 3.5), V("stretch", Position.WR, 235, 5.4), V("near", Position.RB, 200, 8), V("far", Position.RB, 240, 60),
        V("q2", Position.QB, 215, 12), V("t2", Position.TE, 170, 12)], Four), 0);          // q2 and t2 will last to pick 8, so waiting on QB or TE costs little

    [Fact]
    public void The_advice_has_five_ranked_recommendations_each_with_named_tags()
    {
        var advice = AdviceAtPickOne();

        Assert.Equal(1, advice.Pick);
        Assert.Equal(8, advice.NextPick);
        Assert.Equal([1, 2, 3, 4, 5], advice.Recommended.Select(r => r.Rank));
        var first = advice.Recommended[0];
        Assert.Equal("star", first.Candidate.Player.Id);
        Assert.Contains(first.Tags, t => t.Name == "Starter" && t.Text == "He fills an open starting RB spot.");
        Assert.Contains(first.Tags, t => t.Label == ReasonLabel.RunningOut && t.Name == "Recommended" && t.Text.Contains("near, projected 200"));
    }

    [Fact]
    public void Each_position_tile_has_the_top_player_the_cost_of_waiting_and_who_is_likely_to_last()
    {
        var advice = AdviceAtPickOne();

        Assert.Equal([Position.QB, Position.RB, Position.WR, Position.TE], advice.Positions.Select(p => p.Position));
        var rb = advice.Positions.Single(p => p.Position == Position.RB);
        Assert.Equal("star", rb.Top.Player.Id);
        Assert.Equal(rb.Top.WaitShortfall, rb.CostOfWaiting);
        Assert.True(rb.TakeNow);
        Assert.Equal(["near"], rb.LikelyThere.Select(a => a.Candidate.Player.Id));          // "far" lasts too, but is far past his ADP at pick 8
        Assert.InRange(rb.LikelyThere[0].Survival, 0.5, 0.65);
    }

    [Fact]
    public void Players_beyond_the_reach_limit_are_listed_unranked_with_how_early_they_would_be()
    {
        var advice = AdviceAtPickOne();

        var wall = Assert.Single(advice.PastTheWall);              // "stretch" and "near" are past 1.5 sigma and "far" is not recommendable at all
        Assert.Equal("wall", wall.Player.Id);
        Assert.Equal(2.5, wall.PicksEarly, 6);
        Assert.DoesNotContain(advice.Recommended, r => r.Candidate.Player.Id == "wall");
    }

    [Fact]
    public void Only_the_top_pick_is_tagged_recommended_and_only_its_position_is_the_recommended_tile()
    {
        var advice = AdviceAtPickOne();

        Assert.Null(advice.Rival);
        var tagged = advice.Recommended.Where(r => r.Tags.Any(t => t.Label == ReasonLabel.RunningOut)).Select(r => r.Rank);
        Assert.Equal([1], tagged);                                            // waiting costs points at other positions too, but that is not a recommendation
        Assert.Equal([Position.RB], advice.Positions.Where(p => p.IsRecommended).Select(p => p.Position));
        Assert.Contains(advice.Positions, p => p.TakeNow && !p.IsRecommended);          // costly to wait on, yet not what the advice backs
    }

    [Fact]
    public void The_top_pick_is_tagged_recommended_even_when_waiting_on_him_is_cheap_with_a_reason_that_says_why()
    {
        // a better RB will surely last to pick 8, so waiting costs almost nothing, yet "star" is still the pick
        var advice = DraftAdvisor.Advise(new DraftState([
            V("star", Position.RB, 200, 1), V("twin", Position.RB, 205, 16), V("w", Position.WR, 110, 12), V("q", Position.QB, 105, 12), V("t", Position.TE, 105, 12)], Four), 0);

        var top = advice.Recommended[0];
        Assert.Equal("star", top.Candidate.Player.Id);
        Assert.True(top.Candidate.WaitShortfall < 5);
        var tag = Assert.Single(top.Tags, t => t.Label == ReasonLabel.RunningOut);
        Assert.Equal("Recommended", tag.Name);
        Assert.StartsWith("The best overall pick at this spot", tag.Text);
        Assert.Contains("so you are not reaching for him", tag.Text);
        Assert.Equal("Starter", top.Tags[0].Name);                    // tags keep their order: the lineup reason first
    }

    [Fact]
    public void In_a_close_call_both_positions_are_recommended_and_both_top_picks_carry_the_tag()
    {
        // two identical strong players at RB and WR, each with the same later alternative: a tie
        var advice = DraftAdvisor.Advise(new DraftState([
            V("a", Position.RB, 200, 1), V("a2", Position.RB, 150, 8), V("b", Position.WR, 200, 1), V("b2", Position.WR, 150, 8),
            V("q", Position.QB, 105, 12), V("t", Position.TE, 105, 12)], Four), 0);

        Assert.NotNull(advice.Rival);
        Assert.Equal(2, advice.Positions.Count(p => p.IsRecommended));
        var tagged = advice.Recommended.Where(r => r.Tags.Any(t => t.Label == ReasonLabel.RunningOut)).Select(r => r.Candidate.Player.Id).Order();
        Assert.Equal(["a", "b"], tagged);
    }

    [Fact]
    public void Early_picks_are_not_recommended_even_when_they_would_rank_in_the_top_five_they_go_past_the_wall()
    {
        // three sane picks at ADP 1, and a strong receiver 2.5 picks early (1.16 sigma): ranked fourth before, now unranked
        var advice = DraftAdvisor.Advise(new DraftState([
            V("star", Position.RB, 250, 1), V("w1", Position.WR, 150, 1), V("q1", Position.QB, 220, 1),
            V("wall", Position.WR, 240, 3.5), V("t2", Position.TE, 170, 12)], Four), 0);

        Assert.Equal(["q1", "star", "w1"], advice.Recommended.Select(r => r.Candidate.Player.Id).Order());
        Assert.DoesNotContain(advice.Recommended, r => r.Candidate.Player.Id == "wall");
        Assert.DoesNotContain(advice.Recommended.SelectMany(r => r.Tags), t => t.Label == ReasonLabel.Reach);
        Assert.Equal(["wall"], advice.PastTheWall.Select(w => w.Player.Id));
    }

    [Fact]
    public void A_reach_the_advisor_charges_for_is_not_a_card_and_marks_its_position()
    {
        // a quarterback 3.2 picks early who would probably last to the next pick (1.5 sigma): the cost is well past the reach line, so no card, and his position says its best player is a reach
        var advice = DraftAdvisor.Advise(new DraftState([
            V("star", Position.RB, 250, 1), V("w1", Position.WR, 150, 1), V("t1", Position.TE, 180, 1),
            V("slight", Position.QB, 300, 4.2), V("q2", Position.QB, 150, 12)], Four), 0);

        Assert.DoesNotContain(advice.Recommended, r => r.Candidate.Player.Id == "slight");
        Assert.Contains("slight", advice.PastTheWall.Select(w => w.Player.Id));
        Assert.True(advice.Positions.Single(p => p.Position == Position.QB).TopIsReach);
        Assert.False(advice.Positions.Single(p => p.Position == Position.RB).TopIsReach);
    }

    [Fact]
    public void A_pick_that_is_early_by_less_than_the_free_pick_is_a_card_and_not_a_reach()
    {
        // 0.9 picks early: inside the first free pick of the reach cost, so the screen and the score agree that it is not a reach (it used to be one at 0.25 sigma)
        var advice = DraftAdvisor.Advise(new DraftState([
            V("star", Position.RB, 250, 1), V("w1", Position.WR, 150, 1), V("t1", Position.TE, 180, 1),
            V("slight", Position.QB, 300, 1.9), V("q2", Position.QB, 150, 12)], Four), 0);

        Assert.Contains(advice.Recommended, r => r.Candidate.Player.Id == "slight");
        Assert.Equal(0, advice.Recommended.Single(r => r.Candidate.Player.Id == "slight").Candidate.ReachPenalty);
        Assert.False(advice.Positions.Single(p => p.Position == Position.QB).TopIsReach);
    }

    [Fact]
    public void The_top_pick_share_says_how_firmly_a_pick_stands()
    {
        // a clear best pick is first in every nudged re-ranking; two near-identical players at different positions split the top spot and make the call close
        var clear = DraftAdvisor.Advise(new DraftState([V("star", Position.RB, 300, 1), V("w1", Position.WR, 150, 8), V("t1", Position.TE, 120, 9)], Four), 0);
        Assert.Equal(1.0, clear.Recommended[0].TopShare);
        Assert.Null(clear.Rival);

        var tied = DraftAdvisor.Advise(new DraftState([V("rb", Position.RB, 250, 5.8), V("wr", Position.WR, 250, 6.2), V("t1", Position.TE, 120, 30)], Four), 0);
        Assert.InRange(tied.Recommended[0].TopShare!.Value, 0.3, 0.8);
        Assert.NotNull(tied.Rival);
        Assert.Equal(tied.Recommended.Take(2).Sum(r => r.TopShare!.Value), tied.Recommended.Sum(r => r.TopShare!.Value), 9);   // the shares of a tie add up (nobody else is first)

        Assert.Null(clear.TossUp);
        Assert.Equal(2, tied.TossUp!.Rank);

        // each card says what it gives up against the first: nothing for the first, a real gap behind a clear pick, a tie behind a tied one
        Assert.Equal(0, clear.Recommended[0].BehindTop);
        Assert.True(clear.Recommended[0].NearTop);
        var gap = DraftAdvisor.Advise(new DraftState([V("star", Position.RB, 300, 1), V("w1", Position.WR, 150, 1.2), V("t1", Position.TE, 120, 9)], Four), 0);
        Assert.Equal(gap.Recommended[0].Candidate.Score - gap.Recommended[1].Candidate.Score, gap.Recommended[1].BehindTop, 9);
        Assert.False(gap.Recommended[1].NearTop);
        Assert.Equal(DraftAdvisor.RealPoints(gap.Recommended[0].Candidate) - DraftAdvisor.RealPoints(gap.Recommended[1].Candidate), gap.Recommended[1].PointsBehindTop, 9);
        var weighted = new ValueCandidate(Valued("w", Position.TE), 300, 10, 0, Gain: 80, BenchValue: 5, WaitBonus: 200, WaitShortfall: 50);
        Assert.Equal(135, DraftAdvisor.RealPoints(weighted), 9);       // 80 + 5 + the unweighted 50: no x4 weight, no reach cost
        var even = DraftAdvisor.Advise(new DraftState([V("rb", Position.RB, 250, 1), V("wr", Position.WR, 250, 1.1), V("t1", Position.TE, 120, 9)], Four), 0);
        Assert.True(even.Recommended[1].NearTop);
    }

    [Fact]
    public void A_dead_pick_is_never_a_card()
    {
        // late in a real practice draft, the structural bench weights mark players who can never start or be needed as dead picks; none may reach the cards
        var file = BacktestFile();
        var state = new DraftState(Valuator.Value(file.Players, file.PositionRmse, new LeagueSettings()), new LeagueSettings());
        var checkedPicks = 0;
        while (!state.IsComplete)
        {
            var team = state.CurrentTeam;
            var advice = DraftAdvisor.Advise(state, team, confidenceSamples: 0);
            if (advice.Recommended.Any(r => r.Candidate.Score > ValueRecommender.DeadPickScore / 2))
            {
                Assert.All(advice.Recommended, r => Assert.True(r.Candidate.Score > ValueRecommender.DeadPickScore / 2, $"pick {advice.Pick}: {r.Candidate.Player.Player.PlayerName}"));
                checkedPicks++;
            }
            state.Draft(advice.Recommended[0].Candidate.Player.Id);
        }
        Assert.True(checkedPicks > 0);
    }

    [Fact]
    public void A_gap_that_is_mostly_reach_cost_reads_as_too_early()
    {
        ValueCandidate C(double score, double reach) => new(Valued("x", Position.RB), score, 0, 0) { ReachPenalty = reach };

        Assert.True(DraftAdvisor.MostlyReach(C(100, 0), C(-80, 170)));      // 180 behind, 170 of it reach cost
        Assert.False(DraftAdvisor.MostlyReach(C(100, 0), C(70, 10)));       // 30 behind, 10 of it reach cost: a real value gap
        Assert.True(DraftAdvisor.MostlyReach(C(100, 20), C(60, 40)));       // only the extra reach over the first card counts: 20 of 40
        Assert.False(DraftAdvisor.MostlyReach(C(100, 0), C(100, 0)));       // no gap
    }

    [Fact]
    public void The_toss_up_is_the_next_pick_with_the_largest_share_of_at_least_a_fifth()
    {
        RankedPick R(int rank, double? share) => new(rank, new ValueCandidate(Valued($"p{rank}", Position.RB), 0, 0, 0), "", [], share);

        Assert.Equal(3, DraftAdvisor.TossUpWith([R(1, 0.5), R(2, 0.2), R(3, 0.3)])!.Rank);
        Assert.Null(DraftAdvisor.TossUpWith([R(1, 0.85), R(2, 0.15)]));                 // under a fifth: the top pick stands clear
        Assert.Null(DraftAdvisor.TossUpWith([R(1, null), R(2, null)]));                 // the check was skipped
        Assert.Equal(2, DraftAdvisor.TossUpWith([R(1, 0.1), R(2, 0.9)])!.Rank);          // never the top pick itself
    }

    [Fact]
    public void The_top_pick_shares_are_the_same_every_time_and_can_be_skipped()
    {
        var state = new DraftState([V("rb", Position.RB, 250, 5.8), V("wr", Position.WR, 250, 6.2), V("t1", Position.TE, 120, 30)], Four);

        Assert.Equal(DraftAdvisor.Advise(state, 0).Recommended.Select(r => r.TopShare), DraftAdvisor.Advise(state, 0).Recommended.Select(r => r.TopShare));
        Assert.All(DraftAdvisor.Advise(state, 0, confidenceSamples: 0).Recommended, r => Assert.Null(r.TopShare));
    }

    [Fact]
    public void When_only_early_picks_are_left_they_are_still_recommended()
    {
        var advice = DraftAdvisor.Advise(new DraftState([
            V("a", Position.RB, 250, 3.5), V("b", Position.WR, 150, 3.6), V("c", Position.QB, 220, 3.7), V("d", Position.TE, 170, 3.8)], Four), 0);

        Assert.Equal(4, advice.Recommended.Count);
        Assert.Empty(advice.PastTheWall);
    }

    [Fact]
    public void A_close_call_is_when_the_best_pick_at_another_position_scores_almost_the_same()
    {
        ValueCandidate C(string id, Position position, double score) => new(Valued(id, position), score, 0, 0);

        Assert.Equal(Position.WR, DraftAdvisor.RivalPosition([C("a", Position.RB, 100), C("b", Position.WR, 98), C("c", Position.RB, 90)]));
        Assert.Equal(Position.WR, DraftAdvisor.RivalPosition([C("a", Position.RB, 100), C("b", Position.RB, 99), C("c", Position.WR, 96)]));      // the first other position decides
        Assert.Null(DraftAdvisor.RivalPosition([C("a", Position.RB, 100), C("b", Position.WR, 60)]));
        Assert.Null(DraftAdvisor.RivalPosition([C("a", Position.RB, 100), C("b", Position.RB, 99)]));          // no other position
        Assert.Null(DraftAdvisor.RivalPosition([C("a", Position.RB, 100)]));
        Assert.Equal(Position.TE, DraftAdvisor.RivalPosition([C("a", Position.RB, 3), C("b", Position.TE, -1)]));          // near zero, a few points is still a tie
    }

    [Fact]
    public void The_advice_carries_the_replacement_level_of_every_position()
    {
        var advice = AdviceAtPickOne();

        Assert.Equal(4, advice.Replacement.Count);
        Assert.All(advice.Replacement.Values, v => Assert.Equal(100, v, 6));
    }

    [Fact]
    public void Tags_are_named_for_the_screen_and_the_waiting_cost_reason_is_called_recommended()
    {
        Assert.Equal("Recommended", ReasonLabel.RunningOut.DisplayName());
        Assert.Equal("Not a starter", ReasonLabel.Backup.DisplayName());
        Assert.All(Enum.GetValues<ReasonLabel>(), label => Assert.False(string.IsNullOrWhiteSpace(label.DisplayName())));
    }
}
