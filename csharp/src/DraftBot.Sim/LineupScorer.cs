using DraftBot.Core;

namespace DraftBot.Sim;

public static class LineupScorer
{
    /// <summary>
    /// Actual season PPR of the best legal lineup: each position's best players fill its dedicated slots, then the best
    /// leftover RB/WR/TE fill FLEX. Season totals only, so byes and weekly lineup changes are ignored.
    /// </summary>
    public static double Score(Roster roster, LeagueSettings league)
    {
        var total = 0.0;
        var leftovers = new List<double>();
        foreach (var position in Positions.All)
        {
            var points = roster.At(position).Select(Actual).OrderByDescending(x => x).ToList();
            total += points.Take(league.Starters(position)).Sum();
            if (Positions.FlexEligible.Contains(position)) leftovers.AddRange(points.Skip(league.Starters(position)));
        }
        return total + leftovers.OrderByDescending(x => x).Take(league.Flex).Sum();
    }

    /// <summary>
    /// Weekly scoring when <paramref name="weekly"/> is set and every rostered player has weekly points, else season totals.
    /// </summary>
    public static double Score(Roster roster, LeagueSettings league, bool weekly) =>
        weekly && roster.Picks.All(p => p.Player.WeeklyPpr is not null) ? ScoreWeekly(roster, league) : Score(roster, league);

    /// <summary>
    /// Sum over the 18 weeks of the best legal lineup from the players who played that week (chosen with hindsight). A bye, an injury
    /// or an inactive week means no points, so depth at a position is worth something when a starter is out.
    /// </summary>
    public static double ScoreWeekly(Roster roster, LeagueSettings league)
    {
        var weeks = roster.Picks.Max(p => p.Player.WeeklyPpr!.Count);
        var total = 0.0;
        for (var week = 0; week < weeks; week++)
        {
            var leftovers = new List<double>();
            foreach (var position in Positions.All)
            {
                var points = roster.At(position).Select(p => p.Player.WeeklyPpr![week]).Where(x => x is not null).Select(x => x!.Value)
                    .OrderByDescending(x => x).ToList();
                total += points.Take(league.Starters(position)).Sum();
                if (Positions.FlexEligible.Contains(position)) leftovers.AddRange(points.Skip(league.Starters(position)));
            }
            total += leftovers.OrderByDescending(x => x).Take(league.Flex).Sum();
        }
        return total;
    }

    static double Actual(ValuedPlayer player) =>
        player.Player.ActualPpr ?? throw new InvalidOperationException($"{player.Player.PlayerName} has no actual_ppr (not a backtest file)");
}
