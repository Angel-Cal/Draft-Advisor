namespace DraftBot.Core;

/// <summary>
/// Rollout policy improvement. The best few candidates by the base recommender's score are each tried: take him, then play the rest of the draft forward with
/// the other drafters sampled from <see cref="OpponentModel"/> and my own later picks made by the base recommender, and value the finished roster. The candidate
/// whose rosters come out best on average (the same sampled opponents for every candidate) is the pick. It needs no waiting bonus: what is left for later is
/// what the sampled drafters leave.
/// </summary>
/// <param name="Candidates">How many of the base recommender's best candidates get rolled out.</param>
/// <param name="Samples">Rollouts per candidate.</param>
/// <param name="Opponents">Assumed drafters; null means <c>new OpponentModel()</c>.</param>
public sealed record RolloutSettings(int Candidates = 5, int Samples = 20, OpponentModel? Opponents = null)
{
    public OpponentModel Model => Opponents ?? new OpponentModel();
}

public static class Rollout
{
    /// <param name="Player">The candidate.</param>
    /// <param name="Value">Mean value of the finished roster over the rollouts (points: best lineup plus bench value); the base score when he was not rolled out.</param>
    /// <param name="BaseScore">The base recommender's score for him.</param>
    public sealed record Result(ValuedPlayer Player, double Value, double BaseScore);

    /// <summary>
    /// The rolled-out candidates best first. <paramref name="allowed"/> limits the candidates (for example to the legal picks); <paramref name="baseWait"/> is the waiting
    /// bonus of the base recommender, which also makes my own later picks inside the rollouts.
    /// </summary>
    public static IReadOnlyList<Result> Rank(DraftState state, ReachSettings reach, NeedSettings need, int teamIndex, RolloutSettings settings,
        Func<ValuedPlayer, bool>? allowed = null, WaitSettings? baseWait = null)
    {
        var candidates = ValueRecommender.Rank(state, reach, need, teamIndex, baseWait)
            .Where(c => allowed?.Invoke(c.Player) ?? true).Take(Math.Max(1, settings.Candidates)).ToList();
        if (candidates.Count <= 1) return candidates.Select(c => new Result(c.Player, c.Score, c.Score)).ToList();

        var replacement = LineupValue.Replacement(state);
        var waiver = LineupValue.Waiver(state, replacement);
        var model = settings.Model;
        var teams = state.League.Teams;
        var everyone = state.Available.OrderBy(p => p.Id, StringComparer.Ordinal).ToList();
        var unranked = state.Available.Concat(state.Teams.SelectMany(t => t.Picks)).Max(p => p.Player.Adp ?? 0) + 1;

        var totals = new double[candidates.Count];
        for (var sample = 0; sample < settings.Samples; sample++)
        {
            var keys = new Dictionary<string, double>?[teams];             // each drafter's pick keys for this sample, shared by every candidate's rollout
            Dictionary<string, double> KeysOf(int team) => keys[team] ??= DrawKeys(everyone, unranked, model, new Random((state.OverallPick * 10007 + sample) * 131 + team));
            for (var i = 0; i < candidates.Count; i++)
            {
                var clone = state.Clone();
                clone.Draft(candidates[i].Player.Id);
                for (var guard = clone.League.Teams * clone.League.RosterSize; !clone.IsComplete && clone.Teams[teamIndex].Picks.Count < clone.League.RosterSize; guard--)
                {
                    if (guard < 0) throw new InvalidOperationException("the rollout made no progress");
                    var next = clone.CurrentTeam == teamIndex
                        ? ValueRecommender.Rank(clone, reach, need, teamIndex, baseWait)[0].Player
                        : model.Choose(clone, clone.CurrentTeam, p => KeysOf(clone.CurrentTeam)[p.Id]);
                    clone.Draft(next.Id);
                }
                totals[i] += FinalValue(clone.Teams[teamIndex].Picks, clone.League, replacement, waiver, need);
            }
        }
        return candidates.Select((c, i) => new Result(c.Player, totals[i] / settings.Samples, c.Score)).OrderByDescending(r => r.Value).ToList();
    }

    static Dictionary<string, double> DrawKeys(IReadOnlyList<ValuedPlayer> players, double unranked, OpponentModel model, Random random)
    {
        var keys = new Dictionary<string, double>(players.Count);
        foreach (var player in players)
        {
            var adp = player.Player.Adp ?? unranked;
            var u1 = 1.0 - random.NextDouble();
            var u2 = random.NextDouble();
            keys[player.Id] = adp + model.NoiseSd(adp) * Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2);
        }
        return keys;
    }

    /// <summary>
    /// What a finished roster is worth in points: its best lineup plus the bench value the recommender itself gives (the structural backup weight times the option
    /// value above the waiver level, counting only players who do not start).
    /// </summary>
    public static double FinalValue(IReadOnlyList<ValuedPlayer> roster, LeagueSettings league, IReadOnlyDictionary<Position, double> replacement,
        IReadOnlyDictionary<Position, double> waiver, NeedSettings need)
    {
        var lineup = LineupValue.Best(roster, league, replacement);
        var bench = 0.0;
        foreach (var group in roster.GroupBy(p => p.Position))
        {
            var backups = group.Where(p => LineupValue.Best(roster.Where(q => q.Id != p.Id), league, replacement) >= lineup - 1e-9)       // removing him changes nothing: he does not start
                .OrderByDescending(p => p.Player.ProjectedPpr).ToList();
            for (var k = 1; k <= backups.Count; k++)
            {
                var weight = need.MissProbability is null ? need.BenchFraction
                    : need.BenchFraction * NeedSettings.AtLeast(k, NeedSettings.BackupSlots(group.Key, league), need.MissProbability.Value);
                var p = backups[k - 1];
                bench += weight * (need.OptionValue ? NeedSettings.ExpectedExcess(p.Player.ProjectedPpr, p.Rmse, waiver[group.Key]) : Math.Max(0, p.Vor));
            }
        }
        return lineup + bench;
    }
}
