namespace DraftBot.Core;

/// <summary>
/// One row of a projection file (.claude/projection_schema_v1.md). <see cref="WeeklyPpr"/> (backtest files only) holds the 18
/// regular-season weeks of actual PPR, null where the player did not play. The last three fields are optional role-context facts (WRs only, null when unknown):
/// the share of last season's targets earned while the team's top receiver was out, whether he changed teams, and whether a first-round rookie WR/TE is on his roster.
/// <see cref="GamesHistory"/> and <see cref="MajorInjury"/> are the optional facts behind <see cref="InjuryFlag"/> (null in older files and for players with no history).
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
    bool? RookieR1Teammate = null,
    IReadOnlyList<SeasonGames>? GamesHistory = null,
    MajorInjury? MajorInjury = null);

/// <summary>Games he played in one regular season, out of the games his team played (16 before 2021, 17 from 2021).</summary>
public sealed record SeasonGames(int Season, int Games, int Of);

/// <summary>A confirmed major injury (torn knee ligament or Achilles) in the season before the draft; <see cref="Week"/> is null for one suffered outside the season.</summary>
public sealed record MajorInjury(int Season, int? Week, string Injury);
