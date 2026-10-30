using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Ways the simulated opponents can differ from "ADP plus a personal bias" without the advisor being told: a position drafted earlier or later than ADP says, a rush on a position after
/// several recent picks there, and a pull toward a position the team still needs a starter at. All in picks of ADP (positive = earlier). The default style changes nothing. Used to ask
/// whether the advisor's edge (the waiting bonus and bench terms in particular) depends on opponents that follow ADP.
/// </summary>
/// <param name="QbEarlier">Picks earlier than ADP that every opponent takes a QB (negative = later).</param>
/// <param name="RbEarlier">The same for RBs.</param>
/// <param name="WrEarlier">The same for WRs.</param>
/// <param name="TeEarlier">The same for TEs.</param>
/// <param name="RunPull">Picks earlier for each pick at the player's position among the last <paramref name="RunWindow"/> picks of the draft (a run on a position).</param>
/// <param name="RunWindow">How many of the latest picks count toward a run.</param>
/// <param name="NeedPull">Picks earlier for a player at a position where this team still has a dedicated starter slot open.</param>
public sealed record OpponentStyle(double QbEarlier = 0, double RbEarlier = 0, double WrEarlier = 0, double TeEarlier = 0, double RunPull = 0, int RunWindow = 6, double NeedPull = 0)
{
    public bool IsDefault => QbEarlier == 0 && RbEarlier == 0 && WrEarlier == 0 && TeEarlier == 0 && RunPull == 0 && NeedPull == 0;

    public double Earlier(Position position) => position switch
    {
        Position.QB => QbEarlier,
        Position.RB => RbEarlier,
        Position.WR => WrEarlier,
        _ => TeEarlier,
    };
}
