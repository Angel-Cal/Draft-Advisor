using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class RecommenderTests
{
    // 2 teams, one starter at each position, no FLEX, 2 bench spots (6 rounds)
    static readonly LeagueSettings Small = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 2);

    static DraftState State(LeagueSettings league, IEnumerable<ValuedPlayer> pool) => new(pool, league);

    /// <summary>Players of one position, all in the given tier, with distinct ids.</summary>
    static IEnumerable<ValuedPlayer> InTier(Position position, int tier, int count, string prefix, bool injury = false) =>
        Enumerable.Range(0, count).Select(i => Valued($"{prefix}{position}{tier}-{i}", position, tier: tier, injury: injury));

    // ---- position selection -----------------------------------------------------------------------------------

    [Fact]
    public void The_position_with_the_fewest_players_left_in_its_best_tier_is_most_scarce()
    {
        // every position has 2 starters' worth of demand (2 empty teams x 1 slot); TE has one player in tier 1
        var pool = InTier(Position.QB, 1, 2, "a").Concat(InTier(Position.RB, 1, 2, "a"))
            .Concat(InTier(Position.WR, 1, 2, "a")).Concat(InTier(Position.TE, 1, 1, "a")).Concat(InTier(Position.TE, 2, 3, "a"));
        var state = State(Small, pool);

        Assert.Equal(1.0, BaselineRecommender.Scarcity(state, Position.QB));
        Assert.Equal(2.0, BaselineRecommender.Scarcity(state, Position.TE));
        Assert.Equal(Position.TE, BaselineRecommender.SelectPosition(state, 0));
    }

    [Fact]
    public void Equal_scarcity_goes_to_the_first_position_in_qb_rb_wr_te_order()
    {
        var pool = Positions.All.SelectMany(p => InTier(p, 1, 2, "a"));

        Assert.Equal(Position.QB, BaselineRecommender.SelectPosition(State(Small, pool), 0));
    }

    [Fact]
    public void A_single_unmet_need_decides_the_position()
    {
        var pool = Positions.All.SelectMany(p => InTier(p, 1, 3, "a")).ToList();
        var state = State(Small, pool);
        state.Teams[0].Add(Valued("my-qb", Position.QB));
        state.Teams[0].Add(Valued("my-rb", Position.RB));
        state.Teams[0].Add(Valued("my-wr", Position.WR));

        Assert.Equal(Position.TE, BaselineRecommender.SelectPosition(state, 0));
    }

    [Fact]
    public void A_flex_need_opens_rb_wr_and_te_even_where_the_starter_slots_are_full()
    {
        var league = new LeagueSettings(Teams: 2, Qb: 1, Rb: 2, Wr: 1, Te: 1, Flex: 1, Bench: 0);
        // team 0 holds two RBs, so its needs are QB, WR, TE and FLEX; RB has one player in its best tier, so RB wins
        var pool = InTier(Position.QB, 1, 2, "a").Concat(InTier(Position.RB, 1, 1, "a")).Concat(InTier(Position.RB, 2, 4, "a"))
            .Concat(InTier(Position.WR, 1, 2, "a")).Concat(InTier(Position.TE, 1, 2, "a"));
        var state = State(league, pool);
        state.Teams[0].Add(Valued("my-rb1", Position.RB));
        state.Teams[0].Add(Valued("my-rb2", Position.RB));

        Assert.Equal(Position.RB, BaselineRecommender.SelectPosition(state, 0));
    }

    [Fact]
    public void With_no_starter_needs_two_injury_flagged_players_at_a_position_boost_its_scarcity()
    {
        // team 0 starts everyone and has a second RB. Scarcity is 0.5 everywhere (1 empty-slot team / 2 in the best tier)
        static DraftState Build(bool flagged)
        {
            var pool = Positions.All.SelectMany(p => InTier(p, 1, 2, "a")).ToList();
            var state = State(Small, pool);
            foreach (var position in Positions.All) state.Teams[0].Add(Valued($"my-{position}", position, injury: flagged && position == Position.RB));
            state.Teams[0].Add(Valued("my-rb-2", Position.RB, injury: flagged));
            return state;
        }

        Assert.Equal(Position.QB, BaselineRecommender.SelectPosition(Build(flagged: false), 0));
        Assert.Equal(Position.RB, BaselineRecommender.SelectPosition(Build(flagged: true), 0));
    }

    // ---- player selection -------------------------------------------------------------------------------------

    [Fact]
    public void Candidates_are_ranked_by_half_vor_rank_and_half_value_gap_scaled_within_the_position()
    {
        // vor rank 1,2,3 -> scaled 1, .5, 0 ; value gap 0,10,4 -> scaled 0, 1, .4
        var pool = new[]
        {
            Valued("A", Position.WR, vorRank: 1, valueGap: 0), Valued("B", Position.WR, vorRank: 2, valueGap: 10),
            Valued("C", Position.WR, vorRank: 3, valueGap: 4),
        };
        var candidates = BaselineRecommender.SelectPlayers(Position.WR, State(Small, pool), 0);

        Assert.Equal(["B", "A", "C"], candidates.Select(c => c.Player.Id));
        Assert.Equal([0.75, 0.5, 0.2], candidates.Select(c => c.WeightedValue).ToArray(), new ApproxComparer());
    }

    [Fact]
    public void Only_the_top_five_candidates_are_returned_and_ties_keep_pool_order()
    {
        var pool = Enumerable.Range(0, 8).Select(i => Valued($"p{i}", Position.RB, vorRank: 1, valueGap: 0)).ToList();

        var candidates = BaselineRecommender.SelectPlayers(Position.RB, State(Small, pool), 0);

        Assert.Equal(["p0", "p1", "p2", "p3", "p4"], candidates.Select(c => c.Player.Id));
        Assert.All(candidates, c => Assert.Equal(0, c.WeightedValue));     // identical ranges scale to 0, never NaN
    }

    [Fact]
    public void An_empty_position_yields_no_candidates_and_zero_scarcity()
    {
        var state = State(Small, InTier(Position.WR, 1, 2, "a"));

        Assert.Empty(BaselineRecommender.SelectPlayers(Position.QB, state, 0));
        Assert.Equal(0, BaselineRecommender.Scarcity(state, Position.QB));
    }

    [Fact]
    public void Injury_flagged_candidates_are_penalized_in_proportion_to_flagged_players_already_rostered()
    {
        // round 1 of 6, one flagged RB already on the roster: penalty = 0.5 x 1 x (1 - 1/6)
        var pool = new[]
        {
            Valued("healthy", Position.RB, vorRank: 1, valueGap: 10),
            Valued("fragile", Position.RB, vorRank: 2, valueGap: 0, injury: true),
        };
        var state = State(Small, pool);
        state.Teams[0].Add(Valued("my-flagged-rb", Position.RB, injury: true));

        var expected = 0.5 * 1 * (1 - 1.0 / 6);
        Assert.Equal(expected, BaselineRecommender.RiskPenalty(Position.RB, state, 0), 12);
        Assert.Equal(0, BaselineRecommender.RiskPenalty(Position.QB, state, 0));

        var candidates = BaselineRecommender.SelectPlayers(Position.RB, state, 0).ToDictionary(c => c.Player.Id);
        Assert.Equal(1.0, candidates["healthy"].WeightedValue, 12);
        Assert.Equal(0.0 - expected, candidates["fragile"].WeightedValue, 12);
    }

    [Fact]
    public void Recommend_combines_the_chosen_position_with_its_candidates()
    {
        var pool = Positions.All.SelectMany(p => InTier(p, 1, 2, "a")).Concat(InTier(Position.TE, 2, 2, "b"));
        var state = State(Small, pool);

        var recommendation = BaselineRecommender.Recommend(state, 0);

        Assert.Equal(Position.QB, recommendation.Position);       // every position has demand 2 and 2 players in its best tier: a tie, so QB comes first
    }

    sealed class ApproxComparer : IEqualityComparer<double>
    {
        public bool Equals(double x, double y) => Math.Abs(x - y) < 1e-9;
        public int GetHashCode(double value) => 0;
    }
}
