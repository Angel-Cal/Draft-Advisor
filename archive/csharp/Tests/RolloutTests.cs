using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class RolloutTests
{
    // 4 teams, 1 starter each at QB/RB/WR/TE, 3 bench spots: 7 picks each, 28 in all
    static readonly LeagueSettings Four = new(Teams: 4, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);
    static readonly Position[] Cycle = [Position.QB, Position.RB, Position.WR, Position.RB, Position.WR, Position.TE, Position.WR, Position.RB];

    static ValuedPlayer V(string id, Position position, double adp) => new(Player(id, position, 200 - adp, adp: adp), 100 - adp, 0, 0, false, 1, 0, 1, 50);

    static DraftState Pool() => new(Enumerable.Range(1, 36).Select(i => V($"p{i}", Cycle[(i - 1) % Cycle.Length], i)), Four);

    [Fact]
    public void A_cloned_draft_state_can_be_played_without_touching_the_original()
    {
        var state = Pool();
        state.Draft("p1");

        var clone = state.Clone();
        clone.Draft("p2");
        clone.Draft("p3");

        Assert.Equal(35, state.Available.Count);
        Assert.Equal(1, state.OverallPick);
        Assert.Single(state.History);
        Assert.Equal(33, clone.Available.Count);
        Assert.Equal(3, clone.OverallPick);
        Assert.Equal(state.Teams[0].Picks.Select(p => p.Id), clone.Teams[0].Picks.Select(p => p.Id));
        Assert.Single(clone.Teams[0].Picks);
        Assert.Single(clone.Teams[1].Picks);
    }

    [Fact]
    public void An_opponent_follows_its_position_cap_and_takes_the_best_key_among_the_rest()
    {
        var state = Pool();
        var noQb = new OpponentModel(MaxQb: 0);

        var pick = noQb.Choose(state, team: 0, p => p.Player.Adp!.Value);

        Assert.Equal("p2", pick.Id);                           // p1 is the QB
        Assert.Equal("p1", new OpponentModel().Choose(state, 0, p => p.Player.Adp!.Value).Id);
    }

    [Fact]
    public void The_rollout_ranks_its_candidates_by_mean_value_and_leaves_the_real_draft_alone()
    {
        var state = Pool();
        var reach = new ReachSettings(0, 100);
        var settings = new RolloutSettings(Candidates: 3, Samples: 3);

        var results = Rollout.Rank(state, reach, NeedSettings.Default, teamIndex: 0, settings);
        var again = Rollout.Rank(Pool(), reach, NeedSettings.Default, teamIndex: 0, settings);

        Assert.Equal(3, results.Count);
        Assert.Equal(results.OrderByDescending(r => r.Value).Select(r => r.Player.Id), results.Select(r => r.Player.Id));
        Assert.All(results, r => Assert.True(double.IsFinite(r.Value)));
        Assert.Equal(results.Select(r => (r.Player.Id, r.Value)), again.Select(r => (r.Player.Id, r.Value)));      // same state, same answer
        Assert.Equal(36, state.Available.Count);
        Assert.Equal(0, state.OverallPick);
    }

    [Fact]
    public void The_candidate_filter_limits_the_rollout_and_one_candidate_needs_no_rollout()
    {
        var state = Pool();
        var reach = new ReachSettings(0, 100);

        var results = Rollout.Rank(state, reach, NeedSettings.Default, 0, new RolloutSettings(Candidates: 5, Samples: 2), allowed: p => p.Position == Position.TE);
        var single = Rollout.Rank(state, reach, NeedSettings.Default, 0, new RolloutSettings(Candidates: 1, Samples: 2));

        Assert.All(results, r => Assert.Equal(Position.TE, r.Player.Position));
        Assert.Single(single);
        Assert.Equal(single[0].BaseScore, single[0].Value);
    }

    [Fact]
    public void A_finished_rosters_value_is_its_lineup_plus_bench_value_only_for_players_who_do_not_start()
    {
        var replacement = new Dictionary<Position, double> { [Position.QB] = 100, [Position.RB] = 100, [Position.WR] = 100, [Position.TE] = 100 };
        var waiver = new Dictionary<Position, double> { [Position.QB] = 50, [Position.RB] = 50, [Position.WR] = 50, [Position.TE] = 50 };
        var starters = new[] { V("qb", Position.QB, 1), V("rb", Position.RB, 2), V("wr", Position.WR, 3), V("te", Position.TE, 4) };
        var backup = V("rb2", Position.RB, 5);

        var lineupOnly = Rollout.FinalValue(starters, Four, replacement, waiver, NeedSettings.Default);
        var withBackup = Rollout.FinalValue([.. starters, backup], Four, replacement, waiver, NeedSettings.Default);

        Assert.Equal(LineupValue.Best(starters, Four, replacement), lineupOnly, 9);
        Assert.True(withBackup > lineupOnly);                                  // a first backup has bench value
        Assert.Equal(LineupValue.Best(starters, Four, replacement), LineupValue.Best([.. starters, backup], Four, replacement), 9);     // and does not change the lineup
        Assert.True(withBackup - lineupOnly <= NeedSettings.ExpectedExcess(backup.Player.ProjectedPpr, backup.Rmse, 50) + 1e-9);
    }
}
