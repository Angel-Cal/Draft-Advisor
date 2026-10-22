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
    /// <summary>E[max(0, X - waiver)] for X ~ Normal(mean, sd).</summary>
    public static double ExpectedExcess(double mean, double sd, double waiver)
    {
        if (sd <= 0) return Math.Max(0, mean - waiver);
        var d = (mean - waiver) / sd;
        return (mean - waiver) * NormalCdf(d) + sd * Math.Exp(-0.5 * d * d) / Math.Sqrt(2 * Math.PI);
    }

    static double NormalCdf(double x)      // Abramowitz-Stegun 7.1.26 (error < 1.5e-7)
    {
        var z = Math.Abs(x) / Math.Sqrt(2);
        var t = 1 / (1 + 0.3275911 * z);
        var erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.Exp(-z * z);
        return 0.5 * (1 + Math.Sign(x) * erf);
    }

    /// <summary>q from the data: draftable players missed 3.1 of 17 games (QB 2.9, RB 3.2, WR 3.1, TE 3.1) plus one bye week in 18.</summary>
    public const double MeasuredMissProbability = 0.23;

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

    /// <summary>Roster need with no bench value: lineup gain only. What `tune-need` selected before bench value was explored.</summary>
    public static NeedSettings NoBench { get; } = new(0);

    /// <summary>Roster need with structural, position-specific bench value (k-th backup rule at the measured miss probability).</summary>
    public static NeedSettings Structural { get; } = new(1.0, MeasuredMissProbability);

    /// <summary>Structural weights applied to the option value of a bench player against the waiver level.</summary>
    public static NeedSettings Option { get; } = new(1.0, MeasuredMissProbability, OptionValue: true);

    /// <summary>
    /// The recommended roster-need setting: lineup gain, plus structural position-specific bench value as option value over the waiver
    /// level, with dead picks (a player who can never start or be needed as cover) ranked last. It builds sane rosters without caps
    /// (about 2 QBs and 2 TEs) and beat no bench value in every configuration tested; see `tune-bench` and LOG.md.
    /// </summary>
    public static NeedSettings Default => Option;
}

/// <param name="Score">Value minus the reach cost.</param>
/// <param name="ReachPenalty">lambda x z^2, in points.</param>
/// <param name="ReachSigmas">z: how many standard deviations past the current pick his ADP is (0 if he slid).</param>
/// <param name="Gain">Points added to the team's best lineup; null when roster need is off.</param>
/// <param name="BenchWeight">Share of his non-lineup value counted as bench value; null when roster need is off.</param>
/// <param name="BenchValue">Points of bench value in the score (0 for a pure starter); null when roster need is off. Candidates that can never start and have a zero backup weight are "dead picks" (score offset by <see cref="ValueRecommender.DeadPickScore"/>).</param>
public sealed record ValueCandidate(ValuedPlayer Player, double Score, double ReachPenalty, double ReachSigmas, double? Gain = null, double? BenchWeight = null, double? BenchValue = null)
{
    public double Vor => Player.Vor;
}

/// <summary>
/// One score across every position, replacing the position-first selection: value (points over replacement, optionally measured
/// as the gain to the team's lineup) minus a reach cost for taking a player past his ADP, with the same far cap as the windowed
/// recommender.
/// </summary>
public static class ValueRecommender
{
    const int TopN = 5;

    /// <summary>Score offset for a "dead pick": a player who would never start and, at his position, could never be needed as cover.</summary>
    public const double DeadPickScore = -1_000_000;

    /// <summary>Provisional default from the sweep in `tune-value` (peak of a plateau at lambda 400-1000); lambda is in points per sigma squared.</summary>
    public static ReachSettings DefaultReach { get; } = new(Lambda: 1000, CapSigmas: 4);

    /// <summary>
    /// Every recommendable player, best first. Ties keep pool order (VOR, best first). With <paramref name="need"/> the value is
    /// roster-aware for <paramref name="teamIndex"/>; without it the value is plain VOR.
    /// </summary>
    public static IReadOnlyList<ValueCandidate> Rank(DraftState state, ReachSettings reach, NeedSettings? need = null, int teamIndex = 0)
    {
        var pick = state.OverallPick + 1;
        var roster = state.Teams[teamIndex].Picks;
        var replacement = need is null ? null : LineupValue.Replacement(state);
        var baseline = replacement is null ? 0 : LineupValue.Best(roster, state.League, replacement);
        var waiver = need is { OptionValue: true } ? LineupValue.Waiver(state, replacement!) : null;

        return BaselineRecommender.RecommendablePool(state, reach)
            .Select(p =>
            {
                var sigmas = reach.Reach(p.Player, pick);
                var penalty = reach.Lambda == 0 ? 0 : reach.Lambda * sigmas * sigmas;
                double? gain = null, weight = null, bench = null;
                var value = p.Vor;
                if (need is not null)
                {
                    var g = Math.Max(0, LineupValue.Best(roster.Append(p), state.League, replacement!) - baseline);
                    gain = g;
                    weight = need.Weight(p, roster, state.League);
                    // the part of him that does not start: the leftover VOR, or the option value above the waiver level
                    var unused = p.Vor > 0 ? Math.Clamp(1 - g / p.Vor, 0, 1) : 1;
                    bench = waiver is null
                        ? weight.Value * Math.Max(0, p.Vor - g)
                        : weight.Value * unused * NeedSettings.ExpectedExcess(p.Player.ProjectedPpr, p.Rmse, waiver[p.Position]);
                    value = g + bench.Value;
                    if (need.MissProbability is not null && g == 0 && weight == 0) value += DeadPickScore;       // structural weights only: can never start, can never be needed
                }
                return new ValueCandidate(p, value - penalty, penalty, sigmas, gain, weight, bench);
            })
            .OrderByDescending(c => c.Score)
            .ToList();
    }

    public static IReadOnlyList<ValueCandidate> Recommend(DraftState state, ReachSettings reach, NeedSettings? need = null, int teamIndex = 0) =>
        Rank(state, reach, need, teamIndex).Take(TopN).ToList();
}
