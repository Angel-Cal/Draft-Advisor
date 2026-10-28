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
