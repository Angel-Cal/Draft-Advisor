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
    readonly TimeProvider time;

    /// <summary>A fresh draft from a projection file: <paramref name="slot"/> is the user's 0-based draft slot.</summary>
    /// <param name="time">The pick clock's time source (monotonic timestamps); the system's by default.</param>
    public PracticeDraft(ProjectionFile file, LeagueSettings league, int slot, int seed, TimeProvider? time = null)
        : this(NewState(file, league), slot, seed, time)
    {
    }

    /// <summary>A practice draft continuing from a draft state that already has picks (the bots pick for every team but <paramref name="slot"/>).</summary>
    public PracticeDraft(DraftState state, int slot, int seed, TimeProvider? time = null)
    {
        State = state;
        Slot = slot;
        this.time = time ?? TimeProvider.System;
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

    // the pick clock, in monotonic timestamps (a wall-clock change during a pick must not move it): when the advice for the current pick was produced, moved forward by the time spent paused
    long pickStarted;
    long? pausedAt;

    /// <summary>While paused the pick clock stands still and nothing can be drafted; for testing, so a screen can be looked at as long as needed.</summary>
    public bool IsPaused => pausedAt is not null;

    /// <summary>Time on the current pick so far, not counting time paused.</summary>
    public TimeSpan ElapsedOnPick => time.GetElapsedTime(pickStarted, pausedAt ?? time.GetTimestamp());

    /// <summary>How long a new pick's advice is on the clock before a pick is accepted: the Windows double-click time, so the second click of a double-click cannot draft at the next pick.</summary>
    public static readonly TimeSpan DefaultRepeatGuard = TimeSpan.FromMilliseconds(500);

    /// <summary>The repeat guard in use (<see cref="DefaultRepeatGuard"/>; tests that draft without a clock set it to zero).</summary>
    public TimeSpan RepeatGuard { get; init; } = DefaultRepeatGuard;

    /// <summary>True when <see cref="Draft"/> would take a pick now: the user is on the clock, not paused, and the pick's advice has been up for <see cref="RepeatGuard"/>.</summary>
    public bool AcceptsPicks => !IsPaused && !State.IsComplete && State.CurrentTeam == Slot && ElapsedOnPick >= RepeatGuard;

    public void Pause()
    {
        if (pausedAt is not null || State.IsComplete) return;
        pausedAt = time.GetTimestamp();
        Changed?.Invoke();
    }

    public void Resume()
    {
        if (pausedAt is not { } at) return;
        pickStarted += time.GetTimestamp() - at;
        pausedAt = null;
        Changed?.Invoke();
    }

    /// <summary>The advice for the user's current pick; null once the draft is complete.</summary>
    public Advice? Advice { get; private set; }

    public event Action? Changed;

    /// <summary>
    /// The user drafts the player at overall pick <paramref name="pick"/> (1-based, <see cref="Core.Advice.Pick"/> of the advice the choice was made from); the opponents then
    /// pick until the user's next turn. False if that is not the current pick (a click left over from an earlier pick), the pick's advice has been up for less than
    /// <see cref="RepeatGuard"/> (the second click of a double-click), it is not the user's turn, the draft is paused, or the player is gone (STATE_MACHINES.md, ISSUE-1).
    /// </summary>
    public bool Draft(string playerId, int pick)
    {
        if (!AcceptsPicks || pick != State.OverallPick + 1 || !State.Draft(playerId)) return false;
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
        Advice = State.IsComplete ? null : DraftAdvisor.Advise(State, Slot);
        pickStarted = time.GetTimestamp();
    }
}
