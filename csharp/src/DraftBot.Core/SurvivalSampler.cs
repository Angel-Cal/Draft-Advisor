namespace DraftBot.Core;

/// <summary>
/// What the recommender assumes about the other drafters: they take the player with the best "pick key" (ADP plus a personal noise draw whose SD grows with ADP)
/// among those they may take. Position caps and forced starter fills are the same rules the simulator's opponents follow, and the ones a real league tends
/// to follow in spirit; <see cref="NoRules"/> drops them.
/// </summary>
/// <param name="NoiseBase">SD of a drafter's noise at ADP 0, in picks.</param>
/// <param name="NoisePerAdp">Extra SD per ADP slot.</param>
/// <param name="MaxQb">Most QBs a drafter takes.</param>
/// <param name="MaxTe">Most TEs a drafter takes.</param>
/// <param name="ForceStartersAfterRound">After this round a drafter with an open starter slot fills one of them.</param>
public sealed record OpponentModel(double NoiseBase = 1.0, double NoisePerAdp = 0.12, int MaxQb = 2, int MaxTe = 2, int ForceStartersAfterRound = 10)
{
    /// <summary>The same noise, but drafters take whoever they like best: no caps and no forced fills.</summary>
    public static OpponentModel NoRules { get; } = new(MaxQb: int.MaxValue, MaxTe: int.MaxValue, ForceStartersAfterRound: int.MaxValue);

    public double NoiseSd(double adp) => NoiseBase + NoisePerAdp * adp;

    /// <summary>The player this drafter takes now: the best by <paramref name="key"/> (lower is better) among those the caps and forced fills allow.</summary>
    public ValuedPlayer Choose(DraftState state, int team, Func<ValuedPlayer, double> key)
    {
        var roster = state.Teams[team];
        var allowed = Positions.All.Where(p => roster.At(p).Count < Cap(p)).ToHashSet();
        if (state.Round > ForceStartersAfterRound)
        {
            var open = Positions.All.Where(p => roster.At(p).Count < state.League.Starters(p)).ToHashSet();
            if (open.Count > 0) allowed.IntersectWith(open);
        }
        var legal = state.Available.Where(p => allowed.Contains(p.Position)).ToList();
        return (legal.Count > 0 ? legal : state.Available).MinBy(key) ?? throw new InvalidOperationException("no player left to take");
    }

    internal int Cap(Position position) => position switch
    {
        Position.QB => MaxQb,
        Position.TE => MaxTe,
        _ => int.MaxValue,
    };
}

/// <summary>
/// Survival by simulation: who is still there at a later pick, found by playing out the other drafters' picks in between many times. Unlike the
/// ADP-only normal model it knows each drafter's roster, so a QB nobody still needs lasts, and a position the drafters ahead of me all need goes fast.
/// </summary>
public static class SurvivalSampler
{
    /// <summary>
    /// P(each available player is still there at overall pick <paramref name="untilPick"/> (1-based)), assuming every pick after the current one and before
    /// that pick is made by a drafter following <paramref name="model"/>. The current pick (mine) is ignored. Deterministic for a given state.
    /// </summary>
    public static Dictionary<string, double> Survival(DraftState state, int untilPick, OpponentModel model, int samples)
    {
        var available = state.Available;
        var n = available.Count;
        var league = state.League;
        var unranked = available.Concat(state.Teams.SelectMany(t => t.Picks)).Max(p => p.Player.Adp ?? 0) + 1;
        var adp = available.Select(p => p.Player.Adp ?? unranked).ToArray();
        var positions = Positions.All;
        var position = available.Select(p => Array.IndexOf(positions, p.Position)).ToArray();

        var picks = new List<(int Team, int Round)>();
        for (var number = state.OverallPick + 2; number < untilPick && number <= league.Teams * league.RosterSize; number++)
        {
            var overall = number - 1;
            var inRound = overall % league.Teams;
            var roundIndex = overall / league.Teams;
            picks.Add((roundIndex % 2 == 1 ? league.Teams - 1 - inRound : inRound, roundIndex + 1));
        }

        var baseCounts = state.Teams.Select(t => positions.Select(p => t.At(p).Count).ToArray()).ToArray();
        var survived = new int[n];
        for (var sample = 0; sample < samples; sample++)
        {
            var random = new Random(state.OverallPick * 10007 + sample);
            var keys = new double[league.Teams][];
            var counts = baseCounts.Select(c => (int[])c.Clone()).ToArray();
            var taken = new bool[n];
            foreach (var (team, round) in picks)
            {
                keys[team] ??= Enumerable.Range(0, n).Select(i => adp[i] + model.NoiseSd(adp[i]) * Gaussian(random)).ToArray();
                var allowed = positions.Select((p, index) => counts[team][index] < model.Cap(p)).ToArray();
                if (round > model.ForceStartersAfterRound)
                {
                    var open = positions.Select((p, index) => counts[team][index] < league.Starters(p)).ToArray();
                    if (open.Any(o => o)) allowed = allowed.Zip(open, (a, o) => a && o).ToArray();
                }
                var choice = Best(keys[team], taken, position, allowed) ?? Best(keys[team], taken, position, null);
                if (choice is not { } picked) break;
                taken[picked] = true;
                counts[team][position[picked]]++;
            }
            for (var i = 0; i < n; i++)
                if (!taken[i]) survived[i]++;
        }
        return Enumerable.Range(0, n).ToDictionary(i => available[i].Id, i => survived[i] / (double)samples);
    }

    static int? Best(double[] key, bool[] taken, int[] position, bool[]? allowed)
    {
        int? best = null;
        for (var i = 0; i < key.Length; i++)
        {
            if (taken[i] || (allowed is not null && !allowed[position[i]])) continue;
            if (best is null || key[i] < key[best.Value]) best = i;
        }
        return best;
    }

    static double Gaussian(Random random)
    {
        var u1 = 1.0 - random.NextDouble();
        var u2 = random.NextDouble();
        return Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2);
    }
}
