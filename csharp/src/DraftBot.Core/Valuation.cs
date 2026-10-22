namespace DraftBot.Core;

/// <summary>A player plus everything the recommender derives from the pool and the league settings.</summary>
public sealed record ValuedPlayer(
    Player Player,
    double Vor,
    double Ceiling,
    double Floor,
    bool AvailabilityFlag,
    double VorRank,
    double ValueGap,
    int Tier)
{
    public string Id => Player.PlayerId;
    public Position Position => Player.Position;
}

/// <param name="TierGapRmse">A new tier starts where the projection drops by more than this many position-RMSEs.</param>
public sealed record ValuationSettings(double TierGapRmse = 0.1);

public static class Valuator
{
    /// <summary>Values the whole pool. Result is ordered by VOR, best first.</summary>
    public static List<ValuedPlayer> Value(IReadOnlyList<Player> players, IReadOnlyDictionary<Position, double> rmse,
        LeagueSettings league, ValuationSettings? settings = null)
    {
        league.Validate();
        settings ??= new ValuationSettings();
        var replacement = ReplacementLevel.Points(players, league);
        var tiers = Tiers(players, rmse, settings.TierGapRmse);

        var vor = players.ToDictionary(p => p.PlayerId, p => p.ProjectedPpr - replacement[p.Position]);
        var unrankedAdp = players.Max(p => p.Adp ?? 0) + 1;       // no ADP: treated as last in the pool
        var ordered = players.OrderByDescending(p => vor[p.PlayerId]).ToList();

        var valued = new List<ValuedPlayer>(ordered.Count);
        foreach (var player in ordered)
        {
            var (ceiling, floor, availability) = CeilingFloor(player, rmse[player.Position]);
            var vorRank = 1 + ordered.Count(other => vor[other.PlayerId] > vor[player.PlayerId]);   // ties share the best rank
            valued.Add(new ValuedPlayer(player, vor[player.PlayerId], ceiling, floor, availability, vorRank,
                (player.Adp ?? unrankedAdp) - vorRank, tiers[player.PlayerId]));
        }
        return valued;
    }

    /// <summary>
    /// Ceiling is projection + RMSE. A player back from a big games drop (availability flag) gets the higher of that and a
    /// full-health pace (17 / games), capped at double the projection.
    /// </summary>
    public static (double Ceiling, double Floor, bool Availability) CeilingFloor(Player player, double rmse)
    {
        var availability = player.Games < 13 && player.GamesDelta < -5;
        var rmseCeiling = player.ProjectedPpr + rmse;
        var ceiling = rmseCeiling;
        if (availability)
        {
            var healthy = Math.Min(player.ProjectedPpr * (17.0 / player.Games), player.ProjectedPpr * 2);
            ceiling = Math.Max(healthy, rmseCeiling);
        }
        return (ceiling, Math.Max(player.ProjectedPpr - rmse, 0), availability);
    }

    /// <summary>Per-position tiers, 1 = best: a new tier starts wherever the next player drops by more than k x RMSE.</summary>
    public static Dictionary<string, int> Tiers(IReadOnlyList<Player> players, IReadOnlyDictionary<Position, double> rmse,
        double gapRmse)
    {
        var tiers = new Dictionary<string, int>();
        foreach (var position in Positions.All)
        {
            var threshold = gapRmse * rmse[position];
            var tier = 1;
            Player? previous = null;
            foreach (var player in players.Where(p => p.Position == position).OrderByDescending(p => p.ProjectedPpr))
            {
                if (previous is not null && previous.ProjectedPpr - player.ProjectedPpr > threshold) tier++;
                tiers[player.PlayerId] = tier;
                previous = player;
            }
        }
        return tiers;
    }
}
