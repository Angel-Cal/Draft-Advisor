namespace DraftBot.Core;

/// <summary>Team count and starting lineup; every replacement level, tier and recommendation derives from these.</summary>
public sealed record LeagueSettings(
    int Teams = 12, int Qb = 1, int Rb = 2, int Wr = 3, int Te = 1, int Flex = 1, int Bench = 8)
{
    public int RosterSize => Qb + Rb + Wr + Te + Flex + Bench;

    public int Starters(Position position) => position switch
    {
        Position.QB => Qb,
        Position.RB => Rb,
        Position.WR => Wr,
        Position.TE => Te,
        _ => throw new ArgumentOutOfRangeException(nameof(position)),
    };

    public LeagueSettings Validate()
    {
        if (Teams < 1) throw new ArgumentException($"need at least 1 team, got {Teams}");
        if (Qb < 0 || Rb < 0 || Wr < 0 || Te < 0 || Flex < 0 || Bench < 0)
            throw new ArgumentException("roster slot counts cannot be negative");
        if (Qb + Rb + Wr + Te + Flex == 0) throw new ArgumentException("league has no starting slots");
        return this;
    }
}
