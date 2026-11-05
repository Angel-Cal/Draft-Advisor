// Tests of archived experiments and removed Core options, cut from the live test files (they test archive/csharp code and do not compile against the current Core).
namespace DraftBot.Tests;

public class RemovedTests
{
    // from ReachTests.cs
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

    // from WaitTests.cs
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

    // from WaitTests.cs
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

    // from WaitTests.cs
    [Fact]
    public void The_wait_sweep_reports_the_weight_arms_and_the_need_control()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportWait(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "wait w=0.1", "wait w=2", "need", "adp", "held-out gain over need" }) Assert.Contains(expected, text);
    }

    // from WaitTests.cs
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

    // from WaitTests.cs
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

    // from WaitTests.cs
    [Fact]
    public void Mean_and_sd_are_the_population_statistics()
    {
        Assert.Equal((0.0, 0.0), ValueRecommender.MeanAndSd([]));
        var (mean, sd) = ValueRecommender.MeanAndSd([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]);
        Assert.Equal(5.0, mean);
        Assert.Equal(2.0, sd, 9);
    }

    // from WaitTests.cs
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

    // from WaitTests.cs
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

    // from WaitTests.cs
    [Fact]
    public void The_scarce_position_sweep_reports_the_rb_te_arms()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportScarce(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "RB+TE w=2", "RB+TE w=8", "need+wait (adopted)", "held-out gain over need+wait (adopted)" }) Assert.Contains(expected, text);
    }

    // from WaitTests.cs
    [Fact]
    public void The_where_sweep_reports_round_blocks_and_positions_switched_on_and_off()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportWhere(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "rd 1-4 only", "all but rd 5-9", "rd 10-16 only", "QB only", "all but TE", "need+wait (adopted)" }) Assert.Contains(expected, text);
    }

    // from WaitTests.cs
    [Fact]
    public void The_horizon_sweep_reports_the_arms_and_the_adopted_reference()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportHorizon(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "h=1 w=4", "h=3 w=0.5", "h=3 d=0.5 w=2", "need+wait (adopted)", "held-out gain over need+wait (adopted)" }) Assert.Contains(expected, text);
    }

    // from WaitTests.cs
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

    // from WaitTests.cs
    [Fact]
    public void The_reach_and_waiting_sweep_crosses_the_reach_cost_with_the_weight_and_includes_no_waiting()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportReachWait(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "l=100 w=0", "l=3000 w=4", "l=1000 w=2", "held-out gain over need" }) Assert.Contains(expected, text);
    }

    // from WaitTests.cs
    [Fact]
    public void The_survival_calibration_report_compares_the_scales_and_shows_reliability()
    {
        var files = new Dictionary<int, ProjectionFile> { [2024] = BacktestFile(2024) };

        var text = SurvivalCalibration.Report(files, new SimSettings(new LeagueSettings()), seeds: 1,
            new ValueRecommenderStrategy("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait),
            ReachSettings.Windowed, [0.5, 1.0]);

        foreach (var expected in new[] { "log-loss", "Brier", "reliability of normal x1", "predicted", "observed", "rounds 1-3" }) Assert.Contains(expected, text);
    }

    // from WaitTests.cs
    [Fact]
    public void The_survival_calibration_report_scores_simulated_survival_next_to_the_normal_scales()
    {
        var files = new Dictionary<int, ProjectionFile> { [2024] = BacktestFile(2024) };

        var text = SurvivalCalibration.Report(files, new SimSettings(new LeagueSettings()), seeds: 1,
            new ValueRecommenderStrategy("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait),
            ReachSettings.Windowed, [1.0], [("simulated, rules", new OpponentModel()), ("simulated, no rules", OpponentModel.NoRules)], samples: 5);

        foreach (var expected in new[] { "normal x1", "simulated, rules", "simulated, no rules" }) Assert.Contains(expected, text);
    }

    // from WaitTests.cs
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

    // from NeedTests.cs
    [Fact]
    public void The_need_sweep_reports_the_bench_fraction_arms_and_the_value_control()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportNeed(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "need b=0 l=1000", "need b=1 l=400", "value", "adp", "held-out gain over value" }) Assert.Contains(expected, text);
    }

    // from SimulatorTests.cs
    [Fact]
    public void The_slot_choice_check_scores_each_slots_best_arm_on_the_held_out_season()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024), [2025] = BacktestFile(2025) };
        IDraftStrategy[] strategies = [new AdpStrategy(), new VorStrategy()];
        var rows = Experiment.Run(files, Settings, strategies, noiseScales: [1.0], seeds: 2).Rows;

        var report = Experiment.SlotChoiceCheck(rows, ["vor"], baseline: "adp");
        var onlyBaseline = Experiment.SlotChoiceCheck(rows, [], baseline: "adp");

        Assert.Contains("gain over adp", report);
        Assert.Contains("2025:", report);
        Assert.Contains("0.0 +/- 0.0", onlyBaseline);          // choosing among the baseline alone changes nothing
    }
    // from TuningAndRegretTests.cs
    [Fact]
    public void Adjusted_r2_charges_for_the_number_of_groups()
    {
        // groups {10,12} and {2,4}: within = 4, total = 68, n = 4, g = 2 -> 1 - (4/2) / (68/3)
        var score = TierTuning.AdjustedR2([0, 0, 1, 1], [10, 12, 2, 4]);

        Assert.Equal(1 - 2.0 / (68.0 / 3), score!.Value, 9);
    }

    // from TuningAndRegretTests.cs
    [Fact]
    public void Adjusted_r2_is_undefined_without_variance_or_when_every_player_has_a_tier()
    {
        Assert.Null(TierTuning.AdjustedR2([0, 0, 1, 1], [5, 5, 5, 5]));
        Assert.Null(TierTuning.AdjustedR2([0, 1, 2, 3], [1, 2, 3, 4]));
    }

    // from TuningAndRegretTests.cs
    [Fact]
    public void Gap_tiers_are_compared_with_equal_size_tiers_of_the_same_count()
    {
        // projections 300, 250, 240, 100 with threshold 0.3 x 100: tiers {300} {250,240} {100}; actuals 10, 6, 8, 1
        var projections = new[] { 300.0, 250, 240, 100 };
        var actuals = new[] { 10.0, 6, 8, 1 };
        var players = projections.Select((p, i) => Player($"WR{i}", Position.WR, p, actual: actuals[i])).ToList();

        var result = TierTuning.ScorePosition(players, Rmse, Position.WR, gapRmse: 0.3)!.Value;

        Assert.Equal(3, result.Tiers);
        Assert.Equal(1 - 2.0 / (44.75 / 3), result.AdjustedR2, 9);          // gap tiers: within = 0 + 2 + 0
        Assert.Equal(1 - 8.0 / (44.75 / 3), result.QuantileR2, 9);          // equal-size tiers {10,6} {8} {1}: within = 8
        Assert.Equal(2, result.Largest);
    }
    // from ValueRecommenderTests.cs
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
