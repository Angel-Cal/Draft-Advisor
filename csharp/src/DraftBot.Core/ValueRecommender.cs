namespace DraftBot.Core;

/// <param name="Score">Value minus the reach cost, plus the cost-of-waiting bonus when it is on.</param>
/// <param name="ReachPenalty">lambda x z^2, in points (z less the free zone, <see cref="ReachSettings.Charged"/>).</param>
/// <param name="ReachSigmas">z: how many standard deviations past the current pick his ADP is (0 if he slid).</param>
/// <param name="Gain">Points added to the team's best lineup; null when roster need is off.</param>
/// <param name="BenchWeight">Share of his non-lineup value counted as bench value; null when roster need is off.</param>
/// <param name="BenchValue">Points of bench value in the score (0 for a pure starter); null when roster need is off. Candidates that can never start and have a zero backup weight are "dead picks" (score offset by <see cref="ValueRecommender.DeadPickScore"/>).</param>
/// <param name="WaitBonus">Points added for the cost of waiting (<see cref="WaitSettings"/>); null when it is off or I have no later pick.</param>
/// <param name="WaitAlternatives">
/// The players the waiting bonus assumes I might take instead at my next pick, best first: the best alternatives at his position, by the same rule and order the bonus
/// uses, that are likely to last (<see cref="WaitSettings.LikelyToLast"/>), at most <see cref="WaitSettings.DisplayedAlternatives"/>. Null when there is no bonus; empty when no one qualifies.
/// </param>
/// <param name="WaitShortfall">Expected projected points lost by waiting for the alternatives instead of taking him now (the bonus is this times the weight); null when there is no bonus.</param>
public sealed record ValueCandidate(ValuedPlayer Player, double Score, double ReachPenalty, double ReachSigmas, double? Gain = null, double? BenchWeight = null, double? BenchValue = null,
    double? WaitBonus = null, IReadOnlyList<WaitAlternative>? WaitAlternatives = null, double? WaitShortfall = null)
{
    /// <summary>The first of <see cref="WaitAlternatives"/>: the player the explanation names as the alternative to taking him now; null when there is none.</summary>
    public ValueCandidate? WaitFallback => WaitAlternatives?.FirstOrDefault()?.Candidate;

    public double Vor => Player.Vor;

    /// <summary>The value before the reach cost and the waiting bonus: lineup gain plus bench value, or plain VOR when roster need is off.</summary>
    public double BaseValue => Gain is null ? Vor : Gain.Value + (BenchValue ?? 0);
}

/// <summary>
/// One score across every position, replacing the position-first selection: value (points over replacement, optionally measured
/// as the gain to the team's lineup) minus a reach cost for taking a player past his ADP, with the same far cap as the windowed
/// recommender.
/// </summary>
public static class ValueRecommender
{
    const int TopN = 5;

    /// <summary>Survival below which a player is certainly gone by my next pick: he is no alternative, and skipping him keeps the evaluation cheap.</summary>
    const double MinSurvival = 1e-3;

    /// <summary>Score offset for a "dead pick": a player who would never start and, at his position, could never be needed as cover.</summary>
    public const double DeadPickScore = -1_000_000;

    /// <summary>
    /// The recommended cost-of-waiting settings, used with <see cref="NeedSettings.Default"/>.
    /// Weight 4 was the best of 0.1 .. 8 at the calibrated noise
    /// (title odds +1.9 pp, playoffs +1.7 pp, points +11 over plain `need`) and was ahead of `need` at half and double noise and with the roster rules
    /// lifted, with identical roster composition; weight 8 loses ground at low noise. See LOG.md (2026-10-25).
    /// </summary>
    public static WaitSettings DefaultWait { get; } = new(Weight: 4);

    /// <summary>
    /// Lambda 1000 (the peak of a plateau at 400-1000 in `tune-value`; points per sigma squared) with the first pick of reach free (<see cref="ReachSettings.FreePicks"/> 1: ADP cannot claim a finer
    /// resolution, and a 0.4-pick gap was a 102-point swing). Non-inferior to the plain wall in both projection worlds and at every noise level (LOG.md, 2026-10-29). The survival-scaled cost
    /// was the best arm on the validated files but 28 points worse than the wall on the files the live recipe produces (2025 collapses in both), so it was not adopted.
    /// </summary>
    public static ReachSettings DefaultReach { get; } = new(Lambda: 1000, CapSigmas: 4, FreePicks: 1);

    /// <summary>
    /// Every recommendable player, best first. Ties keep pool order (VOR, best first). With <paramref name="need"/> the value is
    /// roster-aware for <paramref name="teamIndex"/>; without it the value is plain VOR.
    /// </summary>
    public static IReadOnlyList<ValueCandidate> Rank(DraftState state, ReachSettings reach, NeedSettings? need = null, int teamIndex = 0, WaitSettings? wait = null)
    {
        var pick = state.OverallPick + 1;
        var roster = state.Teams[teamIndex].Picks;
        var replacement = need is null ? null : LineupValue.Replacement(state);
        var baseline = replacement is null ? 0 : LineupValue.Best(roster, state.League, replacement);
        var waiver = need is { OptionValue: true } ? LineupValue.Waiver(state, replacement!) : null;

        var evaluated = new Dictionary<string, ValueCandidate>();
        ValueCandidate Evaluate(ValuedPlayer p) => evaluated.TryGetValue(p.Id, out var known) ? known : evaluated[p.Id] = Score(p);

        ValueCandidate Score(ValuedPlayer p)
        {
            var sigmas = reach.Reach(p.Player, pick);
            var beyondFree = reach.Charged(p.Player, pick);
            var penalty = reach.Lambda == 0 ? 0 : reach.Lambda * beyondFree * beyondFree;
            if (need is null) return new ValueCandidate(p, p.Vor - penalty, penalty, sigmas);

            var gain = Math.Max(0, LineupValue.Best(roster.Append(p), state.League, replacement!) - baseline);
            var weight = need.Weight(p, roster, state.League);
            // the part of him that does not start: the leftover VOR, or the option value above the waiver level
            var unused = p.Vor > 0 ? Math.Clamp(1 - gain / p.Vor, 0, 1) : 1;
            var bench = waiver is null
                ? weight * Math.Max(0, p.Vor - gain)
                : weight * unused * NeedSettings.ExpectedExcess(p.Player.ProjectedPpr, p.Rmse, waiver[p.Position]);
            var value = gain + bench;
            if (need.MissProbability is not null && gain == 0 && weight == 0) value += DeadPickScore;       // structural weights only: can never start, can never be needed
            return new ValueCandidate(p, value - penalty, penalty, sigmas, gain, weight, bench);
        }

        var scored = BaselineRecommender.RecommendablePool(state, reach).Select(Evaluate).ToList();
        if (wait is { Weight: > 0 } && state.NextPick(teamIndex) is { } nextPick)
            scored = AddWaitBonus(scored, state, wait.Weight, nextPick, reach, Evaluate);
        return scored.OrderByDescending(c => c.Score).ToList();
    }

    public static IReadOnlyList<ValueCandidate> Recommend(DraftState state, ReachSettings reach, NeedSettings? need = null, int teamIndex = 0, WaitSettings? wait = null) =>
        Rank(state, reach, need, teamIndex, wait).Take(TopN).ToList();

    /// <summary>
    /// Adds the cost-of-waiting bonus to every candidate: his value against the best same-position players likely to last to my next pick
    /// that the recommender could take there (inside the reach cap at that pick).
    /// Alternatives come from everyone still available, not just the recommendable window, which is measured at the current pick and would
    /// hide the players I will actually be choosing between later.
    /// </summary>
    static List<ValueCandidate> AddWaitBonus(List<ValueCandidate> scored, DraftState state, double weight, int nextPick, ReachSettings reach,
        Func<ValuedPlayer, ValueCandidate> evaluate)
    {
        var alternatives = state.Available
            .Where(p => WaitSettings.Survival(p.Player, nextPick, reach) > MinSurvival && reach.Reach(p.Player, nextPick) <= reach.CapSigmas)
            .Select(evaluate).GroupBy(c => c.Player.Position).ToDictionary(g => g.Key, g => g
                .OrderByDescending(c => c.BaseValue).Take(WaitSettings.Alternatives + 1)
                .Select(c => (Value: c.BaseValue, Survival: WaitSettings.Survival(c.Player.Player, nextPick, reach), Candidate: c)).ToList());

        return scored.Select(c =>
        {
            var options = alternatives.GetValueOrDefault(c.Player.Position, []).Where(a => a.Candidate.Player.Id != c.Player.Id).ToList();
            var shortfall = WaitSettings.ExpectedShortfall(c.BaseValue, options.Select(o => (o.Value, o.Survival)));
            var likely = options.Where(o => o.Survival >= WaitSettings.LikelyToLast).Take(WaitSettings.DisplayedAlternatives)
                .Select(o => new WaitAlternative(o.Candidate, o.Survival)).ToList();
            return c with { Score = c.Score + weight * shortfall, WaitBonus = weight * shortfall, WaitAlternatives = likely, WaitShortfall = shortfall };
        }).ToList();
    }
}
