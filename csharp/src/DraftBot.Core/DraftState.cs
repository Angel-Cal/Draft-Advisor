namespace DraftBot.Core;

public sealed record Pick(int Round, int PickInRound, int Team, ValuedPlayer Player);

/// <summary>Snake draft: team order reverses every round. Tracks every roster and the pool.</summary>
public sealed class DraftState
{
    readonly List<ValuedPlayer> available;
    readonly List<Pick> history = [];

    public DraftState(IEnumerable<ValuedPlayer> pool, LeagueSettings league)
    {
        League = league.Validate();
        available = pool.ToList();
        Teams = Enumerable.Range(0, league.Teams).Select(_ => new Roster(league)).ToList();
    }

    public LeagueSettings League { get; }
    public IReadOnlyList<Roster> Teams { get; }
    public IReadOnlyList<ValuedPlayer> Available => available;
    public IReadOnlyList<Pick> History => history;

    /// <summary>1-based.</summary>
    public int Round { get; private set; } = 1;

    /// <summary>0-based position within the round.</summary>
    public int PickInRound { get; private set; }

    public int OverallPick => (Round - 1) * League.Teams + PickInRound;
    public bool IsComplete => Round > League.RosterSize;

    public int CurrentTeam => Round % 2 == 0 ? League.Teams - 1 - PickInRound : PickInRound;

    /// <summary>The 1-based overall number of the team's next pick after the one on the clock; null if it has none left.</summary>
    public int? NextPick(int team) => UpcomingPicks(team, 1) is [var next] ? next : null;

    /// <summary>The 1-based overall numbers of the team's next <paramref name="count"/> picks after the one on the clock (fewer if the draft ends first).</summary>
    public IReadOnlyList<int> UpcomingPicks(int team, int count)
    {
        var picks = new List<int>();
        for (var overall = OverallPick + 1; overall < League.Teams * League.RosterSize && picks.Count < count; overall++)
        {
            var inRound = overall % League.Teams;
            if ((overall / League.Teams % 2 == 1 ? League.Teams - 1 - inRound : inRound) == team) picks.Add(overall + 1);
        }
        return picks;
    }

    /// <summary>Drafts the player for the team on the clock. False if the player is not in the pool.</summary>
    public bool Draft(string playerId)
    {
        if (IsComplete) throw new InvalidOperationException("the draft is complete");
        var index = available.FindIndex(p => p.Id == playerId);
        if (index < 0) return false;

        var player = available[index];
        Teams[CurrentTeam].Add(player);
        history.Add(new Pick(Round, PickInRound, CurrentTeam, player));
        available.RemoveAt(index);

        PickInRound++;
        if (PickInRound >= League.Teams)
        {
            PickInRound = 0;
            Round++;
        }
        return true;
    }
}
