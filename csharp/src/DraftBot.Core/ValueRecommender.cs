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
/// <param name="StarterOption">
/// Weight on the option premium of a starter (needs <paramref name="OptionValue"/>). A starter who busts is cut and replaced from the waiver
/// level, so he is worth E[max(X, waiver)], not max(projection, waiver); the premium is the difference, counted for the share of him that
/// starts (lineup gain over VOR). 0 turns it off.
/// </param>
public sealed record NeedSettings(double BenchFraction, double? MissProbability = null, bool OptionValue = false, double StarterOption = 0)
{
    /// <summary>E[max(X, waiver)] - max(projection, waiver) for X ~ Normal(projection, sd): what the right to cut a bust is worth. Never negative.</summary>
    public static double OptionPremium(double projection, double sd, double waiver) =>
        Math.Max(0, ExpectedExcess(projection, sd, waiver) - Math.Max(0, projection - waiver));

    /// <summary>E[max(0, X - waiver)] for X ~ Normal(mean, sd).</summary>
    public static double ExpectedExcess(double mean, double sd, double waiver)
    {
        if (sd <= 0) return Math.Max(0, mean - waiver);
        var d = (mean - waiver) / sd;
        return (mean - waiver) * NormalCdf(d) + sd * Math.Exp(-0.5 * d * d) / Math.Sqrt(2 * Math.PI);
    }

    internal static double NormalCdf(double x)      // Abramowitz-Stegun 7.1.26 (error < 1.5e-7)
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

    /// <summary>The default roster need plus the option premium of starters, at the given weight.</summary>
    public static NeedSettings WithStarterOption(double weight) => Option with { StarterOption = weight };

    /// <summary>
    /// The recommended roster-need setting: lineup gain, plus structural position-specific bench value as option value over the waiver
    /// level, with dead picks (a player who can never start or be needed as cover) ranked last. It builds sane rosters without caps
    /// (about 2 QBs and 2 TEs) and beat no bench value in every configuration tested; see `tune-bench` and LOG.md.
    /// </summary>
    public static NeedSettings Default => Option;
}

/// <summary>
/// Cost of waiting (value over next available). Taking a player now rather than at my next pick is worth the points I expect to lose by
/// waiting: how far the best player at his position who is still there at that pick falls short of him. A player the market is about to
/// take, with nobody close behind him, is worth more now than an equal player in a deep position.
/// The score gets <paramref name="Weight"/> x that expected shortfall; a weight of 0 changes nothing.
/// </summary>
/// <param name="Weight">Share of the expected shortfall added to the score (tuned in the simulator).</param>
/// <param name="SpreadScale">
/// Multiplies the pick spread used for survival (the reach settings' 2 + 0.16 x ADP, which measures disagreement between ADP sources, about 1.8x the
/// real draft-to-draft spread in Fantasy Football Calculator mocks). 1 keeps the reach spread.
/// </param>
/// <param name="Horizon">
/// How many of my next picks to look at. The bonus is the sum of the expected shortfall at each of them (survival gets worse the longer a player must last, so
/// each later term is larger for a scarce player), each later term scaled by <paramref name="HorizonDecay"/> per step. 1 is the original one-pick bonus.
/// </param>
/// <param name="ActiveRounds">Rounds (1-based) in which the bonus applies; null means every round. For finding where the bonus earns its gain.</param>
/// <param name="ActivePositions">Positions the bonus applies to; null means all. Inactive candidates keep their one-step score (bonus 0).</param>
/// <param name="Standardize">
/// Combine the value and the shortfall as z-scores over the best <paramref name="StandardizePool"/> candidates (by one-step score) instead of adding the raw shortfall:
/// score = mean + sd x (z_value + Weight x z_shortfall) / (1 + Weight) - reach cost, with mean and sd of the values before the reach cost. The weight is then a
/// unit-free mixing weight (1 = equal importance) and means the same thing in every round, however spread out the values are. Candidates outside the pool keep their one-step score.
/// </param>
public sealed record WaitSettings(double Weight, double SpreadScale = 1.0, int Horizon = 1, double HorizonDecay = 1.0,
    IReadOnlyList<int>? ActiveRounds = null, IReadOnlyList<Position>? ActivePositions = null, bool Standardize = false, int StandardizePool = 15)
{
    /// <summary>Whether the bonus applies to a candidate at <paramref name="position"/> in <paramref name="round"/>.</summary>
    public bool AppliesTo(int round, Position position) =>
        (ActiveRounds is null || ActiveRounds.Contains(round)) && (ActivePositions is null || ActivePositions.Contains(position));

    /// <summary>Only the best few alternatives at a position can matter: the chance that all of them are gone shrinks fast.</summary>
    internal const int Alternatives = 20;

    /// <summary>
    /// P(the player is still there at pick <paramref name="nextPick"/>): his draft position is Normal around his ADP with the spread the reach
    /// cost uses for a pick at that ADP. A player with no ADP is one nobody takes.
    /// </summary>
    public static double Survival(Player player, int nextPick, ReachSettings reach, double spreadScale = 1.0) =>
        player.Adp is null ? 1 : NeedSettings.NormalCdf((player.Adp.Value - (nextPick - 0.5)) / (spreadScale * (reach.SigmaBase + reach.SigmaPerPick * player.Adp.Value)));

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

/// <summary>
/// Two-step lookahead. A candidate is scored as his value plus <paramref name="Beta"/> x the expected value of my best pick at my next turn, given
/// my roster with him on it, from the players likely to still be there (any position, independent survivals from the ADP model). If he will
/// probably last, taking someone else now and him later beats taking him now; that is what the reach cost approximates by hand. Replaces the
/// cost-of-waiting bonus (they cannot be combined).
/// </summary>
/// <param name="Beta">Weight on the next-turn term.</param>
/// <param name="Candidates">Only the best this-many candidates by the one-step score get the lookahead (it re-values the likely survivors for each one).</param>
/// <param name="PerPosition">Survivors considered per position, best first by their value before the pick (it can only fall after it).</param>
/// <param name="SpreadScale">Multiplies the survival spread, as in <see cref="WaitSettings"/>.</param>
public sealed record LookaheadSettings(double Beta, int Candidates = 15, int PerPosition = 12, double SpreadScale = 1.0)
{
    /// <summary>E[value of the best survivor]: the first survivor in value order is the one I get; if none lasts, nothing above replacement.</summary>
    public static double ExpectedBest(IEnumerable<(double Value, double Survival)> alternativesBestFirst)
    {
        var noneYet = 1.0;
        var expected = 0.0;
        foreach (var (value, survival) in alternativesBestFirst)
        {
            expected += noneYet * survival * Math.Max(0, value);
            noneYet *= 1 - survival;
        }
        return expected;
    }
}

/// <param name="Score">Value minus the reach cost, plus the cost-of-waiting bonus or the lookahead term when one is on.</param>
/// <param name="ReachPenalty">lambda x z^2, in points.</param>
/// <param name="ReachSigmas">z: how many standard deviations past the current pick his ADP is (0 if he slid).</param>
/// <param name="Gain">Points added to the team's best lineup; null when roster need is off.</param>
/// <param name="BenchWeight">Share of his non-lineup value counted as bench value; null when roster need is off.</param>
/// <param name="BenchValue">Points of bench value in the score (0 for a pure starter); null when roster need is off. Candidates that can never start and have a zero backup weight are "dead picks" (score offset by <see cref="ValueRecommender.DeadPickScore"/>).</param>
/// <param name="WaitBonus">Points added for the cost of waiting (<see cref="WaitSettings"/>); null when it is off or I have no later pick.</param>
/// <param name="StarterPremium">Points of option premium for the part of him that starts (<see cref="NeedSettings.StarterOption"/>); null when off.</param>
/// <param name="NextTurn">Expected value of my best pick at my next turn if I take him now (<see cref="LookaheadSettings"/>), before the weight; null when not looked ahead.</param>
public sealed record ValueCandidate(ValuedPlayer Player, double Score, double ReachPenalty, double ReachSigmas, double? Gain = null, double? BenchWeight = null, double? BenchValue = null, double? WaitBonus = null, double? StarterPremium = null, double? NextTurn = null)
{
    public double Vor => Player.Vor;

    /// <summary>The value before the reach cost and the waiting bonus: lineup gain plus bench value and starter premium, or plain VOR when roster need is off.</summary>
    public double BaseValue => Gain is null ? Vor : Gain.Value + (BenchValue ?? 0) + (StarterPremium ?? 0);
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

    /// <summary>
    /// The recommended cost-of-waiting weight, used with <see cref="NeedSettings.Default"/>. Weight 4 was the best of 0.1 .. 8 at the calibrated noise
    /// (title odds +1.9 pp, playoffs +1.7 pp, points +11 over plain `need`) and was ahead of `need` at half and double noise and with the roster rules
    /// lifted, with identical roster composition; weight 8 loses ground at low noise. See LOG.md (2026-10-25).
    /// </summary>
    public static WaitSettings DefaultWait { get; } = new(Weight: 4);

    /// <summary>Provisional default from the sweep in `tune-value` (peak of a plateau at lambda 400-1000); lambda is in points per sigma squared.</summary>
    public static ReachSettings DefaultReach { get; } = new(Lambda: 1000, CapSigmas: 4);

    /// <summary>
    /// Every recommendable player, best first. Ties keep pool order (VOR, best first). With <paramref name="need"/> the value is
    /// roster-aware for <paramref name="teamIndex"/>; without it the value is plain VOR.
    /// </summary>
    public static IReadOnlyList<ValueCandidate> Rank(DraftState state, ReachSettings reach, NeedSettings? need = null, int teamIndex = 0, WaitSettings? wait = null,
        LookaheadSettings? lookahead = null)
    {
        if (wait is not null && lookahead is not null) throw new ArgumentException("the lookahead replaces the waiting bonus; use one", nameof(lookahead));
        var pick = state.OverallPick + 1;
        var roster = state.Teams[teamIndex].Picks;
        var replacement = need is null ? null : LineupValue.Replacement(state);
        var baseline = replacement is null ? 0 : LineupValue.Best(roster, state.League, replacement);
        var waiver = need is { OptionValue: true } ? LineupValue.Waiver(state, replacement!) : null;

        var evaluated = new Dictionary<string, ValueCandidate>();
        ValueCandidate Evaluate(ValuedPlayer p)
        {
            if (evaluated.TryGetValue(p.Id, out var known)) return known;
            return evaluated[p.Id] = ScoreWith(p, roster, baseline);
        }

        // The player's value for a given roster (the real one, or the real one plus a candidate in the lookahead); baseline = that roster's best lineup.
        ValueCandidate ScoreWith(ValuedPlayer p, IReadOnlyList<ValuedPlayer> rosterNow, double baselineNow)
        {
            var sigmas = reach.Reach(p.Player, pick);
            var penalty = reach.Lambda == 0 ? 0 : reach.Lambda * sigmas * sigmas;
            double? gain = null, weight = null, bench = null, starter = null;
            var value = p.Vor;
            if (need is not null)
            {
                var g = Math.Max(0, LineupValue.Best(rosterNow.Append(p), state.League, replacement!) - baselineNow);
                gain = g;
                weight = need.Weight(p, rosterNow, state.League);
                // the part of him that does not start: the leftover VOR, or the option value above the waiver level
                var unused = p.Vor > 0 ? Math.Clamp(1 - g / p.Vor, 0, 1) : 1;
                bench = waiver is null
                    ? weight.Value * Math.Max(0, p.Vor - g)
                    : weight.Value * unused * NeedSettings.ExpectedExcess(p.Player.ProjectedPpr, p.Rmse, waiver[p.Position]);
                value = g + bench.Value;
                if (need.StarterOption > 0 && waiver is not null && g > 0 && p.Vor > 0)
                {
                    starter = need.StarterOption * Math.Clamp(g / p.Vor, 0, 1) * NeedSettings.OptionPremium(p.Player.ProjectedPpr, p.Rmse, waiver[p.Position]);
                    value += starter.Value;
                }
                if (need.MissProbability is not null && g == 0 && weight == 0) value += DeadPickScore;       // structural weights only: can never start, can never be needed
            }
            return new ValueCandidate(p, value - penalty, penalty, sigmas, gain, weight, bench, StarterPremium: starter);
        }

        var scored = BaselineRecommender.RecommendablePool(state, reach).Select(Evaluate).ToList();

        if (wait is { Weight: > 0 } && state.UpcomingPicks(teamIndex, Math.Max(1, wait.Horizon)) is { Count: > 0 } upcoming)
            scored = AddWaitBonus(scored, state, wait, upcoming, reach, Evaluate);
        if (lookahead is { Beta: > 0 } && state.NextPick(teamIndex) is { } nextTurn)
            scored = AddLookahead(scored, state, lookahead, nextTurn, reach, roster, ScoreWith, replacement, Evaluate);
        return scored.OrderByDescending(c => c.Score).ToList();
    }

    /// <summary>
    /// Adds the two-step lookahead to the best candidates by the one-step score: for each, the expected value of my best pick at my next turn given my roster with him
    /// on it. The likely survivors are the best few per position by their value before the pick (their value can only fall once he joins), re-valued against the new roster.
    /// </summary>
    static List<ValueCandidate> AddLookahead(List<ValueCandidate> scored, DraftState state, LookaheadSettings lookahead, int nextTurn, ReachSettings reach,
        IReadOnlyList<ValuedPlayer> roster, Func<ValuedPlayer, IReadOnlyList<ValuedPlayer>, double, ValueCandidate> scoreWith,
        IReadOnlyDictionary<Position, double>? replacement, Func<ValuedPlayer, ValueCandidate> evaluate)
    {
        const double MinSurvival = 1e-3;
        double Survival(ValuedPlayer p) => WaitSettings.Survival(p.Player, nextTurn, reach, lookahead.SpreadScale);
        var survivors = state.Available.Where(p => Survival(p) > MinSurvival).Select(p => (Player: p, Survival: Survival(p), Before: evaluate(p).BaseValue))
            .GroupBy(s => s.Player.Position).SelectMany(g => g.OrderByDescending(s => s.Before).Take(lookahead.PerPosition)).ToList();

        var top = scored.OrderByDescending(c => c.Score).Take(lookahead.Candidates).Select(c => c.Player.Id).ToHashSet();
        return scored.Select(c =>
        {
            if (!top.Contains(c.Player.Id)) return c;
            var withHim = roster.Append(c.Player).ToList();
            var baselineWith = replacement is null ? 0 : LineupValue.Best(withHim, state.League, replacement);        // plain VOR (no roster need) ignores the roster
            var next = LookaheadSettings.ExpectedBest(survivors.Where(s => s.Player.Id != c.Player.Id)
                .Select(s => (Value: scoreWith(s.Player, withHim, baselineWith).BaseValue, s.Survival)).OrderByDescending(s => s.Value));
            return c with { Score = c.Score + lookahead.Beta * next, NextTurn = next };
        }).ToList();
    }

    /// <summary>
    /// Adds the cost-of-waiting bonus to every candidate: his value against the best same-position players likely to last to each of my
    /// <paramref name="upcoming"/> picks, summed over the picks (each later one scaled by the horizon decay).
    /// Alternatives come from everyone still available, not just the recommendable window, which is measured at the current pick and would
    /// hide the players I will actually be choosing between later.
    /// </summary>
    static List<ValueCandidate> AddWaitBonus(List<ValueCandidate> scored, DraftState state, WaitSettings wait, IReadOnlyList<int> upcoming, ReachSettings reach,
        Func<ValuedPlayer, ValueCandidate> evaluate)
    {
        const double MinSurvival = 1e-3;       // a player who is certainly gone by then is no alternative; skipping him keeps the evaluation cheap
        // survival only falls the longer a player has to last, so anyone worth considering at a later pick passes this filter at the first one
        var alternatives = state.Available
            .Where(p => WaitSettings.Survival(p.Player, upcoming[0], reach, wait.SpreadScale) > MinSurvival)
            .Select(evaluate).GroupBy(c => c.Player.Position).ToDictionary(g => g.Key, g => g
                .OrderByDescending(c => c.BaseValue).Take(WaitSettings.Alternatives + 1)
                .Select(c => (c.Player.Id, c.BaseValue, Survival: upcoming.Select(pick => WaitSettings.Survival(c.Player.Player, pick, reach, wait.SpreadScale)).ToArray())).ToList());

        var withShortfall = scored.Select(c =>
        {
            if (!wait.AppliesTo(state.Round, c.Player.Position)) return (Candidate: c, Shortfall: 0.0);
            var sameSpot = alternatives.GetValueOrDefault(c.Player.Position, []).Where(a => a.Id != c.Player.Id).ToList();
            var shortfall = 0.0;
            for (var step = 0; step < upcoming.Count; step++)
                shortfall += Math.Pow(wait.HorizonDecay, step) * WaitSettings.ExpectedShortfall(c.BaseValue, sameSpot.Select(a => (a.BaseValue, a.Survival[step])));
            return (Candidate: c, Shortfall: shortfall);
        }).ToList();

        if (!wait.Standardize)
            return withShortfall.Select(x => x.Candidate with { Score = x.Candidate.Score + wait.Weight * x.Shortfall, WaitBonus = wait.Weight * x.Shortfall }).ToList();

        // standardize the value (before the reach cost, which stays a separate wall in points: the best candidates by one-step score include heavily penalized ones)
        var pool = withShortfall.OrderByDescending(x => x.Candidate.Score).Take(wait.StandardizePool).ToList();
        var inPool = pool.Select(x => x.Candidate.Player.Id).ToHashSet();
        var (meanValue, sdValue) = MeanAndSd(pool.Select(x => x.Candidate.BaseValue));
        var (meanShortfall, sdShortfall) = MeanAndSd(pool.Select(x => x.Shortfall));
        return withShortfall.Select(x =>
        {
            var c = x.Candidate;
            if (!inPool.Contains(c.Player.Id) || sdValue < 1e-9) return c with { WaitBonus = 0 };
            var zValue = (c.BaseValue - meanValue) / sdValue;
            var zShortfall = sdShortfall < 1e-9 ? 0 : (x.Shortfall - meanShortfall) / sdShortfall;
            var mixed = meanValue + sdValue * (zValue + wait.Weight * zShortfall) / (1 + wait.Weight);
            var apart = c.Score - (c.BaseValue - c.ReachPenalty);                 // what the one-step score holds beyond value and reach cost (the dead-pick offset)
            var score = mixed - c.ReachPenalty + apart;
            return c with { Score = score, WaitBonus = score - c.Score };
        }).ToList();
    }

    /// <summary>Mean and population standard deviation.</summary>
    public static (double Mean, double Sd) MeanAndSd(IEnumerable<double> values)
    {
        var list = values.ToList();
        if (list.Count == 0) return (0, 0);
        var mean = list.Average();
        return (mean, Math.Sqrt(list.Sum(v => (v - mean) * (v - mean)) / list.Count));
    }

    public static IReadOnlyList<ValueCandidate> Recommend(DraftState state, ReachSettings reach, NeedSettings? need = null, int teamIndex = 0, WaitSettings? wait = null,
        LookaheadSettings? lookahead = null) =>
        Rank(state, reach, need, teamIndex, wait, lookahead).Take(TopN).ToList();
}
