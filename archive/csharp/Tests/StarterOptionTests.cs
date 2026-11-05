using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class StarterOptionTests
{
    // 2 teams, 1 starter each at QB/RB/WR/TE and one FLEX; replacement points: QB 200, RB 100, WR 100, TE 50
    static readonly LeagueSettings Small = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 3);
    static readonly Dictionary<Position, double> Replacement = new()
        { [Position.QB] = 200, [Position.RB] = 100, [Position.WR] = 100, [Position.TE] = 50 };

    static ValuedPlayer V(string id, Position position, double projected, double adp = 1, double rmse = 50) =>
        new(Player(id, position, projected, adp: adp), projected - Replacement[position], 0, 0, false, 1, 0, 1, rmse);

    [Fact]
    public void The_option_premium_is_largest_next_to_the_waiver_level_and_vanishes_far_above_it()
    {
        Assert.Equal(0, NeedSettings.OptionPremium(150, 0, 100));                                     // no spread, no option
        Assert.Equal(50 / Math.Sqrt(2 * Math.PI), NeedSettings.OptionPremium(100, 50, 100), 3);       // at the waiver level: sd x pdf(0)
        Assert.InRange(NeedSettings.OptionPremium(320, 50, 200), 0, 0.5);                             // far above: he is simply a starter
        Assert.True(NeedSettings.OptionPremium(120, 50, 100) > NeedSettings.OptionPremium(200, 50, 100));
        Assert.True(NeedSettings.OptionPremium(120, 80, 100) > NeedSettings.OptionPremium(120, 40, 100));
        Assert.All(new[] { 0.0, 60, 100, 140, 400 }, projection => Assert.True(NeedSettings.OptionPremium(projection, 50, 100) >= 0));
    }

    [Fact]
    public void A_starter_near_the_waiver_level_gains_a_premium_and_a_clear_starter_does_not()
    {
        var state = new DraftState([V("wr", Position.WR, 120), V("qb", Position.QB, 320)], Small);
        var reach = new ReachSettings(0, 100);

        var plain = ValueRecommender.Rank(state, reach, NeedSettings.Option).ToDictionary(c => c.Player.Id);
        var option = ValueRecommender.Rank(state, reach, NeedSettings.WithStarterOption(1)).ToDictionary(c => c.Player.Id);

        Assert.All(plain.Values, c => Assert.Null(c.StarterPremium));
        Assert.InRange(option["wr"].StarterPremium!.Value, 11.4, 11.6);                    // E[max(X, 100)] - 120 for X ~ N(120, 50)
        Assert.InRange(option["qb"].StarterPremium!.Value, 0, 0.5);
        Assert.Equal(plain["wr"].Score + option["wr"].StarterPremium!.Value, option["wr"].Score, 9);
        Assert.Equal(option["wr"].BaseValue, option["wr"].Gain!.Value + option["wr"].BenchValue!.Value + option["wr"].StarterPremium!.Value, 9);
    }

    [Fact]
    public void A_player_who_would_not_start_gets_no_starter_premium()
    {
        // the second WR cannot beat the 300s already holding the WR and FLEX slots; bench value covers him instead
        var state = new DraftState([V("wr2", Position.WR, 120)], Small);
        state.Teams[0].Add(V("wr1", Position.WR, 300));
        state.Teams[0].Add(V("rb1", Position.RB, 300));
        state.Teams[0].Add(V("rb2", Position.RB, 300));      // FLEX already holds a 300

        var candidate = ValueRecommender.Rank(state, new ReachSettings(0, 100), NeedSettings.WithStarterOption(1)).Single();

        Assert.Equal(0, candidate.Gain);
        Assert.Null(candidate.StarterPremium);              // not a starter: bench value covers him
    }

    [Fact]
    public void The_starter_sweep_reports_the_weight_arms_the_combination_and_the_need_control()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportStarter(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "starter w=0.5", "starter w=4", "starter w=1 + wait w=2", "need", "adp", "held-out gain over need" }) Assert.Contains(expected, text);
    }

    [Fact]
    public void Sweep_metrics_parse_and_select_the_right_column()
    {
        var row = new RunRow(2024, 1, 0, 0, "x", Points: 2100, Finish: 3, WinPct: 0.55, Playoff: 0.6, Title: 0.12);

        Assert.Equal(SweepMetric.Title, SweepMetrics.Parse("TITLE"));
        Assert.Equal(SweepMetric.Points, SweepMetrics.Parse(null));
        Assert.Equal(2100, SweepMetric.Points.Selector()(row));
        Assert.Equal(55, SweepMetric.Wins.Selector()(row), 9);
        Assert.Equal(60, SweepMetric.Playoffs.Selector()(row), 9);
        Assert.Equal(12, SweepMetric.Title.Selector()(row), 9);
        Assert.Throws<ArgumentException>(() => SweepMetrics.Parse("goals"));
    }
}
