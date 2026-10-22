namespace DraftBot.Core;

/// <param name="Score">Projected VOR minus the reach cost.</param>
/// <param name="ReachPenalty">lambda x z^2, in points.</param>
/// <param name="ReachSigmas">z: how many standard deviations past the current pick his ADP is (0 if he slid).</param>
public sealed record ValueCandidate(ValuedPlayer Player, double Score, double ReachPenalty, double ReachSigmas)
{
    public double Vor => Player.Vor;
}

/// <summary>
/// One score across every position, replacing the position-first selection: points over replacement (already comparable
/// across positions) minus a reach cost for taking a player past his ADP, with the same far cap as the windowed recommender.
/// There is deliberately no roster-need term yet; it is added later as its own measured step.
/// </summary>
public static class ValueRecommender
{
    const int TopN = 5;

    /// <summary>Provisional default from `tune-value` (peak of a plateau at lambda 400-1000); lambda is in points per sigma squared.</summary>
    public static ReachSettings DefaultReach { get; } = new(Lambda: 1000, CapSigmas: 4);

    /// <summary>Every recommendable player, best first. Ties keep pool order (VOR, best first).</summary>
    public static IReadOnlyList<ValueCandidate> Rank(DraftState state, ReachSettings reach)
    {
        var pick = state.OverallPick + 1;
        return BaselineRecommender.RecommendablePool(state, reach)
            .Select(p =>
            {
                var sigmas = reach.Reach(p.Player, pick);
                var penalty = reach.Lambda == 0 ? 0 : reach.Lambda * sigmas * sigmas;
                return new ValueCandidate(p, p.Vor - penalty, penalty, sigmas);
            })
            .OrderByDescending(c => c.Score)
            .ToList();
    }

    public static IReadOnlyList<ValueCandidate> Recommend(DraftState state, ReachSettings reach) =>
        Rank(state, reach).Take(TopN).ToList();
}
