using System.Globalization;
using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>Every pick of the drafter's own team, for analysis outside the Sim (`pick-log`: which round and which players each strategy takes).</summary>
public static class PickLog
{
    /// <summary>
    /// Runs each strategy from every slot against the same seeded opponents (as `Experiment.Run` does) and writes one CSV row per pick of
    /// the drafter's team: season, seed, slot, strategy, round, player, position, ADP, projection, actual points, and the team's starter points and title odds.
    /// </summary>
    public static int Write(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, IReadOnlyList<IDraftStrategy> strategies,
        int seeds, string path, int firstSeed = 0)
    {
        var pools = files.ToDictionary(f => f.Key,
            f => Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));
        var jobs = (from season in files.Keys.Order()
                    from seed in Enumerable.Range(firstSeed, seeds)
                    from slot in Enumerable.Range(0, settings.League.Teams)
                    select (season, seed, slot)).ToList();
        var lines = new string[jobs.Count][];
        string F(double? v) => v?.ToString("F2", CultureInfo.InvariantCulture) ?? "";
        Parallel.For(0, jobs.Count, i =>
        {
            var (season, seed, slot) = jobs[i];
            lines[i] = strategies.SelectMany(strategy =>
            {
                var result = DraftSimulator.Run(pools[season], settings, slot, strategy, seed);
                return result.MyPicks.Select((p, round) => string.Join(',', season, seed, slot + 1, strategy.Name, round + 1, p.Id,
                    p.Position, F(p.Player.Adp), F(p.Player.ProjectedPpr), F(p.Player.ActualPpr), F(result.Points), F(result.Odds?.TitleProbability)));
            }).ToArray();
        });
        File.WriteAllLines(path, lines.SelectMany(l => l).Prepend("season,seed,slot,strategy,round,player_id,position,adp,projected,actual,team_points,team_title"));
        return lines.Sum(l => l.Length);
    }
}
