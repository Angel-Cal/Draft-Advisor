namespace DraftBot.Core;

/// <summary>
/// Cost of waiting (value over next available). Taking a player now rather than at my next pick is worth the points I expect to lose by
/// waiting: how far the best player at his position who is still there at that pick falls short of him. A player the market is about to
/// take, with nobody close behind him, is worth more now than an equal player in a deep position. Only players the recommender could take
/// at that pick (inside the reach cap there) count as alternatives, so the player named as the fallback is one it would advise.
/// The score gets <paramref name="Weight"/> x that expected shortfall; a weight of 0 changes nothing.
/// </summary>
/// <param name="Weight">Share of the expected shortfall added to the score (tuned in the simulator).</param>
public sealed record WaitSettings(double Weight)
{
    /// <summary>Only the best few alternatives at a position can matter: the chance that all of them are gone shrinks fast.</summary>
    internal const int Alternatives = 20;

    /// <summary>Survival chance from which an alternative counts as "likely still there" at my next pick, i.e. can be named as the player I would take instead.</summary>
    internal const double LikelyToLast = 0.5;

    /// <summary>How many likely-to-last alternatives a candidate carries for display (the first one is the fallback the explanation names).</summary>
    internal const int DisplayedAlternatives = 2;

    /// <summary>
    /// P(the player is still there at pick <paramref name="nextPick"/>): his draft position is Normal around his ADP with the spread the reach
    /// cost uses for a pick at that ADP. A player with no ADP is one nobody takes.
    /// </summary>
    public static double Survival(Player player, int nextPick, ReachSettings reach) =>
        player.Adp is null ? 1 : Normal.Cdf((player.Adp.Value - (nextPick - 0.5)) / (reach.SigmaBase + reach.SigmaPerPick * player.Adp.Value));

    /// <summary>
    /// E[max(0, value - best survivor)], taking the alternatives best-first and independent: the first one that survives is the one I get;
    /// if none does, I get nothing above replacement and the whole value is lost.
    /// </summary>
    public static double ExpectedShortfall(double value, IEnumerable<(double Value, double Survival)> alternativesBestFirst)
    {
        var noneYet = 1.0;
        var shortfall = 0.0;
        foreach (var (alternative, survival) in alternativesBestFirst)
        {
            shortfall += noneYet * survival * Math.Max(0, value - alternative);
            noneYet *= 1 - survival;
        }
        return shortfall + noneYet * Math.Max(0, value);
    }
}

/// <summary>An alternative to taking a candidate now: who he is (valued as if drafted by me) and the chance he is still there at my next pick.</summary>
public sealed record WaitAlternative(ValueCandidate Candidate, double Survival);
