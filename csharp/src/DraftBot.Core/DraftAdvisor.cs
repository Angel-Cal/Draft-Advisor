namespace DraftBot.Core;

/// <summary>One reason tag on a recommendation: which reason it is, its name on screen, and the sentence shown when the user hovers it.</summary>
public sealed record AdviceTag(ReasonLabel Label, string Name, string Text);

/// <summary>A ranked recommendation (1 is best) with its plain-language headline and reason tags.</summary>
/// <param name="TopShare">
/// How firmly the advisor stands behind it: the share of re-rankings with every ADP nudged by about a pick (<see cref="DraftAdvisor.ConfidenceJitterPicks"/>) in which he comes first among the picks the advice backs;
/// null when the advice was asked to skip the check. Several picks with a real share are interchangeable at this spot.
/// </param>
public sealed record RankedPick(int Rank, ValueCandidate Candidate, string Headline, IReadOnlyList<AdviceTag> Tags, double? TopShare = null);

/// <summary>
/// What waiting means at one position: the advisor's top player there now, the projected points expected to be lost by waiting for someone else, whether that
/// loss is large enough to say "take now" (<see cref="Explainer.NoticeableCost"/>), and the best players likely to still be there at my next pick.
/// </summary>
/// <param name="IsRecommended">
/// Whether this is a position the advice backs: the top pick's position, and in a close call the other position too. Only these tiles get the recommendation's emphasis;
/// a position can be costly to wait on (<paramref name="TakeNow"/>) without being the recommended one.
/// </param>
/// <param name="TopIsReach">The advisor's top player at this position would be a reach at this pick (<see cref="Explainer.IsReach"/>): he cannot be a card, so waiting costs points but taking him now is not the advice.</param>
public sealed record PositionAdvice(Position Position, ValueCandidate Top, double CostOfWaiting, bool TakeNow, IReadOnlyList<WaitAlternative> LikelyThere, bool IsRecommended, bool TopIsReach = false);

/// <summary>A player the model likes who is further above his ADP than the advisor will recommend; <paramref name="PicksEarly"/> is how many picks before his ADP this pick falls.</summary>
public sealed record PastTheWallPlayer(ValuedPlayer Player, double PicksEarly);

/// <summary>Everything the draft screen shows for one team's pick (see <see cref="DraftAdvisor"/>).</summary>
/// <param name="Pick">The pick being made, 1-based.</param>
/// <param name="NextPick">The team's next pick, or null when it has none left.</param>
/// <param name="Recommended">
/// The advisor's top <see cref="DraftAdvisor.RecommendedCount"/> sane picks, best first: players who would be a reach (<see cref="Explainer.IsReach"/>)
/// are left out and appear under <paramref name="PastTheWall"/> instead (unless nothing else is left).
/// </param>
/// <param name="Positions">One entry per position that has a candidate, in QB, RB, WR, TE order.</param>
/// <param name="PastTheWall">Unranked: players beyond the reach limit, by value without the reach cost.</param>
/// <param name="Replacement">Replacement-level projected points per position.</param>
/// <param name="Rival">Set when the best pick at another position scores almost the same as the top pick (a close call): that other position (see <see cref="DraftAdvisor.RivalPosition"/>).</param>
public sealed record Advice(int Pick, int? NextPick, IReadOnlyList<RankedPick> Recommended, IReadOnlyList<PositionAdvice> Positions,
    IReadOnlyList<PastTheWallPlayer> PastTheWall, IReadOnlyDictionary<Position, double> Replacement, Position? Rival = null);

/// <summary>
/// The one call the app makes at each pick: ranks the pool with the adopted settings (single score with roster need, the waiting bonus and the reach limit)
/// and packages the result for the screen, so the screen never recomputes anything.
/// </summary>
public static class DraftAdvisor
{
    /// <summary>How many ranked recommendations come back (the screen shows the first three as cards and the rest as a line).</summary>
    public const int RecommendedCount = 5;

    /// <summary>How many "past the wall" players come back.</summary>
    public const int PastTheWallCount = 3;

    /// <summary>Only slight reaches count as "past the wall": players whose ADP is within this many standard deviations of the pick. At 2.5 the list also held a running back 20 picks early.</summary>
    public const double PastTheWallSigmas = 1.5;

    /// <summary>A close call: the best pick at another position scores within this share of the top score (but never less than <see cref="CloseCallMinPoints"/> apart). A display choice, not a tested one.</summary>
    public const double CloseCallShare = 0.05;

    /// <summary>Score difference always treated as a tie, so a top score near zero does not make every gap look big.</summary>
    public const double CloseCallMinPoints = 5;

    /// <summary>How many times the pool is re-ranked with the ADPs nudged, to see how firmly the top pick stands (<see cref="RankedPick.TopShare"/>). About 0.1 s a pick.</summary>
    public const int ConfidenceSamples = 30;

    /// <summary>Standard deviation, in picks, of the nudge applied to every ADP: about the resolution a consensus ADP can claim. At this size 20.6% of rounds 1-2 picks changed under the old cost (LOG.md, 2026-10-29).</summary>
    public const double ConfidenceJitterPicks = 1.0;

    /// <summary>A pick at another position that is first in at least this share of the nudged re-rankings makes the call close, whatever the score gap.</summary>
    public const double CloseCallTopShare = 0.2;

    /// <summary>
    /// The position of the best candidate at a different position than the first one, if his score is within <see cref="CloseCallShare"/> of the top score
    /// (<see cref="CloseCallMinPoints"/> at least); null when the top pick is clearly ahead or no other position is among the candidates.
    /// </summary>
    public static Position? RivalPosition(IReadOnlyList<ValueCandidate> bestFirst)
    {
        if (bestFirst.Count < 2) return null;
        var best = bestFirst[0];
        var rival = bestFirst.Skip(1).FirstOrDefault(c => c.Player.Position != best.Player.Position);
        if (rival is null) return null;
        return best.Score - rival.Score <= Math.Max(CloseCallMinPoints, CloseCallShare * Math.Abs(best.Score)) ? rival.Player.Position : null;
    }

    /// <summary>The advice for <paramref name="teamIndex"/> at the current pick; settings default to the adopted ones.</summary>
    /// <param name="confidenceSamples">How many nudged re-rankings back <see cref="RankedPick.TopShare"/> and the share-based close call; 0 skips the check.</param>
    public static Advice Advise(DraftState state, int teamIndex, ReachSettings? reach = null, NeedSettings? need = null, WaitSettings? wait = null, int confidenceSamples = ConfidenceSamples)
    {
        reach ??= ValueRecommender.DefaultReach;
        need ??= NeedSettings.Default;
        wait ??= ValueRecommender.DefaultWait;
        var pick = state.OverallPick + 1;

        var ranked = ValueRecommender.Rank(state, reach, need, teamIndex, wait);
        var sane = ranked.Where(c => !Explainer.IsReach(c)).Take(RecommendedCount).ToList();
        var top = sane.Count > 0 ? sane : ranked.Take(RecommendedCount).ToList();          // never an empty screen: if only early picks are left, they are the picks
        var explanations = Explainer.Explain(state, teamIndex, top, reach);
        var shares = confidenceSamples > 0 ? TopShares(state, teamIndex, reach, need, wait, confidenceSamples) : null;
        var rival = RivalPosition(top) ?? ShareRival(top, shares);

        // "Recommended" (the waiting-cost reason) belongs only to a pick the advice stands behind: the top pick and, in a close call, the best pick at the other position
        var backed = new HashSet<string>();
        if (top.Count > 0) backed.Add(top[0].Player.Id);
        if (rival is { } other) backed.Add(top.First(c => c.Player.Position == other).Player.Id);
        var recommended = top.Select((c, i) =>
        {
            var tags = explanations[i].Labels.Zip(explanations[i].Reasons, (label, text) => new AdviceTag(label, label.DisplayName(), text))
                .Where(tag => tag.Label != ReasonLabel.RunningOut || backed.Contains(c.Player.Id)).ToList();
            // a backed pick is always tagged "Recommended": with the waiting-cost reason when waiting is costly, else with the best-overall reason
            if (backed.Contains(c.Player.Id) && tags.All(t => t.Label != ReasonLabel.RunningOut))
                tags.Insert(Math.Min(1, tags.Count), new AdviceTag(ReasonLabel.RunningOut, ReasonLabel.RunningOut.DisplayName(), Explainer.BestPickReason(c, pick)));
            return new RankedPick(i + 1, c, explanations[i].Headline, tags, shares is null ? null : shares.GetValueOrDefault(c.Player.Id));
        }).ToList();

        var positions = new List<PositionAdvice>();
        foreach (var position in Positions.All)
        {
            var best = ranked.FirstOrDefault(c => c.Player.Position == position);
            if (best is null) continue;
            var cost = best.WaitShortfall ?? 0;
            var backedPosition = top.Count > 0 && (position == top[0].Player.Position || position == rival);
            positions.Add(new PositionAdvice(position, best, cost, cost >= Explainer.NoticeableCost, best.WaitAlternatives ?? [], backedPosition, Explainer.IsReach(best)));
        }

        // the reach cost is what keeps these out of the ranking, so rank them without it (score + penalty is the same score with the cost off)
        var shown = top.Select(c => c.Player.Id).ToHashSet();
        var pastTheWall = ranked
            .Where(c => !shown.Contains(c.Player.Id) && c.ReachSigmas <= PastTheWallSigmas && c.Vor > 0)
            .OrderByDescending(c => c.Score + c.ReachPenalty)
            .Take(PastTheWallCount)
            .Select(c => new PastTheWallPlayer(c.Player, (c.Player.Player.Adp ?? pick) - pick))
            .ToList();

        return new Advice(pick, state.NextPick(teamIndex), recommended, positions, pastTheWall, LineupValue.Replacement(state), rival);
    }

    /// <summary>The position of the best pick at another position whose <see cref="RankedPick.TopShare"/> is at least <see cref="CloseCallTopShare"/>; null without shares or without such a pick.</summary>
    static Position? ShareRival(IReadOnlyList<ValueCandidate> top, IReadOnlyDictionary<string, double>? shares)
    {
        if (shares is null || top.Count < 2) return null;
        return top.Skip(1).FirstOrDefault(c => c.Player.Position != top[0].Player.Position && shares.GetValueOrDefault(c.Player.Id) >= CloseCallTopShare)?.Player.Position;
    }

    /// <summary>
    /// Player id to the share of <paramref name="samples"/> re-rankings in which he is the first pick the advice would back, when every ADP is moved by a random offset
    /// (SD <see cref="ConfidenceJitterPicks"/> picks, fixed by the state so the same state always gives the same shares). Drafted players are replayed in order so the rosters are the real ones.
    /// </summary>
    static Dictionary<string, double> TopShares(DraftState state, int teamIndex, ReachSettings reach, NeedSettings need, WaitSettings wait, int samples)
    {
        var everyone = state.Available.Concat(state.History.Select(h => h.Player)).ToList();
        var rng = new Random(state.OverallPick * 7919 + teamIndex);
        double Normal() => Math.Sqrt(-2 * Math.Log(1 - rng.NextDouble())) * Math.Cos(2 * Math.PI * rng.NextDouble());
        var offsets = Enumerable.Range(0, samples).Select(_ => everyone.Select(_ => ConfidenceJitterPicks * Normal()).ToArray()).ToList();
        var first = new string?[samples];
        Parallel.For(0, samples, i =>
        {
            var pool = everyone.Select((p, k) => p.Player.Adp is { } adp ? p with { Player = p.Player with { Adp = Math.Max(0.5, adp + offsets[i][k]) } } : p).ToList();
            var twin = new DraftState(pool, state.League);
            foreach (var pick in state.History) twin.Draft(pick.Player.Id);
            var ranked = ValueRecommender.Rank(twin, reach, need, teamIndex, wait);
            first[i] = (ranked.FirstOrDefault(c => !Explainer.IsReach(c)) ?? ranked.FirstOrDefault())?.Player.Id;
        });
        return first.Where(id => id is not null).GroupBy(id => id!).ToDictionary(g => g.Key, g => g.Count() / (double)samples);
    }
}
