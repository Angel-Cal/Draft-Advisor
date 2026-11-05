using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>How the drafter being evaluated chooses. <paramref name="legal"/> already respects the roster rules.</summary>
public interface IDraftStrategy
{
    string Name { get; }
    ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal);
}

/// <summary>Takes the best ADP available, no noise: an opponent who always agrees with the market.</summary>
public sealed class AdpStrategy : IDraftStrategy
{
    public string Name => "adp";

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        var unranked = OpponentBot.UnrankedAdp(state.Available);
        return legal.MinBy(p => p.Player.Adp ?? unranked)!;
    }
}

/// <summary>Takes the highest value over replacement available.</summary>
public sealed class VorStrategy : IDraftStrategy
{
    public string Name => "vor";

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal) =>
        legal.MaxBy(p => p.Vor)!;
}

/// <summary>
/// The ported Phase 1 recommender: its best legal suggestion at the chosen position, or the best VOR if the roster rules
/// rule out everything it suggests.
/// </summary>
public sealed class RecommenderStrategy : IDraftStrategy
{
    public string Name => "recommender";

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        var suggested = BaselineRecommender.Recommend(state, team).Candidates
            .Select(c => c.Player).FirstOrDefault(p => legal.Contains(p));
        return suggested ?? legal.MaxBy(p => p.Vor)!;
    }
}

/// <summary>The recommender with the ADP-reach penalty and cap (see <see cref="ReachSettings"/>); otherwise identical to the baseline.</summary>
public sealed class WindowedRecommenderStrategy(string name, ReachSettings reach) : IDraftStrategy
{
    public string Name => name;
    public ReachSettings Reach => reach;

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        var suggested = BaselineRecommender.Recommend(state, team, reach).Candidates
            .Select(c => c.Player).FirstOrDefault(p => legal.Contains(p));
        return suggested ?? legal.MaxBy(p => p.Vor)!;
    }
}

/// <summary>The single-score recommender (<see cref="ValueRecommender"/>): its best legal suggestion, else the best VOR.</summary>
public sealed class ValueRecommenderStrategy(string name, ReachSettings reach, NeedSettings? need = null, WaitSettings? wait = null, LookaheadSettings? lookahead = null) : IDraftStrategy
{
    public string Name => name;
    public ReachSettings Reach => reach;
    public NeedSettings? Need => need;
    public WaitSettings? Wait => wait;
    public LookaheadSettings? Lookahead => lookahead;

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        var allowed = legal.Select(p => p.Id).ToHashSet();
        return ValueRecommender.Rank(state, reach, need, team, wait, lookahead).Select(c => c.Player).FirstOrDefault(p => allowed.Contains(p.Id))
               ?? legal.MaxBy(p => p.Vor)!;
    }
}

/// <summary>
/// Another strategy with a QB timing rule (LOG 2026-11-04): before round <paramref name="notBeforeRound"/> it may not take a QB, except one ranked within the
/// season's top <paramref name="allowTopRanks"/> QBs by ADP (0 = no exception). If the rule would leave nothing legal, the rule is dropped for that pick.
/// </summary>
public sealed class QbTimingStrategy(string name, IDraftStrategy inner, int notBeforeRound, int allowTopRanks = 0) : IDraftStrategy
{
    public string Name => name;

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        if (state.Round >= notBeforeRound) return inner.Pick(state, team, legal);
        var filtered = legal.Where(p => p.Position != Position.QB || QbAdpRank(state, p) <= allowTopRanks).ToList();
        return inner.Pick(state, team, filtered.Count > 0 ? filtered : legal);
    }

    /// <summary>1-based rank of a QB by ADP among every QB in the season's pool (still available or already drafted); a QB with no ADP ranks last.</summary>
    public static int QbAdpRank(DraftState state, ValuedPlayer qb)
    {
        var adp = qb.Player.Adp ?? double.MaxValue;
        return 1 + state.Available.Concat(state.History.Select(h => h.Player))
            .Count(p => p.Position == Position.QB && p.Id != qb.Id && (p.Player.Adp ?? double.MaxValue) < adp);
    }
}

/// <summary>How a user picks among the recommendation cards the app shows.</summary>
public enum CardChoice
{
    /// <summary>Always the first card.</summary>
    First,
    /// <summary>Any shown card, each equally likely.</summary>
    Random,
    /// <summary>The shown card with the lowest ADP: a user who leans to the market's favourite.</summary>
    LowestAdp,
}

/// <summary>
/// A user of the app (LOG 2026-11-04): takes one of the first <see cref="ShownCards"/> recommendations of <see cref="DraftAdvisor.Advise"/> (reaches already left out)
/// by <paramref name="choice"/>; the best legal player of the adopted ranking when no shown card is legal. Random choices are seeded by the draft's own picks so a run is repeatable.
/// </summary>
public sealed class CardChoiceStrategy(string name, CardChoice choice) : IDraftStrategy
{
    /// <summary>Cards on the draft screen.</summary>
    public const int ShownCards = 3;

    public string Name => name;

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        var allowed = legal.Select(p => p.Id).ToHashSet();
        var advice = DraftAdvisor.Advise(state, team, confidenceSamples: 0);
        var cards = advice.Recommended.Take(ShownCards).Select(r => r.Candidate.Player).Where(p => allowed.Contains(p.Id)).ToList();
        if (cards.Count == 0)
            return ValueRecommender.Rank(state, ValueRecommender.DefaultReach, NeedSettings.Default, team, ValueRecommender.DefaultWait)
                       .Select(c => c.Player).FirstOrDefault(p => allowed.Contains(p.Id)) ?? legal.MaxBy(p => p.Vor)!;
        return choice switch
        {
            CardChoice.First => cards[0],
            CardChoice.LowestAdp => cards.MinBy(p => p.Player.Adp ?? double.MaxValue)!,
            _ => cards[(int)(DraftHash(state, team) % (ulong)cards.Count)],
        };
    }

    /// <summary>A stable hash of the picks made so far and the team on the clock (FNV-1a; string.GetHashCode changes between runs).</summary>
    static ulong DraftHash(DraftState state, int team)
    {
        var hash = 14695981039346656037UL;
        void Mix(string s) { foreach (var ch in s) { hash ^= ch; hash *= 1099511628211UL; } }
        foreach (var pick in state.History) Mix(pick.Player.Id);
        Mix(team.ToString(System.Globalization.CultureInfo.InvariantCulture));
        return hash;
    }
}

/// <summary>The recommender with a rollout on top (see <see cref="Rollout"/>): the base recommender proposes, simulated completions of the draft decide.</summary>
public sealed class RolloutStrategy(string name, ReachSettings reach, NeedSettings need, RolloutSettings rollout, WaitSettings? baseWait = null) : IDraftStrategy
{
    public string Name => name;

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        var allowed = legal.Select(p => p.Id).ToHashSet();
        return Rollout.Rank(state, reach, need, team, rollout, p => allowed.Contains(p.Id), baseWait).Select(r => r.Player).FirstOrDefault()
               ?? legal.MaxBy(p => p.Vor)!;
    }
}
