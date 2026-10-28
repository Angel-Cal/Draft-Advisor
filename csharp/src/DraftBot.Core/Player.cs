namespace DraftBot.Core;

/// <summary>
/// One row of a projection file (.claude/projection_schema_v1.md). <see cref="WeeklyPpr"/> (backtest files only) holds the 18
/// regular-season weeks of actual PPR, null where the player did not play. The last three fields are optional role-context facts (WRs only, null when unknown):
/// the share of last season's targets earned while the team's top receiver was out, whether he changed teams, and whether a first-round rookie WR/TE is on his roster.
/// </summary>
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
    double? ActualPpr,
    IReadOnlyList<double?>? WeeklyPpr = null,
    double? AbsenceSharePrev = null,
    bool? TeamChanged = null,
    bool? RookieR1Teammate = null);
