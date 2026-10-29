using DraftBot.Core;
using DraftBot.Sim;

namespace DraftBot.App.Services;

/// <summary>
/// A practice draft: the user picks for one slot and the simulator's opponents (the bots the experiments use) pick for everyone else. After each of the user's
/// picks the bots play on until it is the user's turn again, and the advice for that pick is computed once, so the screen only reads it.
/// </summary>
public sealed class PracticeDraft
{
    /// <summary>Seconds on the pick clock (the screen shows a countdown; nothing is forced at zero).</summary>
    public const int PickClockSeconds = 90;

    readonly SimSettings sim;
    readonly OpponentBot?[] bots;

    /// <summary>A fresh draft from a projection file: <paramref name="slot"/> is the user's 0-based draft slot.</summary>
    public PracticeDraft(ProjectionFile file, LeagueSettings league, int slot, int seed)
        : this(NewState(file, league), slot, seed)
    {
    }

    /// <summary>A practice draft continuing from a draft state that already has picks (the bots pick for every team but <paramref name="slot"/>).</summary>
    public PracticeDraft(DraftState state, int slot, int seed)
    {
        State = state;
        Slot = slot;
        sim = new SimSettings(state.League);
        var pool = state.Available.Concat(state.Teams.SelectMany(t => t.Picks)).ToList();
        bots = Enumerable.Range(0, state.League.Teams).Select(team => team == slot ? null : OpponentBot.Create(pool, sim, seed, team)).ToArray();
        AdvanceToMyTurn();
    }

    static DraftState NewState(ProjectionFile file, LeagueSettings league) =>
        new(Valuator.Value(file.Players, file.PositionRmse, league), league);

    public DraftState State { get; }

    /// <summary>The user's 0-based draft slot.</summary>
    public int Slot { get; }

    public LeagueSettings League => State.League;

    public bool IsComplete => State.IsComplete;

    /// <summary>When the advice for the current pick was produced, for the pick clock (moved forward by the time spent paused).</summary>
    public DateTime PickStartedUtc { get; private set; }

    DateTime? pausedAtUtc;

    /// <summary>While paused the pick clock stands still and nothing can be drafted; for testing, so a screen can be looked at as long as needed.</summary>
    public bool IsPaused => pausedAtUtc is not null;

    /// <summary>Time on the current pick so far, not counting time paused.</summary>
    public TimeSpan ElapsedOnPick => (pausedAtUtc ?? DateTime.UtcNow) - PickStartedUtc;

    public void Pause()
    {
        if (pausedAtUtc is not null || State.IsComplete) return;
        pausedAtUtc = DateTime.UtcNow;
        Changed?.Invoke();
    }

    public void Resume()
    {
        if (pausedAtUtc is not { } at) return;
        PickStartedUtc += DateTime.UtcNow - at;
        pausedAtUtc = null;
        Changed?.Invoke();
    }

    /// <summary>The advice for the user's current pick; null once the draft is complete.</summary>
    public Advice? Advice { get; private set; }

    public event Action? Changed;

    /// <summary>The user drafts the player; the opponents then pick until the user's next turn. False if it is not the user's turn, the draft is paused, or the player is gone.</summary>
    public bool Draft(string playerId)
    {
        if (IsPaused || State.IsComplete || State.CurrentTeam != Slot || !State.Draft(playerId)) return false;
        AdvanceToMyTurn();
        Changed?.Invoke();
        return true;
    }

    /// <summary>"You" for the user's team, otherwise "Team n".</summary>
    public string TeamName(int team) => team == Slot ? "You" : $"Team {team + 1}";

    /// <summary>The overall pick number (1-based) at which the player was taken, or null if he is still available.</summary>
    public int? PickNumber(string playerId) =>
        State.History.Select((p, i) => (p, i)).Where(x => x.p.Player.Id == playerId).Select(x => (int?)(x.i + 1)).FirstOrDefault();

    void AdvanceToMyTurn()
    {
        while (!State.IsComplete && State.CurrentTeam != Slot)
        {
            var team = State.CurrentTeam;
            State.Draft(bots[team]!.Pick(DraftRules.LegalPicks(State, team, sim)).Id);
        }
        PickStartedUtc = DateTime.UtcNow;
        Advice = State.IsComplete ? null : DraftAdvisor.Advise(State, Slot);
    }
}
