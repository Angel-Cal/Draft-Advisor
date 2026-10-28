using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class ExplainerTests
{
    // 4 teams, 1 starter each at QB/RB/WR/TE, 3 bench spots: team 0 picks 1st and 8th
    static readonly LeagueSettings Four = new(Teams: 4, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);
    static readonly ReachSettings Reach = new(0, 100);

    static ValuedPlayer V(string id, Position position, double projected, double adp, bool injury = false, bool market = false) =>
        new(Player(id, position, projected, adp: adp, injury: injury, market: market), projected - 100, 0, 0, false, 1, 0, 1, 50);

    static DraftState Pool(params ValuedPlayer[] extra) =>
        new(extra.Concat(Enumerable.Range(1, 30).Select(i => V($"f{i}", Position.WR, 100, 100 + i))), Four);

    static ValueCandidate Candidate(ValuedPlayer p, double? gain = 50, double? bench = 0, double? wait = null, double sigmas = 0) =>
        new(p, 50, 0, sigmas, gain, gain is null ? null : 0.25, bench, wait);

    [Fact]
    public void A_player_who_fills_an_open_slot_is_described_as_starting_with_the_points_he_adds()
    {
        var star = V("star", Position.RB, 250, 2);
        var state = Pool(star);

        var e = Explainer.Explain(state, 0, [Candidate(star, gain: 80)], Reach)[0];

        Assert.Contains("fills an open starting RB spot", e.Reasons[0]);
        Assert.Contains("250", e.Reasons[0]);
        Assert.Equal(ReasonLabel.Starter, e.Labels[0]);
        Assert.StartsWith("star (RB, KC): he would start for you, adding about 80 points", e.Headline);
    }

    [Fact]
    public void A_player_who_beats_a_current_starter_is_described_by_the_player_he_displaces()
    {
        var old = V("old", Position.RB, 150, 30);
        var better = V("better", Position.RB, 200, 5);
        var state = Pool(old, better);
        state.Draft("old");

        var e = Explainer.Explain(state, 0, [Candidate(better, gain: 50)], Reach)[0];

        Assert.Contains("would start ahead of old (150 projected)", e.Reasons[0]);
    }

    [Fact]
    public void A_player_who_does_not_start_is_described_as_insurance_for_the_best_player_at_his_position()
    {
        var old = V("old", Position.RB, 220, 3);
        var backup = V("backup", Position.RB, 120, 40);
        var state = Pool(old, backup);
        state.Draft("old");

        var e = Explainer.Explain(state, 0, [Candidate(backup, gain: 0, bench: 5)], Reach)[0];

        Assert.Equal(ReasonLabel.Backup, e.Labels[0]);
        Assert.Contains("insurance for old", e.Reasons[0]);
        Assert.Contains("insurance", e.Headline);
    }

    [Fact]
    public void The_waiting_reason_names_the_best_player_at_his_position_who_will_probably_last_and_how_much_worse_he_is()
    {
        var star = V("star", Position.RB, 250, 2);
        var gone = V("gone", Position.RB, 240, 3);          // ADP 3: will not last to pick 8
        var mid = V("mid", Position.RB, 190, 30);           // ADP 30: will
        var state = Pool(star, gone, mid);

        var e = Explainer.Explain(state, 0, [Candidate(star, gain: 80, wait: 30)], Reach, new WaitSettings(4))[0];

        Assert.Contains(ReasonLabel.RunningOut, e.Labels);
        var reason = e.Reasons[e.Labels.ToList().IndexOf(ReasonLabel.RunningOut)];
        Assert.Contains("mid", reason);
        Assert.Contains("#8", reason);
        Assert.Contains("60 points lower", reason);
    }

    [Fact]
    public void The_alternative_is_a_player_the_recommender_could_take_at_that_pick_not_one_far_past_his_ADP()
    {
        var star = V("star", Position.RB, 250, 2);
        var far = V("far", Position.RB, 240, 60);           // certain to last to pick 8, but 16 spreads past it: never recommendable
        var near = V("near", Position.RB, 200, 8);          // about even odds to last, and no reach
        var state = Pool(star, far, near);

        var e = Explainer.Explain(state, 0, [Candidate(star, gain: 80, wait: 30)], new ReachSettings(1000, 4), new WaitSettings(4))[0];

        var reason = e.Reasons[e.Labels.ToList().IndexOf(ReasonLabel.RunningOut)];
        Assert.Contains("near", reason);
        Assert.DoesNotContain("far", reason);
        Assert.Contains("50 points lower", reason);
    }

    [Fact]
    public void Waiting_is_not_called_costly_without_a_bonus_or_when_a_similar_player_will_last()
    {
        var star = V("star", Position.RB, 250, 2);
        var twin = V("twin", Position.RB, 245, 30);
        var state = Pool(star, twin);

        var noBonus = Explainer.Explain(state, 0, [Candidate(star, wait: null)], Reach, new WaitSettings(4))[0];
        var similar = Explainer.Explain(state, 0, [Candidate(star, wait: 3)], Reach, new WaitSettings(4))[0];

        Assert.DoesNotContain(ReasonLabel.RunningOut, noBonus.Labels);
        Assert.DoesNotContain(ReasonLabel.RunningOut, similar.Labels);
    }

    [Fact]
    public void The_headline_is_about_waiting_when_the_waiting_bonus_is_the_largest_term()
    {
        var star = V("star", Position.RB, 250, 2);
        var mid = V("mid", Position.RB, 190, 30);
        var state = Pool(star, mid);

        var e = Explainer.Explain(state, 0, [Candidate(star, gain: 20, bench: 0, wait: 60)], Reach, new WaitSettings(4))[0];

        Assert.Contains("RBs thin out before your next pick", e.Headline);
    }

    [Fact]
    public void A_reach_and_a_bargain_are_told_apart_by_how_far_his_ADP_is_from_the_pick()
    {
        var late = V("late", Position.RB, 200, 20);
        var early = V("early", Position.RB, 200, 1);
        var state = Pool(late, early);
        foreach (var filler in Enumerable.Range(1, 10)) state.Draft($"f{filler}");       // now pick 11

        var reach = Explainer.Explain(state, 0, [Candidate(late, sigmas: 2.5)], Reach)[0];
        var bargain = Explainer.Explain(state, 0, [Candidate(early)], Reach)[0];

        Assert.Contains(ReasonLabel.Reach, reach.Labels);
        Assert.Contains("#20", reach.Reasons.Last());
        Assert.Contains("#11", reach.Reasons.Last());
        Assert.Contains(ReasonLabel.Discount, bargain.Labels);
        Assert.DoesNotContain(ReasonLabel.Reach, bargain.Labels);
    }

    [Fact]
    public void An_injury_history_and_an_estimated_projection_are_flagged()
    {
        var risky = V("risky", Position.RB, 200, 10, injury: true, market: true);
        var state = Pool(risky);

        var e = Explainer.Explain(state, 0, [Candidate(risky)], Reach)[0];

        Assert.Contains(ReasonLabel.InjuryHistory, e.Labels);
        Assert.Contains(ReasonLabel.EstimatedProjection, e.Labels);
        Assert.Equal(e.Labels.Count, e.Reasons.Count);
    }

    [Fact]
    public void An_explanation_has_at_most_four_reasons_and_each_has_a_label()
    {
        var star = V("star", Position.RB, 250, 40, injury: true, market: true);
        var mid = V("mid", Position.RB, 190, 60);
        var state = Pool(star, mid);

        var e = Explainer.Explain(state, 0, [Candidate(star, gain: 80, wait: 30, sigmas: 3)], Reach, new WaitSettings(4))[0];

        Assert.Equal(4, e.Reasons.Count);
        Assert.Equal(4, e.Labels.Count);
        Assert.DoesNotContain(ReasonLabel.Reach, e.Labels);          // the least important reason is the one cut
    }

    [Fact]
    public void Without_roster_need_there_is_no_lineup_reason_and_the_headline_talks_about_value()
    {
        var star = V("star", Position.RB, 250, 2);
        var state = Pool(star);

        var e = Explainer.Explain(state, 0, [Candidate(star, gain: null)], Reach)[0];

        Assert.DoesNotContain(ReasonLabel.Starter, e.Labels);
        Assert.DoesNotContain(ReasonLabel.Backup, e.Labels);
        Assert.Contains("most projected value", e.Headline);
    }

    [Fact]
    public void Candidates_come_back_in_the_order_given_and_the_explanation_never_mentions_score_units()
    {
        var a = V("a", Position.RB, 250, 2);
        var b = V("b", Position.WR, 230, 3);
        var state = Pool(a, b);

        var all = Explainer.Explain(state, 0, [Candidate(b), Candidate(a)], Reach, new WaitSettings(4));

        Assert.Equal(["b", "a"], all.Select(e => e.Player.Id));
        Assert.All(all.SelectMany(e => e.Reasons.Append(e.Headline)), text => Assert.DoesNotContain("score", text, StringComparison.OrdinalIgnoreCase));
    }
}
