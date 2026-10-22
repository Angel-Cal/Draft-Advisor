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

    static double Actual(ValuedPlayer player) =>
        player.Player.ActualPpr ?? throw new InvalidOperationException($"{player.Player.PlayerName} has no actual_ppr (not a backtest file)");
}
