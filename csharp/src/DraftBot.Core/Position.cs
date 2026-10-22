namespace DraftBot.Core;

public enum Position { QB, RB, WR, TE }

/// <summary>A lineup slot: a position, or the FLEX slot that RB/WR/TE can fill.</summary>
public enum Slot { QB, RB, WR, TE, Flex }

public static class Positions
{
    public static readonly Position[] All = [Position.QB, Position.RB, Position.WR, Position.TE];
    public static readonly Position[] FlexEligible = [Position.RB, Position.WR, Position.TE];
}
