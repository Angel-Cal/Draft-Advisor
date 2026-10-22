namespace DraftBot.Core;

/// <summary>
/// Replacement level per position from the league's lineup. Each team's dedicated starters are taken first; the
/// league's FLEX slots then go to the best remaining RB/WR/TE by projection. The replacement player at a position is
/// the best one who does not start.
/// </summary>
public static class ReplacementLevel
{
    /// <summary>How many players at each position start somewhere in the league (dedicated slots plus FLEX).</summary>
    public static Dictionary<Position, int> StarterCounts(IReadOnlyList<Player> pool, LeagueSettings league)
    {
        var counts = Positions.All.ToDictionary(p => p, p => league.Teams * league.Starters(p));

        var flexCandidates = Positions.FlexEligible
            .SelectMany(p => ByProjection(pool, p).Skip(counts[p]))
            .OrderByDescending(player => player.ProjectedPpr)
            .Take(league.Teams * league.Flex);
        foreach (var player in flexCandidates) counts[player.Position]++;
        return counts;
    }

    /// <summary>Projected points of the first non-starter at each position (the last player if the pool runs out).</summary>
    public static Dictionary<Position, double> Points(IReadOnlyList<Player> pool, LeagueSettings league)
    {
        var starters = StarterCounts(pool, league);
        var points = new Dictionary<Position, double>();
        foreach (var position in Positions.All)
        {
            var ranked = ByProjection(pool, position);
            if (ranked.Count == 0) throw new InvalidOperationException($"pool has no {position} players");
            points[position] = ranked[Math.Min(starters[position], ranked.Count - 1)].ProjectedPpr;
        }
        return points;
    }

    static List<Player> ByProjection(IReadOnlyList<Player> pool, Position position) =>
        pool.Where(p => p.Position == position).OrderByDescending(p => p.ProjectedPpr).ToList();
}
