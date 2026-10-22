using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Simulator knobs. Opponent noise is a guess, not calibrated: we only have mean ADP, not its spread, which is why the
/// experiment also runs half and double <see cref="NoiseScale"/>.
/// </summary>
/// <param name="NoiseBase">Per-player bias SD at ADP 0, in picks.</param>
/// <param name="NoisePerAdp">Extra SD per ADP slot (late picks disagree more).</param>
/// <param name="MaxQb">Position caps for every drafter, so no roster ends up with five QBs.</param>
/// <param name="ForceStartersAfterRound">After this round a drafter with an open starter slot must fill it.</param>
public sealed record SimSettings(
    LeagueSettings League,
    double NoiseBase = 1.0,
    double NoisePerAdp = 0.1,
    double NoiseScale = 1.0,
    int MaxQb = 2,
    int MaxTe = 2,
    int ForceStartersAfterRound = 10,
    double TierGapRmse = 0.1)
{
    public double NoiseSd(double adp) => (NoiseBase + NoisePerAdp * adp) * NoiseScale;
}
