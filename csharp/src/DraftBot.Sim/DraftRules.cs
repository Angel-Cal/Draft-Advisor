using DraftBot.Core;

namespace DraftBot.Sim;

public static class DraftRules
{
    /// <summary>
    /// Players the team may take now: positions under their cap, and after the cutoff round only positions with an open
    /// starter slot. If that leaves nobody (a position ran dry) the rules are dropped rather than stalling the draft.
    /// </summary>
    public static IReadOnlyList<ValuedPlayer> LegalPicks(DraftState state, int team, SimSettings settings)
    {
        var roster = state.Teams[team];
        var allowed = Positions.All.Where(p => roster.At(p).Count < Cap(p, settings)).ToHashSet();

        if (state.Round > settings.ForceStartersAfterRound)
        {
            var open = Positions.All.Where(p => roster.At(p).Count < state.League.Starters(p)).ToHashSet();
            if (open.Count > 0) allowed.IntersectWith(open);
        }

        var legal = state.Available.Where(p => allowed.Contains(p.Position)).ToList();
        return legal.Count > 0 ? legal : state.Available;
    }

    static int Cap(Position position, SimSettings settings) => position switch
    {
        Position.QB => settings.MaxQb,
        Position.TE => settings.MaxTe,
        _ => int.MaxValue,
    };
}
