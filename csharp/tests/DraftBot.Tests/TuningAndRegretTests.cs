using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class TierTuningTests
{
    [Fact]
    public void Adjusted_r2_charges_for_the_number_of_groups()
    {
        // groups {10,12} and {2,4}: within = 4, total = 68, n = 4, g = 2 -> 1 - (4/2) / (68/3)
        var score = TierTuning.AdjustedR2([0, 0, 1, 1], [10, 12, 2, 4]);

        Assert.Equal(1 - 2.0 / (68.0 / 3), score!.Value, 9);
    }

    [Fact]
    public void Adjusted_r2_is_undefined_without_variance_or_when_every_player_has_a_tier()
    {
        Assert.Null(TierTuning.AdjustedR2([0, 0, 1, 1], [5, 5, 5, 5]));
        Assert.Null(TierTuning.AdjustedR2([0, 1, 2, 3], [1, 2, 3, 4]));
    }

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
}

public class RegretTests
{
    static readonly LeagueSettings OneTeam = new(Teams: 1, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 0);

    static ValuedPlayer V(string id, Position position, double actual, double vor) =>
        new(Player(id, position, 100 + vor, actual: actual), vor, 0, 0, false, 1, 0, 1);

    static List<ValuedPlayer> Pool() =>
    [
        V("a", Position.WR, 100, vor: 50), V("b", Position.WR, 80, vor: 30), V("c", Position.WR, 50, vor: 0),
        V("x", Position.RB, 90, vor: 40), V("y", Position.RB, 60, vor: 10),
        V("q1", Position.QB, 300, vor: 70), V("q2", Position.QB, 250, vor: 20),
        V("t1", Position.TE, 70, vor: 15), V("t2", Position.TE, 40, vor: 5),
    ];

    [Fact]
    public void Regret_is_measured_against_the_best_legal_player_three_ways()
    {
        var pool = Pool();
        var calculator = new RegretCalculator(pool, OneTeam);
        var legal = pool.Where(p => p.Id is "a" or "b" or "x").ToList();
        var chosen = pool.Single(p => p.Id == "b");

        var regret = calculator.Evaluate(legal, chosen, round: 3);

        // replacement in actual points (1 team, 1 slot): WR 80, RB 60, so over replacement a = 20, b = 0, x = 30
        Assert.Equal(3, regret.Round);
        Assert.Equal(100 - 80, regret.Actual);
        Assert.Equal(30 - 0, regret.ActualVorAdjusted);
        Assert.Equal(50 - 30, regret.ProjectedVor);
    }

    [Fact]
    public void Taking_the_best_option_has_zero_regret()
    {
        var pool = Pool();
        var calculator = new RegretCalculator(pool, OneTeam);
        var legal = pool.Where(p => p.Position == Position.WR).ToList();

        var regret = calculator.Evaluate(legal, pool.Single(p => p.Id == "a"), 1);

        Assert.Equal((0, 0, 0), (regret.Actual, regret.ActualVorAdjusted, regret.ProjectedVor));
    }

    [Fact]
    public void Regret_needs_actual_points()
    {
        var pool = new List<ValuedPlayer> { Valued("p", Position.WR) };
        Assert.Throws<InvalidOperationException>(() => new RegretCalculator(pool, OneTeam));
    }

    [Fact]
    public void A_vor_drafter_has_no_foresight_regret_and_nobody_has_negative_regret()
    {
        var file = new ProjectionFile("v1", "backtest", 2024, "fantasypros", Rmse,
            RealisticPool().Select((p, i) => p with { ActualPpr = p.ProjectedPpr * (0.6 + 0.8 * ((i * 37) % 11) / 10.0) }).ToList());
        var pool = Valuator.Value(file.Players, file.PositionRmse, new LeagueSettings());
        var calculator = new RegretCalculator(pool, new LeagueSettings());

        var vor = DraftSimulator.Run(pool, new SimSettings(new LeagueSettings()), 3, new VorStrategy(), seed: 1, calculator);
        var adp = DraftSimulator.Run(pool, new SimSettings(new LeagueSettings()), 3, new AdpStrategy(), seed: 1, calculator);

        Assert.Equal(16, vor.Regrets.Count);
        Assert.Equal([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], vor.Regrets.Select(r => r.Round));
        Assert.All(vor.Regrets, r => Assert.Equal(0, r.ProjectedVor, 9));
        Assert.All(vor.Regrets.Concat(adp.Regrets), r => Assert.True(r.Actual >= 0 && r.ActualVorAdjusted >= 0 && r.ProjectedVor >= -1e-9));
        Assert.Contains(adp.Regrets, r => r.ProjectedVor > 0);
    }
}
