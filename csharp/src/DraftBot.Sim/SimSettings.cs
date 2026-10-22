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
public sealed record SimSettings(
    LeagueSettings League,
    double NoiseBase = 1.0,
    double NoisePerAdp = 0.12,
    double NoiseScale = 1.0,
    int MaxQb = 2,
    int MaxTe = 2,
    int ForceStartersAfterRound = 10,
    double TierGapRmse = 0.1)
{
    public double NoiseSd(double adp) => (NoiseBase + NoisePerAdp * adp) * NoiseScale;
}
