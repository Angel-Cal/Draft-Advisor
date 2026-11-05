namespace DraftBot.Core;

/// <summary>
/// Roster need. A player's value becomes the points he adds to your best lineup (<see cref="LineupValue.Gain"/>), plus a share of
/// the part of his VOR that does not improve the lineup (depth, injury and bye cover, the chance a backup outscores a starter).
/// That share is <paramref name="BenchFraction"/> for every position, or, when <paramref name="MissProbability"/> is set, it is
/// structural: a backup only plays when enough starters at his position are out the same week. With q the chance a starter is out in
/// a given week and S the slots the position's backups could fill, the k-th backup is worth P(at least k of S starters out) of his
/// VOR (times <paramref name="BenchFraction"/> as a scale, normally 1). A second backup QB or TE is then worth nothing.
/// </summary>
/// <param name="OptionValue">
/// Value bench players by option value against the waiver level instead of by the VOR left over after the lineup: the expected points
/// above the best free agent, E[max(0, X - waiver)] with X normal around his projection (spread = the position RMSE), counted for the part
/// of him that does not start. Starter-level VOR is <= 0 for nearly every late pick, which made all bench candidates worth exactly 0.
/// </param>
public sealed record NeedSettings(double BenchFraction, double? MissProbability = null, bool OptionValue = false)
{
    /// <summary>q from the data: draftable players missed 3.1 of 17 games (QB 2.9, RB 3.2, WR 3.1, TE 3.1) plus one bye week in 18.</summary>
    public const double MeasuredMissProbability = 0.23;

    /// <summary>Roster need with no bench value: lineup gain only. What `tune-need` selected before bench value was explored.</summary>
    public static NeedSettings NoBench { get; } = new(0);

    /// <summary>Roster need with structural, position-specific bench value (k-th backup rule at the measured miss probability).</summary>
    public static NeedSettings Structural { get; } = new(1.0, MeasuredMissProbability);

    /// <summary>Structural weights applied to the option value of a bench player against the waiver level.</summary>
    public static NeedSettings Option { get; } = new(1.0, MeasuredMissProbability, OptionValue: true);

    /// <summary>
    /// The recommended roster-need setting: lineup gain, plus structural position-specific bench value as option value over the waiver
    /// level, with dead picks (a player who can never start or be needed as cover) ranked last. It builds sane rosters without caps
    /// (about 2 QBs and 2 TEs) and beat no bench value in every configuration tested; see LOG.md (`tune-bench`, archived).
    /// </summary>
    public static NeedSettings Default => Option;

    /// <summary>E[max(0, X - waiver)] for X ~ Normal(mean, sd).</summary>
    public static double ExpectedExcess(double mean, double sd, double waiver)
    {
        if (sd <= 0) return Math.Max(0, mean - waiver);
        var d = (mean - waiver) / sd;
        return (mean - waiver) * Normal.Cdf(d) + sd * Math.Exp(-0.5 * d * d) / Math.Sqrt(2 * Math.PI);
    }

    /// <summary>Slots a backup at this position could fill: dedicated starters, plus the FLEX slot for RB and WR (rarely held by a TE).</summary>
    public static int BackupSlots(Position position, LeagueSettings league) => position switch
    {
        Position.RB or Position.WR => league.Starters(position) + league.Flex,
        _ => league.Starters(position),
    };

    /// <summary>P(Binomial(slots, q) >= k): at least k of the starters are out in the same week.</summary>
    public static double AtLeast(int k, int slots, double q)
    {
        var total = 0.0;
        for (var j = k; j <= slots; j++) total += Choose(slots, j) * Math.Pow(q, j) * Math.Pow(1 - q, slots - j);
        return total;
    }

    static double Choose(int n, int r)
    {
        double result = 1;
        for (var i = 1; i <= r; i++) result = result * (n - r + i) / i;
        return result;
    }

    /// <summary>The share of his non-lineup VOR that <paramref name="candidate"/> is worth, given the players already rostered.</summary>
    public double Weight(ValuedPlayer candidate, IReadOnlyList<ValuedPlayer> roster, LeagueSettings league)
    {
        if (MissProbability is null) return BenchFraction;
        var position = candidate.Position;
        var owned = roster.Count(p => p.Position == position) + 1;          // including the candidate
        var k = Math.Max(1, owned - league.Starters(position));            // which backup he would be
        return BenchFraction * AtLeast(k, BackupSlots(position, league), MissProbability.Value);
    }
}

/// <summary>The standard normal distribution.</summary>
static class Normal
{
    /// <summary>P(Z &lt;= x), Abramowitz-Stegun 7.1.26 (error &lt; 1.5e-7).</summary>
    public static double Cdf(double x)
    {
        var z = Math.Abs(x) / Math.Sqrt(2);
        var t = 1 / (1 + 0.3275911 * z);
        var erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.Exp(-z * z);
        return 0.5 * (1 + Math.Sign(x) * erf);
    }
}
