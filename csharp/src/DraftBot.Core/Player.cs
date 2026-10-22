namespace DraftBot.Core;

/// <summary>One row of a projection file (.claude/projection_schema_v1.md).</summary>
public sealed record Player(
    string PlayerId,
    string PlayerName,
    Position Position,
    string Team,
    double ProjectedPpr,
    int Games,
    int GamesDelta,
    double? Adp,
    bool InjuryFlag,
    bool MarketEstimate,
    double? ActualPpr);
