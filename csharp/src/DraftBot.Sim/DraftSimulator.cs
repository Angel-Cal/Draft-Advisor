using DraftBot.Core;

namespace DraftBot.Sim;

/// <param name="Finish">1 = highest starter points in the league (ties share the better finish).</param>
public sealed record DraftResult(int Slot, double Points, int Finish, IReadOnlyList<double> TeamPoints, IReadOnlyList<PickRegret> Regrets,
    IReadOnlyList<ValuedPlayer> MyPicks);

public static class DraftSimulator
{
    /// <summary>
    /// One full draft. The strategy drafts from <paramref name="slot"/>; every other team is a noisy-ADP bot. Rosters are then
    /// scored with actual points.
    /// If a <paramref name="regret"/> calculator is given, each of the strategy's picks is measured against its best legal alternative.
    /// </summary>
    public static DraftResult Run(IReadOnlyList<ValuedPlayer> pool, SimSettings settings, int slot, IDraftStrategy strategy, int seed,
        RegretCalculator? regret = null)
    {
        var league = settings.League;
        var bots = Enumerable.Range(0, league.Teams)
            .Select(team => team == slot ? null : OpponentBot.Create(pool, settings, seed, team)).ToArray();
        var state = new DraftState(pool, league);
        var regrets = new List<PickRegret>();

        while (!state.IsComplete)
        {
            var team = state.CurrentTeam;
            var legal = team == slot && !settings.StrategyFollowsRules ? state.Available : DraftRules.LegalPicks(state, team, settings);
            var pick = bots[team]?.Pick(legal) ?? strategy.Pick(state, team, legal);
            if (team == slot && regret is not null) regrets.Add(regret.Evaluate(legal, pick, state.Round));
            state.Draft(pick.Id);
        }

        var points = state.Teams.Select(roster => LineupScorer.Score(roster, league, settings.WeeklyLineups)).ToList();
        var finish = 1 + points.Count(p => p > points[slot]);
        return new DraftResult(slot, points[slot], finish, points, regrets, state.Teams[slot].Picks);
    }
}
