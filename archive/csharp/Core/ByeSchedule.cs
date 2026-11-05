namespace DraftBot.Core;

/// <summary>
/// Each team's bye week (1-based, 1-18). The schedule is public before a draft, but the projection files do not carry it yet, so for backtests it is read
/// off the weekly points: the week in which none of a team's players scored.
/// </summary>
public sealed class ByeSchedule
{
    /// <summary>Weeks in a regular season, byes included.</summary>
    public const int Weeks = 18;
    const int MinPlayers = 3;           // fewer players than this and an all-empty week says little about the team
    const int FirstByeIndex = 3;        // byes fall in weeks 4-14 (0-based 3-13)
    const int LastByeIndex = 13;

    readonly IReadOnlyDictionary<string, int> weeks;

    public ByeSchedule(IReadOnlyDictionary<string, int> weeks) => this.weeks = weeks;

    /// <summary>A schedule with no known byes (live files carry no weekly points).</summary>
    public static ByeSchedule Empty { get; } = new(new Dictionary<string, int>());

    public int Count => weeks.Count;

    /// <summary>The team's bye week, or null when it is unknown.</summary>
    public int? WeekOf(string team) => weeks.TryGetValue(team, out var week) ? week : null;

    /// <summary>
    /// Infers each team's bye from weekly points: the one week in the bye window (weeks 4-14) with the fewest scorers on the team, if it is unique and has
    /// at most one scorer in six players (a player traded mid-season can carry points from his old team's week). Teams with fewer than three players with
    /// weekly data, or with no such week, are left out.
    /// </summary>
    public static ByeSchedule Infer(IEnumerable<Player> players)
    {
        var result = new Dictionary<string, int>();
        foreach (var team in players.Where(p => p.WeeklyPpr is { Count: Weeks } && p.Team != "FA").GroupBy(p => p.Team))
        {
            var roster = team.ToList();
            if (roster.Count < MinPlayers) continue;
            var scorers = Enumerable.Range(FirstByeIndex, LastByeIndex - FirstByeIndex + 1).Select(i => (Index: i, Count: roster.Count(p => p.WeeklyPpr![i] is not null))).ToList();
            var fewest = scorers.Min(w => w.Count);
            if (scorers.Count(w => w.Count == fewest) == 1 && fewest <= Math.Max(1, roster.Count / 6)) result[team.Key] = scorers.First(w => w.Count == fewest).Index + 1;
        }
        return new ByeSchedule(result);
    }
}
