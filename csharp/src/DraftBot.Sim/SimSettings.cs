using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Simulator knobs. The opponent noise formula (base 1 pick + 0.12 per ADP slot) is fit to the real spread of pick positions across
/// thousands of mock drafts (`calibrate-noise`, `fit-noise`); the experiment still runs half and double <see cref="NoiseScale"/> as a check.
/// </summary>
/// <param name="NoiseBase">Per-player bias SD at ADP 0, in picks.</param>
/// <param name="NoisePerAdp">Extra SD per ADP slot (late picks disagree more).</param>
/// <param name="MaxQb">Position caps for every drafter, so no roster ends up with five QBs.</param>
/// <param name="ForceStartersAfterRound">After this round a drafter with an open starter slot must fill it.</param>
/// <param name="WeeklyLineups">Score rosters with the best lineup each week (byes and injuries matter) when the file has weekly points; false scores season totals.</param>
/// <param name="StrategyFollowsRules">False lifts the caps and forced fills for the strategy being evaluated only (opponents keep them).</param>
/// <param name="Season">Head-to-head season and playoff shape for the league-finish odds; null means <see cref="SeasonFormat"/>'s defaults (13 weeks, 6 playoff teams).</param>
/// <param name="ScheduleSamples">Random schedules each draft's season is replayed under; the odds are averaged over them.</param>
/// <param name="Style">Opponent behavior beyond ADP plus noise (see <see cref="OpponentStyle"/>); null is the calibrated default.</param>
public sealed record SimSettings(
    LeagueSettings League,
    double NoiseBase = 1.0,
    double NoisePerAdp = 0.12,
    double NoiseScale = 1.0,
    int MaxQb = 2,
    int MaxTe = 2,
    int ForceStartersAfterRound = 10,
    double TierGapRmse = 0.1,
    bool StrategyFollowsRules = true,
    bool WeeklyLineups = true,
    SeasonFormat? Season = null,
    int ScheduleSamples = 200,
    OpponentStyle? Style = null)
{
    public SeasonFormat SeasonRules => Season ?? new SeasonFormat();

    public double NoiseSd(double adp) => (NoiseBase + NoisePerAdp * adp) * NoiseScale;
}
