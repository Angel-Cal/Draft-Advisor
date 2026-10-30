namespace DraftBot.Core;

/// <param name="RankTerm">Half-weighted VOR-rank component (1 = best VOR rank among the position's available players).</param>
/// <param name="GapTerm">Half-weighted ADP-minus-VOR-rank component (1 = largest gap, i.e. furthest below its ADP by VOR).</param>
/// <param name="Penalty">Injury-risk penalty subtracted from the score (0 unless the player is flagged).</param>
/// <param name="ReachPenalty">Windowed variant only: lambda x z^2 subtracted for taking the player past his ADP.</param>
/// <param name="ReachSigmas">Windowed variant only: z, how many standard deviations past the current pick his ADP is (0 if not a reach).</param>
public sealed record Candidate(ValuedPlayer Player, double WeightedValue, double RankTerm = 0, double GapTerm = 0, double Penalty = 0,
    double ReachPenalty = 0, double ReachSigmas = 0);

public sealed record Recommendation(Position Position, IReadOnlyList<Candidate> Candidates);

/// <param name="Demand">Starter slots still unfilled across all teams at this position.</param>
/// <param name="Supply">Available players at the position in its best remaining tier.</param>
/// <param name="Value">Demand / Supply, times 1.2 if boosted.</param>
/// <param name="Considered">Whether the team's needs allow this position to be chosen.</param>
/// <param name="InjuryBoost">Bench strategy only: 2+ injury-flagged players already rostered here.</param>
public sealed record PositionScarcity(Position Position, int Demand, int Supply, double Value, bool Considered, bool InjuryBoost);

public sealed record PositionChoice(Position Position, IReadOnlyList<Slot> Needs, IReadOnlyList<PositionScarcity> Scarcity);

/// <summary>
/// Optional ADP-reach control for the recommender. A player whose ADP is later than the current pick is a reach of
/// z = (ADP - pick) / sigma(pick) standard deviations, where sigma grows with the pick (ADP is less predictive later).
/// Taking him costs <paramref name="Lambda"/> x z^2 in score, so small reaches are nearly free and large ones cannot win; players
/// past <paramref name="CapSigmas"/> are removed from the pool entirely (both for choosing a position and a player).
/// </summary>
/// <param name="SigmaBase">Picks of spread at pick 0.</param>
/// <param name="SigmaPerPick">Extra spread per pick; the default is the measured cross-platform spread, about 0.16 x ADP.</param>
/// <param name="SurvivalPower">
/// Only <see cref="ValueRecommender.Rank"/> uses it: the cost is scaled by S^power, S = chance the player is still there at my next pick (1 with no next pick). 0 is the plain cost;
/// above 0, a reach of a player who is about to go costs less than a reach of one who would last anyway.
/// </param>
/// <param name="FreePicks">
/// Only <see cref="ValueRecommender.Rank"/> uses it: reaches up to this many picks cost nothing (on top of <paramref name="FreeSigmas"/>). The resolution of an ADP is a roughly constant number of picks, while a sigma grows with the pick,
/// so a free zone in picks is tight early (where a fraction of a pick should not decide a card) and does not widen into the late rounds. 0 is the plain cost.
/// </param>
/// <param name="FreeSigmas">
/// Only <see cref="ValueRecommender.Rank"/> uses it: reaches up to this many standard deviations cost nothing, and beyond it the cost is lambda x (z - free)^2. 0 is the plain cost.
/// ADP differences inside the market's own spread (a fraction of a pick at an early pick) then cannot decide a pick.
/// </param>
public sealed record ReachSettings(double Lambda, double CapSigmas, bool UseGapTerm = true, double SigmaBase = 2.0, double SigmaPerPick = 0.16,
    double SurvivalPower = 0, double FreeSigmas = 0, double FreePicks = 0)
{
    /// <summary>Provisional default from the Phase 2 follow-up sweep: the middle of a plateau of equally good settings.</summary>
    public static ReachSettings Default { get; } = new(Lambda: 0.3, CapSigmas: 4);

    public double Sigma(int pick) => SigmaBase + SigmaPerPick * pick;

    /// <summary>The reach the cost is charged on: <see cref="Reach"/> less the free zone (<see cref="FreeSigmas"/> sigmas plus <see cref="FreePicks"/> picks), never below 0.</summary>
    public double Charged(Player player, int pick)
    {
        var z = Reach(player, pick);
        return double.IsInfinity(z) ? z : Math.Max(0, z - FreeSigmas - FreePicks / Sigma(pick));
    }

    /// <summary>Reach in standard deviations; 0 for a player at or before the pick, infinity if he has no ADP.</summary>
    public double Reach(Player player, int pick) =>
        player.Adp is null ? double.PositiveInfinity : Math.Max(0, player.Adp.Value - pick) / Sigma(pick);
}

/// <summary>
/// The Phase 1 recommender ported as-is, so later versions are measured against it: pick the position with the most
/// unmet league demand per player left in its best tier, then rank that position's players by VOR rank and ADP gap.
/// Ties go to the first candidate in pool order (VOR, best first).
/// </summary>
public static class BaselineRecommender
{
    const int TopN = 5;

    /// <summary>Without <paramref name="reach"/> this is the ported Phase 1 recommender.</summary>
    public static Recommendation Recommend(DraftState state, int teamIndex, ReachSettings? reach = null)
    {
        var position = SelectPosition(state, teamIndex, reach);
        return new Recommendation(position, SelectPlayers(position, state, teamIndex, reach));
    }

    public static Position SelectPosition(DraftState state, int teamIndex, ReachSettings? reach = null) =>
        ChoosePosition(state, teamIndex, reach).Position;

    /// <summary>The pool the recommender may suggest from: everyone available, or those within the reach cap.</summary>
    public static IReadOnlyList<ValuedPlayer> RecommendablePool(DraftState state, ReachSettings? reach)
    {
        if (reach is null) return state.Available;
        var pick = state.OverallPick + 1;
        var window = state.Available.Where(p => reach.Reach(p.Player, pick) <= reach.CapSigmas).ToList();
        return window.Count > 0 ? window : state.Available;       // never leave the drafter with nothing
    }

    /// <summary>The position decision with the numbers behind it, for every position (even those not considered).</summary>
    public static PositionChoice ChoosePosition(DraftState state, int teamIndex, ReachSettings? reach = null)
    {
        var recommendable = RecommendablePool(state, reach);
        var roster = state.Teams[teamIndex];
        var (needs, _) = roster.GetNeeds();
        Position[] flexOrder = [Position.WR, Position.RB, Position.TE];

        // which positions may be chosen, in tie-break order
        List<Position> considered;
        if (needs.Count == 1 && needs[0] == Slot.Flex)
            considered = [.. flexOrder];
        else if (needs.Count == 1)
            considered = [Enum.Parse<Position>(needs[0].ToString())];
        else if (needs.Count > 1)
        {
            var wanted = needs.Where(n => n != Slot.Flex).Select(n => Enum.Parse<Position>(n.ToString())).ToHashSet();
            if (needs.Contains(Slot.Flex)) wanted.UnionWith(Positions.FlexEligible);
            considered = Positions.All.Where(wanted.Contains).ToList();
        }
        else
            considered = [.. Positions.All];       // no starter needs left: bench strategy

        if (reach is not null)      // a position with nobody inside the window cannot be chosen (unless that leaves nothing)
        {
            var inWindow = considered.Where(p => recommendable.Any(x => x.Position == p)).ToList();
            if (inWindow.Count == 0) inWindow = Positions.All.Where(p => recommendable.Any(x => x.Position == p)).ToList();
            if (inWindow.Count > 0) considered = inWindow;
        }

        // bench strategy boosts a position where 2+ drafted players carry the injury flag
        var benchStrategy = needs.Count == 0;
        var rows = Positions.All.Select(p =>
        {
            var boost = benchStrategy && roster.At(p).Count(x => x.Player.InjuryFlag) >= 2;
            var (demand, supply) = (Demand(state, p), Supply(recommendable, p));
            return new PositionScarcity(p, demand, supply, Ratio(demand, supply) * (boost ? 1.2 : 1.0), considered.Contains(p), boost);
        }).ToDictionary(r => r.Position);

        var best = considered[0];
        foreach (var position in considered)
            if (rows[position].Value > rows[best].Value) best = position;      // first maximum wins
        return new PositionChoice(best, needs, Positions.All.Select(p => rows[p]).ToList());
    }

    /// <summary>Unmet starter demand across the league, divided by how many players remain in the best tier of the position.</summary>
    public static double Scarcity(DraftState state, Position position) =>
        Ratio(Demand(state, position), Supply(state.Available, position));

    static int Demand(DraftState state, Position position) =>
        state.Teams.Sum(team => Math.Max(0, state.League.Starters(position) - team.At(position).Count));

    static int Supply(IReadOnlyList<ValuedPlayer> available, Position position)
    {
        var pool = available.Where(p => p.Position == position).ToList();
        if (pool.Count == 0) return 0;
        var bestTier = pool.Min(p => p.Tier);
        return pool.Count(p => p.Tier == bestTier);
    }

    static double Ratio(int demand, int supply) => supply == 0 ? 0 : (double)demand / supply;

    public static IReadOnlyList<Candidate> SelectPlayers(Position position, DraftState state, int teamIndex, ReachSettings? reach = null)
    {
        var pool = RecommendablePool(state, reach).Where(p => p.Position == position).ToList();
        if (pool.Count == 0) return [];
        var pick = state.OverallPick + 1;

        var rankRange = Range(pool.Select(p => p.VorRank));
        var gapRange = Range(pool.Select(p => p.ValueGap));
        var penalty = RiskPenalty(position, state, teamIndex);

        return pool
            .Select(p =>
            {
                var rank = 0.5 * (rankRange.Max == rankRange.Min ? 0 : 1 - Normalize(p.VorRank, rankRange));
                var gap = reach is { UseGapTerm: false } ? 0 : 0.5 * Normalize(p.ValueGap, gapRange);
                var risk = penalty * (p.Player.InjuryFlag ? 1.0 : 0.0);
                var sigmas = reach?.Reach(p.Player, pick) ?? 0;
                var reachPenalty = reach is null || reach.Lambda == 0 ? 0 : reach.Lambda * sigmas * sigmas;
                return new Candidate(p, rank + gap - risk - reachPenalty, rank, gap, risk, reachPenalty, sigmas);
            })
            .OrderByDescending(c => c.WeightedValue)    // stable: the earlier pool entry wins a tie
            .Take(TopN)
            .ToList();
    }

    /// <summary>Penalty on injury-flagged players: grows with flagged players already rostered at the position, fades to zero by the last round.</summary>
    public static double RiskPenalty(Position position, DraftState state, int teamIndex)
    {
        if (position == Position.QB) return 0;
        var flagged = state.Teams[teamIndex].At(position).Count(p => p.Player.InjuryFlag);
        return 0.5 * flagged * (1 - (double)state.Round / state.League.RosterSize);
    }

    static (double Min, double Max) Range(IEnumerable<double> values)
    {
        var list = values.ToList();
        return (list.Min(), list.Max());
    }

    static double Normalize(double value, (double Min, double Max) range) =>
        range.Max == range.Min ? 0 : (value - range.Min) / (range.Max - range.Min);
}
