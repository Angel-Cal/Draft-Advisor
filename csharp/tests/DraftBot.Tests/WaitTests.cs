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
    public void The_survival_scaled_reach_cost_is_the_plain_cost_times_the_chance_he_lasts()
    {
        // pick 1 of 2 teams, next pick 4: wrA (adp 2) is a reach that will probably be gone by then, wrB (adp 8) is one that will last
        var state = new DraftState([V("wrA", Position.WR, 150, 2), V("wrB", Position.WR, 148, 8)], Small);
        double Penalty(string id, double power) =>
            ValueRecommender.Rank(state, new ReachSettings(1000, 4, SurvivalPower: power)).Single(c => c.Player.Id == id).ReachPenalty;

        foreach (var id in new[] { "wrA", "wrB" })
        {
            var survival = WaitSettings.Survival(state.Available.Single(p => p.Id == id).Player, 4, ValueRecommender.DefaultReach);
            Assert.Equal(Penalty(id, 0) * survival, Penalty(id, 1), 6);
            Assert.Equal(Penalty(id, 0) * survival * survival, Penalty(id, 2), 6);
        }
        Assert.True(Penalty("wrA", 1) < 0.5 * Penalty("wrA", 0));
        Assert.True(Penalty("wrB", 1) > 0.9 * Penalty("wrB", 0));
    }

    [Fact]
    public void A_free_zone_makes_small_reaches_free_and_charges_only_what_lies_beyond_it()
    {
        // pick 1: wrA (adp 2) is 0.46 sigma early, wrB (adp 3.5) 1.16 sigma
        var state = new DraftState([V("wrA", Position.WR, 150, 2), V("wrB", Position.WR, 148, 3.5)], Small);
        double Penalty(string id, double free) =>
            ValueRecommender.Rank(state, new ReachSettings(1000, 4, FreeSigmas: free)).Single(c => c.Player.Id == id).ReachPenalty;

        Assert.Equal(0, Penalty("wrA", 0.5), 9);                                       // inside the free zone
        var z = new ReachSettings(1000, 4).Reach(state.Available.Single(p => p.Id == "wrB").Player, 1);
        Assert.Equal(1000 * (z - 0.5) * (z - 0.5), Penalty("wrB", 0.5), 6);           // only the part beyond 0.5 sigma
        Assert.Equal(1000 * z * z, Penalty("wrB", 0), 6);                              // the default is the plain cost
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
        // te2 (adp 30) is beyond the 4-sigma reach cap at pick 1, so it cannot be recommended now, but it will be there at pick 4
        var state = new DraftState([V("te1", Position.TE, 90, 1), V("te2", Position.TE, 55, 30), V("wrA", Position.WR, 150, 2)], Small);

        var ranked = ValueRecommender.Rank(state, new ReachSettings(1000, 4), wait: new WaitSettings(1));

        Assert.DoesNotContain(ranked, c => c.Player.Id == "te2");
        Assert.InRange(ranked.Single(c => c.Player.Id == "te1").WaitBonus!.Value, 34.9, 35.1);      // not the full 40
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
    public void The_wait_sweep_reports_the_weight_arms_and_the_need_control()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportWait(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "wait w=0.1", "wait w=2", "need", "adp", "held-out gain over need" }) Assert.Contains(expected, text);
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
    public void A_longer_horizon_sums_the_shortfall_over_my_next_picks_and_decay_discounts_the_later_ones()
    {
        // 2 teams: I pick 1, then 4, 5, 8, 9. te2 (adp 30) is worth 5 and certain to last to any of those picks, so waiting costs te1 35 at each one.
        var state = new DraftState([V("te1", Position.TE, 90, 1), V("te2", Position.TE, 55, 30)], Small);
        var reach = new ReachSettings(0, 100);

        double Bonus(WaitSettings wait) => ValueRecommender.Rank(state, reach, wait: wait).Single(c => c.Player.Id == "te1").WaitBonus!.Value;

        Assert.InRange(Bonus(new WaitSettings(1)), 34.9, 35.1);
        Assert.InRange(Bonus(new WaitSettings(1, Horizon: 2)), 69.9, 70.1);
        Assert.InRange(Bonus(new WaitSettings(1, Horizon: 3)), 104.9, 105.1);
        Assert.InRange(Bonus(new WaitSettings(1, Horizon: 2, HorizonDecay: 0.5)), 52.4, 52.6);          // 35 + 0.5 x 35
        Assert.InRange(Bonus(new WaitSettings(2, Horizon: 2)), 139.8, 140.2);
    }

    [Fact]
    public void The_bonus_can_be_limited_to_some_rounds_and_positions()
    {
        var state = new DraftState([V("te1", Position.TE, 90, 1), V("te2", Position.TE, 55, 30), V("wr", Position.WR, 150, 2)], Small);
        var reach = new ReachSettings(0, 100);

        WaitSettings Settings(IReadOnlyList<int>? rounds = null, IReadOnlyList<Position>? positions = null) => new(1, ActiveRounds: rounds, ActivePositions: positions);
        double Bonus(WaitSettings wait, string id) => ValueRecommender.Rank(state, reach, wait: wait).Single(c => c.Player.Id == id).WaitBonus!.Value;

        Assert.InRange(Bonus(Settings(), "te1"), 34.9, 35.1);
        Assert.InRange(Bonus(Settings(rounds: [1, 2]), "te1"), 34.9, 35.1);            // round 1 is in the list
        Assert.Equal(0, Bonus(Settings(rounds: [2, 3]), "te1"));                         // the draft is in round 1
        Assert.InRange(Bonus(Settings(positions: [Position.TE]), "te1"), 34.9, 35.1);
        Assert.Equal(0, Bonus(Settings(positions: [Position.WR, Position.RB]), "te1"));
        Assert.True(Bonus(Settings(positions: [Position.WR]), "wr") > 0);                // the other position still gets it
        Assert.True(Settings().AppliesTo(7, Position.QB));
        Assert.False(Settings(rounds: [1]).AppliesTo(2, Position.QB));
    }

    [Fact]
    public void Mean_and_sd_are_the_population_statistics()
    {
        Assert.Equal((0.0, 0.0), ValueRecommender.MeanAndSd([]));
        var (mean, sd) = ValueRecommender.MeanAndSd([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]);
        Assert.Equal(5.0, mean);
        Assert.Equal(2.0, sd, 9);
    }

    [Fact]
    public void Standardizing_makes_the_weight_a_unit_free_mix_of_value_and_shortfall()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var state = new DraftState(pool, new LeagueSettings());
        var reach = ValueRecommender.DefaultReach;
        var oneStep = ValueRecommender.Rank(state, reach, NeedSettings.Default).ToDictionary(c => c.Player.Id, c => c.Score);

        var zero = ValueRecommender.Rank(state, reach, NeedSettings.Default, wait: new WaitSettings(1e-12, Standardize: true));
        var mix = ValueRecommender.Rank(state, reach, NeedSettings.Default, wait: new WaitSettings(1, Standardize: true, StandardizePool: 10));

        // a vanishing weight leaves the one-step scores (mean + sd x z_value is the score itself)
        Assert.All(zero, c => Assert.Equal(oneStep[c.Player.Id], c.Score, 6));
        // only the pool is re-scored, and the mixed scores stay on the one-step scale: same mean over the pool when the shortfalls are standardized
        var inPool = mix.Where(c => c.WaitBonus != 0).ToList();
        Assert.InRange(inPool.Count, 1, 10);
        Assert.Equal(inPool.Average(c => oneStep[c.Player.Id]), inPool.Average(c => c.Score), 6);
        Assert.All(mix.Where(c => !inPool.Contains(c)), c => Assert.Equal(oneStep[c.Player.Id], c.Score, 6));
    }

    [Fact]
    public void The_standardized_sweep_and_the_scale_diagnostic_report()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };
        var settings = new SimSettings(new LeagueSettings(), StrategyFollowsRules: false);

        var sweep = ReachTuning.ReportStandardized(files, settings, seeds: 1);
        var scales = ScaleDiagnostics.Report(files, settings, seeds: 1);

        foreach (var expected in new[] { "z-mix w=0.25", "z-mix w=4", "need+wait (adopted)", "held-out gain over need+wait (adopted)" }) Assert.Contains(expected, sweep);
        foreach (var expected in new[] { "sd value", "sd shortfall", "ratio v/s", "corr", "all" }) Assert.Contains(expected, scales);
    }

    [Fact]
    public void The_scarce_position_sweep_reports_the_rb_te_arms()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportScarce(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "RB+TE w=2", "RB+TE w=8", "need+wait (adopted)", "held-out gain over need+wait (adopted)" }) Assert.Contains(expected, text);
    }

    [Fact]
    public void The_where_sweep_reports_round_blocks_and_positions_switched_on_and_off()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportWhere(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "rd 1-4 only", "all but rd 5-9", "rd 10-16 only", "QB only", "all but TE", "need+wait (adopted)" }) Assert.Contains(expected, text);
    }

    [Fact]
    public void The_horizon_sweep_reports_the_arms_and_the_adopted_reference()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportHorizon(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "h=1 w=4", "h=3 w=0.5", "h=3 d=0.5 w=2", "need+wait (adopted)", "held-out gain over need+wait (adopted)" }) Assert.Contains(expected, text);
    }

    [Fact]
    public void A_smaller_spread_scale_makes_survival_sharper_on_both_sides_of_the_pick()
    {
        var reach = new ReachSettings(1000, 4);
        var before = Player("slid", Position.WR, 100, adp: 48);          // 12 picks before my next pick: probably gone
        var after = Player("late", Position.WR, 100, adp: 72);           // 12 picks after it: probably there

        Assert.True(WaitSettings.Survival(before, 60, reach, 0.5) < WaitSettings.Survival(before, 60, reach));
        Assert.True(WaitSettings.Survival(after, 60, reach, 0.5) > WaitSettings.Survival(after, 60, reach));
        Assert.Equal(WaitSettings.Survival(after, 60, reach), WaitSettings.Survival(after, 60, reach, 1.0));
    }

    [Fact]
    public void The_reach_and_waiting_sweep_crosses_the_reach_cost_with_the_weight_and_includes_no_waiting()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportReachWait(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "l=100 w=0", "l=3000 w=4", "l=1000 w=2", "held-out gain over need" }) Assert.Contains(expected, text);
    }

    [Fact]
    public void The_survival_calibration_report_compares_the_scales_and_shows_reliability()
    {
        var files = new Dictionary<int, ProjectionFile> { [2024] = BacktestFile(2024) };

        var text = SurvivalCalibration.Report(files, new SimSettings(new LeagueSettings()), seeds: 1,
            new ValueRecommenderStrategy("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait),
            ReachSettings.Default, [0.5, 1.0]);

        foreach (var expected in new[] { "log-loss", "Brier", "reliability of normal x1", "predicted", "observed", "rounds 1-3" }) Assert.Contains(expected, text);
    }

    [Fact]
    public void The_survival_calibration_report_scores_simulated_survival_next_to_the_normal_scales()
    {
        var files = new Dictionary<int, ProjectionFile> { [2024] = BacktestFile(2024) };

        var text = SurvivalCalibration.Report(files, new SimSettings(new LeagueSettings()), seeds: 1,
            new ValueRecommenderStrategy("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait),
            ReachSettings.Default, [1.0], [("simulated, rules", new OpponentModel()), ("simulated, no rules", OpponentModel.NoRules)], samples: 5);

        foreach (var expected in new[] { "normal x1", "simulated, rules", "simulated, no rules" }) Assert.Contains(expected, text);
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
    public void An_alternative_far_past_his_ADP_at_my_next_pick_only_counts_when_alternatives_need_not_be_reachable()
    {
        // 4 teams: I pick 1st and 8th. "far" is certain to last to pick 8 but is ADP 60, 16 spreads past it: the recommender would never take him there
        var league = new LeagueSettings(Teams: 4, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);
        ValuedPlayer V(string id, Position position, double projected, double adp) => new(Player(id, position, projected, adp: adp), projected - 100, 0, 0, false, 1, 0, 1, 50);
        var pool = new List<ValuedPlayer> { V("star", Position.RB, 250, 2), V("far", Position.RB, 240, 60), V("near", Position.RB, 160, 9) };
        pool.AddRange(Enumerable.Range(1, 30).Select(i => V($"f{i}", Position.WR, 100, 100 + i)));
        var state = new DraftState(pool, league);
        var reach = ValueRecommender.DefaultReach;

        double Bonus(AlternativeReach reachable) => ValueRecommender.Rank(state, reach, NeedSettings.Default, 0, new WaitSettings(4, Reachable: reachable))
            .Single(c => c.Player.Id == "star").WaitBonus!.Value;

        var any = Bonus(AlternativeReach.Any);
        var cap = Bonus(AlternativeReach.WithinCap);
        var cost = Bonus(AlternativeReach.AfterReachCost);

        Assert.True(cap > any);                      // "far" no longer props up the alternatives
        Assert.True(cost >= cap);                    // and the reach cost can only make the remaining alternatives look worse
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
        Assert.Equal("far", Star(new WaitSettings(4, Reachable: AlternativeReach.Any)).WaitFallback!.Player.Id);

        var alone = new DraftState([V("star", Position.RB, 250, 2), .. Fillers()], league);
        var onlyHim = ValueRecommender.Rank(alone, reach, NeedSettings.Default, 0, ValueRecommender.DefaultWait).Single(c => c.Player.Id == "star");
        Assert.True(onlyHim.WaitBonus > 0);
        Assert.Null(onlyHim.WaitFallback);
        Assert.All(ValueRecommender.Rank(state, reach, NeedSettings.Default, 0), c => Assert.Null(c.WaitFallback));
    }

    static List<ValuedPlayer> RealisticValued() => Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
}
