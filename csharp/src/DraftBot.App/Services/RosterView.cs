using DraftBot.Core;

namespace DraftBot.App.Services;

/// <summary>One starting slot on the roster card: its label, the player in it (null if open) and the replacement-level points an open slot counts as.</summary>
public sealed record SlotView(string Label, Position? Position, ValuedPlayer? Player, double? Replacement);

/// <summary>A roster laid out as the roster card shows it: the starting slots in order, then the bench.</summary>
public sealed record RosterView(IReadOnlyList<SlotView> Starters, IReadOnlyList<ValuedPlayer> Bench, int BenchSpots)
{
    /// <summary>
    /// Fills each position's starting slots with its best players by projection, then the FLEX slots with the best leftover RB, WR and TE; everyone else is bench.
    /// </summary>
    public static RosterView Build(Roster roster, LeagueSettings league, IReadOnlyDictionary<Position, double> replacement)
    {
        var slots = new List<SlotView>();
        var leftover = new List<ValuedPlayer>();          // RB, WR and TE beyond their own slots: eligible for FLEX
        var benchOnly = new List<ValuedPlayer>();         // extra QBs never fill FLEX
        foreach (var position in Positions.All)
        {
            var players = roster.At(position).OrderByDescending(p => p.Player.ProjectedPpr).ToList();
            var starters = league.Starters(position);
            for (var i = 0; i < starters; i++)
                slots.Add(new SlotView(position.ToString(), position, i < players.Count ? players[i] : null, i < players.Count ? null : replacement.GetValueOrDefault(position)));
            (position == Position.QB ? benchOnly : leftover).AddRange(players.Skip(starters));
        }

        leftover = leftover.OrderByDescending(p => p.Player.ProjectedPpr).ToList();
        for (var i = 0; i < league.Flex; i++)
            slots.Add(new SlotView("FLEX", null, i < leftover.Count ? leftover[i] : null, null));

        var flexUsed = Math.Min(league.Flex, leftover.Count);
        var bench = leftover.Skip(flexUsed).Concat(benchOnly).ToList();
        return new RosterView(slots, bench, league.Bench);
    }
}
