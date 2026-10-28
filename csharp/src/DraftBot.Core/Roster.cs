namespace DraftBot.Core;

/// <summary>One team's picks. Ported from the Python advisor, including how it decides FLEX is "filled".</summary>
public sealed class Roster
{
    readonly Dictionary<Position, List<ValuedPlayer>> byPosition = Positions.All.ToDictionary(p => p, _ => new List<ValuedPlayer>());
    readonly List<ValuedPlayer> picks = [];

    public Roster(LeagueSettings league) => League = league;

    public LeagueSettings League { get; }
    public IReadOnlyList<ValuedPlayer> Picks => picks;
    public IReadOnlyList<ValuedPlayer> At(Position position) => byPosition[position];

    /// <summary>
    /// Mirrors the Python rule: FLEX counts as filled once every RB/WR/TE starter slot is filled, whether or not a
    /// player has actually been drafted into the FLEX slot.
    /// </summary>
    public bool FlexFilled => Positions.FlexEligible.All(p => byPosition[p].Count >= League.Starters(p));

    /// <summary>An independent copy with the same picks.</summary>
    public Roster Clone()
    {
        var copy = new Roster(League);
        foreach (var player in picks) copy.Add(player);
        return copy;
    }

    public void Add(ValuedPlayer player)
    {
        byPosition[player.Position].Add(player);
        picks.Add(player);
    }

    /// <summary>Unfilled starter slots (FLEX appears once any RB/WR/TE starter slot is filled), and bench spots left.</summary>
    public (List<Slot> Needs, int BenchRemaining) GetNeeds()
    {
        var needs = new List<Slot>();
        if (At(Position.QB).Count < League.Qb) needs.Add(Slot.QB);
        if (At(Position.RB).Count < League.Rb) needs.Add(Slot.RB);
        if (At(Position.WR).Count < League.Wr) needs.Add(Slot.WR);
        if (At(Position.TE).Count < League.Te) needs.Add(Slot.TE);
        var anyFlexPositionFilled = Positions.FlexEligible.Any(p => At(p).Count >= League.Starters(p));
        if (League.Flex > 0 && anyFlexPositionFilled && !FlexFilled) needs.Add(Slot.Flex);

        var benchUsed = FlexFilled ? picks.Count - League.Qb - League.Rb - League.Wr - League.Te - League.Flex : 0;
        return (needs, League.Bench - benchUsed);
    }
}
