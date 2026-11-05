namespace DraftBot.Core;

/// <summary>
/// ADP-reach control for the recommenders. A player whose ADP is later than the current pick is a reach of
/// z = (ADP - pick) / sigma(pick) standard deviations, where sigma grows with the pick (ADP is less predictive later).
/// Taking him costs <paramref name="Lambda"/> x z^2 in score, so small reaches are nearly free and large ones cannot win; players
/// past <paramref name="CapSigmas"/> are removed from the pool entirely (both for choosing a position and a player).
/// Lambda is in the recommender's own score units: points for <see cref="ValueRecommender"/>, a 0-1 score for <see cref="BaselineRecommender"/>.
/// </summary>
/// <param name="SigmaBase">Picks of spread at pick 0.</param>
/// <param name="SigmaPerPick">Extra spread per pick; the default is the measured cross-platform spread, about 0.16 x ADP.</param>
/// <param name="FreePicks">
/// Only <see cref="ValueRecommender.Rank"/> uses it: reaches up to this many picks cost nothing. The resolution of an ADP is a roughly constant number of picks, while a sigma grows with the pick,
/// so a free zone in picks is tight early (where a fraction of a pick should not decide a card) and does not widen into the late rounds. 0 is the plain cost.
/// </param>
public sealed record ReachSettings(double Lambda, double CapSigmas, double SigmaBase = 2.0, double SigmaPerPick = 0.16, double FreePicks = 0)
{
    /// <summary>The windowed baseline recommender's setting (score units, not points): the middle of a plateau of equally good settings in the Phase 2 follow-up sweep.</summary>
    public static ReachSettings Windowed { get; } = new(Lambda: 0.3, CapSigmas: 4);

    public double Sigma(int pick) => SigmaBase + SigmaPerPick * pick;

    /// <summary>The reach the cost is charged on: <see cref="Reach"/> less the free zone (<see cref="FreePicks"/> picks), never below 0.</summary>
    public double Charged(Player player, int pick)
    {
        var z = Reach(player, pick);
        return double.IsInfinity(z) ? z : Math.Max(0, z - FreePicks / Sigma(pick));
    }

    /// <summary>Reach in standard deviations; 0 for a player at or before the pick, infinity if he has no ADP.</summary>
    public double Reach(Player player, int pick) =>
        player.Adp is null ? double.PositiveInfinity : Math.Max(0, player.Adp.Value - pick) / Sigma(pick);
}
