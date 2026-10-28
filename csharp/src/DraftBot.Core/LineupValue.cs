namespace DraftBot.Core;

/// <summary>
/// Projected points of the best legal lineup a roster could field. Open starter slots are filled by "ghost" replacement-level
/// players (the free agent you could always pick up), so a player's gain is measured over replacement, not over zero.
/// </summary>
public static class LineupValue
{
    /// <summary>Replacement level per position, in projected points, recovered from any valued player (VOR = projection - replacement).</summary>
    public static Dictionary<Position, double> Replacement(DraftState state)
    {
        var result = new Dictionary<Position, double>();
        var everyone = state.Available.Concat(state.Teams.SelectMany(t => t.Picks));
        foreach (var position in Positions.All)
        {
            var any = everyone.FirstOrDefault(p => p.Position == position);
            result[position] = any is null ? 0 : any.Player.ProjectedPpr - any.Vor;
        }
        return result;
    }

    /// <summary>
    /// Waiver level per position: the best projection among players the league will not draft (ADP beyond teams x roster size), never above
    /// replacement level. This is what a bench player is really competing with: whoever you could pick up for free when a starter is out.
    /// </summary>
    public static Dictionary<Position, double> Waiver(DraftState state, IReadOnlyDictionary<Position, double> replacement)
    {
        var draftable = state.League.Teams * state.League.RosterSize;
        var everyone = state.Available.Concat(state.Teams.SelectMany(t => t.Picks)).ToList();
        return Positions.All.ToDictionary(position => position, position =>
        {
            var undrafted = everyone.Where(p => p.Position == position && (p.Player.Adp ?? double.MaxValue) > draftable)
                .Select(p => p.Player.ProjectedPpr).DefaultIfEmpty(replacement[position]).Max();
            return Math.Min(undrafted, replacement[position]);
        });
    }

    /// <summary>
    /// Best lineup: each position's dedicated slots take its best players, then the FLEX slots take the best of the leftover
    /// RB/WR/TE. Ghosts at replacement level compete for every slot, so a player below replacement adds nothing.
    /// </summary>
    public static double Best(IEnumerable<ValuedPlayer> players, LeagueSettings league, IReadOnlyDictionary<Position, double> replacement)
    {
        var list = players.ToList();
        var total = 0.0;
        var leftovers = new List<double>();
        foreach (var position in Positions.All)
        {
            var slots = league.Starters(position);
            var candidates = list.Where(p => p.Position == position).Select(p => p.Player.ProjectedPpr)
                .Concat(Enumerable.Repeat(replacement[position], slots + league.Flex))
                .OrderByDescending(x => x).ToList();
            total += candidates.Take(slots).Sum();
            if (Positions.FlexEligible.Contains(position)) leftovers.AddRange(candidates.Skip(slots));
        }
        total += leftovers.OrderByDescending(x => x).Take(league.Flex).Sum();
        return total;
    }

    /// <summary>
    /// What a roster earns in bye weeks beyond its season-total lineup. Each week's lineup is the best one among the players not on bye, a player scoring
    /// his projection / 17 in each week he plays and open slots filled by replacement-level pickups every week, so the weekly lineups add up to
    /// <see cref="Best"/> plus this cover. Adding a player changes it by the points his presence adds in other players' bye weeks (and keeps a bye hole of his own covered).
    /// </summary>
    public static double ByeCover(IReadOnlyList<ValuedPlayer> roster, LeagueSettings league, IReadOnlyDictionary<Position, double> replacement, ByeSchedule byes)
    {
        const double PlayedWeeks = 17;
        var full = Best(roster, league, replacement);
        var byeWeeks = roster.Select(p => byes.WeekOf(p.Player.Team)).Where(w => w is not null).Select(w => w!.Value).Distinct().ToList();
        var total = full * (ByeSchedule.Weeks - byeWeeks.Count);
        foreach (var week in byeWeeks)
            total += Best(roster.Where(p => byes.WeekOf(p.Player.Team) != week), league, replacement);
        return total / PlayedWeeks - full;
    }

    /// <summary>How many points <paramref name="candidate"/> adds to the roster's best lineup (0 if he would not start).</summary>
    public static double Gain(IReadOnlyList<ValuedPlayer> roster, ValuedPlayer candidate, LeagueSettings league,
        IReadOnlyDictionary<Position, double> replacement) =>
        Best(roster.Append(candidate), league, replacement) - Best(roster, league, replacement);
}
