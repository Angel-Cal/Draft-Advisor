using DraftBot.Core;

namespace DraftBot.Sim;

public static class LineupScorer
{
    /// <summary>
    /// Actual season PPR of the best legal lineup: each position's best players fill its dedicated slots, then the best
    /// leftover RB/WR/TE fill FLEX. Season totals only, so byes and weekly lineup changes are ignored.
    /// </summary>
    public static double Score(Roster roster, LeagueSettings league) =>
        LineupValue.BestTotal(league, position => roster.At(position).Select(Actual));

    /// <summary>
    /// Weekly scoring when <paramref name="weekly"/> is set and every rostered player has weekly points, else season totals.
    /// </summary>
    public static double Score(Roster roster, LeagueSettings league, bool weekly) =>
        weekly && roster.Picks.All(p => p.Player.WeeklyPpr is not null) ? ScoreWeekly(roster, league) : Score(roster, league);

    /// <summary>
    /// Sum over the 18 weeks of the best legal lineup from the players who played that week (chosen with hindsight). A bye, an injury
    /// or an inactive week means no points, so depth at a position is worth something when a starter is out.
    /// </summary>
    public static double ScoreWeekly(Roster roster, LeagueSettings league) => WeeklyScores(roster, league).Sum();

    /// <summary>The best legal lineup's points in each week (index 0 = week 1), from the players who played that week.</summary>
    public static double[] WeeklyScores(Roster roster, LeagueSettings league)
    {
        var weeks = roster.Picks.Max(p => p.Player.WeeklyPpr!.Count);
        return Enumerable.Range(0, weeks).Select(week => LineupValue.BestTotal(league, position =>
            roster.At(position).Select(p => p.Player.WeeklyPpr![week]).Where(x => x is not null).Select(x => x!.Value))).ToArray();
    }

    /// <summary>Whether every rostered player has weekly points, i.e. weekly lineups can be scored.</summary>
    public static bool HasWeekly(Roster roster) => roster.Picks.Count > 0 && roster.Picks.All(p => p.Player.WeeklyPpr is not null);

    static double Actual(ValuedPlayer player) =>
        player.Player.ActualPpr ?? throw new InvalidOperationException($"{player.Player.PlayerName} has no actual_ppr (not a backtest file)");
}
