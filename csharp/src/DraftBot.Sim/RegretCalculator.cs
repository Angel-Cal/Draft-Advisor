using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// What a pick gave up versus the best player the team could legally have taken, three ways. All are zero or more.
/// </summary>
/// <param name="Actual">Hindsight: the best legal player's actual points minus the chosen player's.</param>
/// <param name="ActualVorAdjusted">Hindsight over replacement: each player's actual points minus the position's replacement level in actual points.</param>
/// <param name="ProjectedVor">Foresight: best legal projected VOR minus the chosen player's.</param>
public sealed record PickRegret(int Round, double Actual, double ActualVorAdjusted, double ProjectedVor);

public sealed class RegretCalculator
{
    readonly Dictionary<Position, double> replacementActual;

    /// <summary>Replacement level in actual points: the same FLEX-fill rule, applied to the season's actual results.</summary>
    public RegretCalculator(IReadOnlyList<ValuedPlayer> pool, LeagueSettings league)
    {
        var byActual = pool.Select(p => p.Player with { ProjectedPpr = Actual(p) }).ToList();
        replacementActual = ReplacementLevel.Points(byActual, league);
    }

    public PickRegret Evaluate(IReadOnlyList<ValuedPlayer> legal, ValuedPlayer chosen, int round)
    {
        double Adjusted(ValuedPlayer p) => Actual(p) - replacementActual[p.Position];
        return new PickRegret(round,
            legal.Max(Actual) - Actual(chosen),
            legal.Max(Adjusted) - Adjusted(chosen),
            legal.Max(p => p.Vor) - chosen.Vor);
    }

    static double Actual(ValuedPlayer p) =>
        p.Player.ActualPpr ?? throw new InvalidOperationException($"{p.Player.PlayerName} has no actual_ppr (not a backtest file)");
}
