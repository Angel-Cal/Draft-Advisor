using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class ValuationTests
{
    static readonly LeagueSettings TwoTeams = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 0);
    static readonly LeagueSettings OneTeam = new(Teams: 1, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 0);

    static List<Player> SmallPool()
    {
        var pool = new List<Player>();
        pool.AddRange(new[] { 300.0, 250, 200 }.Select((v, i) => Player($"QB{i}", Position.QB, v, adp: 100 + i)));
        pool.AddRange(new[] { 100.0, 90, 80, 70, 60, 50 }.Select((v, i) => Player($"RB{i}", Position.RB, v, adp: 10 + i)));
        pool.AddRange(new[] { 95.0, 85, 75, 65, 55 }.Select((v, i) => Player($"WR{i}", Position.WR, v, adp: 20 + i)));
        pool.AddRange(new[] { 50.0, 40, 30 }.Select((v, i) => Player($"TE{i}", Position.TE, v, adp: 50 + i)));
        return pool;
    }

    [Fact]
    public void Flex_slots_go_to_the_best_remaining_rb_wr_or_te()
    {
        // 2 teams: dedicated starters are 2 per position; the 2 FLEX slots go to RB 80 and WR 75
        var counts = ReplacementLevel.StarterCounts(SmallPool(), TwoTeams);

        Assert.Equal(new Dictionary<Position, int>
            { [Position.QB] = 2, [Position.RB] = 3, [Position.WR] = 3, [Position.TE] = 2 }, counts);
        var points = ReplacementLevel.Points(SmallPool(), TwoTeams);
        Assert.Equal(200, points[Position.QB]);
        Assert.Equal(70, points[Position.RB]);
        Assert.Equal(65, points[Position.WR]);
        Assert.Equal(30, points[Position.TE]);
    }

    [Fact]
    public void Replacement_follows_the_league_settings()
    {
        var pool = RealisticPool();
        var twelve = ReplacementLevel.StarterCounts(pool, new LeagueSettings());
        var ten = ReplacementLevel.StarterCounts(pool, new LeagueSettings(Teams: 10));

        Assert.Equal(12 * (1 + 2 + 3 + 1 + 1), twelve.Values.Sum());       // every league starter is counted once
        Assert.Equal(10 * (1 + 2 + 3 + 1 + 1), ten.Values.Sum());
        Assert.Equal(12, twelve[Position.QB]);
        Assert.Equal(12, twelve[Position.TE]);
        Assert.True(twelve[Position.RB] >= 24 && twelve[Position.WR] >= 36);
    }

    [Fact]
    public void Default_league_replacement_is_near_the_old_hardcoded_ranks()
    {
        // Python used QB 12, RB 29, WR 41, TE 12 (0-based): the first non-starter at each position
        var counts = ReplacementLevel.StarterCounts(RealisticPool(), new LeagueSettings());
        Assert.InRange(counts[Position.RB], 27, 33);
        Assert.InRange(counts[Position.WR], 39, 45);
    }

    [Fact]
    public void Vor_is_projection_minus_replacement_and_the_pool_is_ordered_by_it()
    {
        var valued = Valuator.Value(SmallPool(), Rmse, TwoTeams);

        Assert.Equal(valued.OrderByDescending(v => v.Vor).Select(v => v.Id), valued.Select(v => v.Id));
        Assert.Equal(100 - 70, valued.Single(v => v.Id == "RB0").Vor);
        Assert.Equal(300 - 200, valued.Single(v => v.Id == "QB0").Vor);
        Assert.Equal(50 - 70, valued.Single(v => v.Id == "RB5").Vor);          // below replacement is negative
    }

    [Fact]
    public void Vor_rank_ties_share_the_best_rank_and_value_gap_is_adp_minus_vor_rank()
    {
        var pool = new List<Player>
        {
            Player("QB0", Position.QB, 300, adp: 1), Player("QB1", Position.QB, 200, adp: 2),
            Player("RB0", Position.RB, 300, adp: 3), Player("RB1", Position.RB, 100, adp: 4),
            Player("WR0", Position.WR, 250, adp: 5), Player("WR1", Position.WR, 150, adp: 6),
            Player("TE0", Position.TE, 120, adp: 7), Player("TE1", Position.TE, 90, adp: null),
        };
        // one team, one slot each: replacement is the 2nd player -> QB 200, RB 100, WR 150, TE 90
        // VOR: RB0 200 | QB0 100, WR0 100 | TE0 30 | QB1, RB1, WR1, TE1 all 0
        var byId = Valuator.Value(pool, Rmse, OneTeam).ToDictionary(v => v.Id);

        Assert.Equal(1, byId["RB0"].VorRank);
        Assert.Equal(2, byId["QB0"].VorRank);
        Assert.Equal(2, byId["WR0"].VorRank);                  // tied with QB0
        Assert.Equal(4, byId["TE0"].VorRank);
        Assert.Equal(5, byId["TE1"].VorRank);

        Assert.Equal(3 - 1, byId["RB0"].ValueGap);
        Assert.Equal(1 - 2, byId["QB0"].ValueGap);
        Assert.Equal(7 - 4, byId["TE0"].ValueGap);
        Assert.Equal(8 - 5, byId["TE1"].ValueGap);             // no ADP: valued as one past the last ADP (7)
    }

    [Theory]
    [InlineData(16, 0, 100, 150, 50, false)]      // healthy: projection +/- RMSE (50)
    [InlineData(8, -7, 100, 200, 50, true)]       // missed time: 17/8 pace is 212.5, capped at 2 x projection
    [InlineData(12, -6, 100, 150, 50, true)]      // flagged, but 17/12 pace (141.7) is below the RMSE ceiling
    [InlineData(8, 0, 100, 150, 50, false)]       // few games but no big drop: not flagged
    [InlineData(16, 0, 30, 80, 0, false)]         // floor never goes below zero
    public void Ceiling_floor_and_availability(int games, int delta, double projected, double ceiling, double floor, bool flagged)
    {
        var result = Valuator.CeilingFloor(Player("p", Position.WR, projected, games: games, gamesDelta: delta), 50);

        Assert.Equal((ceiling, floor, flagged), result);
    }

    [Fact]
    public void Tiers_break_where_the_projection_drops_by_more_than_k_times_rmse()
    {
        var pool = new[] { 300.0, 290, 250, 245, 200 }.Select((v, i) => Player($"WR{i}", Position.WR, v)).ToList();
        pool.AddRange(new[] { 280.0, 275, 100 }.Select((v, i) => Player($"RB{i}", Position.RB, v)));

        var tiers = Valuator.Tiers(pool, Rmse, gapRmse: 0.2);      // threshold = 0.2 x 100 = 20 points

        Assert.Equal([1, 1, 2, 2, 3], Enumerable.Range(0, 5).Select(i => tiers[$"WR{i}"]));
        Assert.Equal([1, 1, 2], Enumerable.Range(0, 3).Select(i => tiers[$"RB{i}"]));      // tiers restart per position
    }

    [Fact]
    public void A_drop_exactly_at_the_threshold_stays_in_the_tier()
    {
        var pool = new[] { 300.0, 280, 260 }.Select((v, i) => Player($"WR{i}", Position.WR, v)).ToList();
        var tiers = Valuator.Tiers(pool, Rmse, gapRmse: 0.2);
        Assert.All(tiers.Values, tier => Assert.Equal(1, tier));
    }

    [Fact]
    public void Tier_threshold_scales_with_the_position_rmse()
    {
        var rmse = new Dictionary<Position, double> { [Position.QB] = 200, [Position.RB] = 50, [Position.WR] = 50, [Position.TE] = 50 };
        var pool = new[] { 300.0, 270 }.Select((v, i) => Player($"QB{i}", Position.QB, v)).ToList();
        pool.AddRange(new[] { 300.0, 270 }.Select((v, i) => Player($"RB{i}", Position.RB, v)));

        var tiers = Valuator.Tiers(pool, rmse, gapRmse: 0.2);       // QB threshold 40, RB threshold 10

        Assert.Equal(1, tiers["QB1"]);
        Assert.Equal(2, tiers["RB1"]);
    }
}
