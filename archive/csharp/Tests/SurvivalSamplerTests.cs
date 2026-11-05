using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class SurvivalSamplerTests
{
    // 4 teams, so picks 2-4 belong to teams 1-3 while I (team 0) hold pick 1 and wait for pick 5
    static readonly LeagueSettings Four = new(Teams: 4, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);
    static readonly OpponentModel Exact = new(NoiseBase: 0, NoisePerAdp: 0);

    static ValuedPlayer V(string id, Position position, double adp) => new(Player(id, position, 200 - adp, adp: adp), 100 - adp, 0, 0, false, 1, 0, 1, 50);

    static DraftState Pool() => new(
    [
        V("qb1", Position.QB, 1), V("rb2", Position.RB, 2), V("wr3", Position.WR, 3), V("rb4", Position.RB, 4), V("wr5", Position.WR, 5),
        V("te6", Position.TE, 6), V("qb7", Position.QB, 7), V("rb8", Position.RB, 8), V("wr9", Position.WR, 9), V("te10", Position.TE, 10),
        V("rb11", Position.RB, 11), V("wr12", Position.WR, 12),
    ], Four);

    [Fact]
    public void With_no_noise_the_drafters_ahead_of_me_take_exactly_the_best_by_adp()
    {
        var survival = SurvivalSampler.Survival(Pool(), untilPick: 5, Exact, samples: 5);

        Assert.All(new[] { "qb1", "rb2", "wr3" }, id => Assert.Equal(0, survival[id]));        // three opponent picks come before pick 5
        Assert.All(survival.Where(s => s.Key is not ("qb1" or "rb2" or "wr3")), s => Assert.Equal(1, s.Value));
    }

    [Fact]
    public void A_position_nobody_may_take_survives_and_pushes_the_run_to_the_next_best()
    {
        var capped = Exact with { MaxQb = 0 };

        var survival = SurvivalSampler.Survival(Pool(), untilPick: 5, capped, samples: 5);

        Assert.Equal(1, survival["qb1"]);                         // would be gone without the cap
        Assert.Equal(0, survival["rb4"]);                         // the third pick reaches one player further
    }

    [Fact]
    public void Survival_is_a_probability_the_current_pick_is_ignored_and_the_result_is_repeatable()
    {
        var state = Pool();
        var noisy = new OpponentModel();

        var first = SurvivalSampler.Survival(state, 5, noisy, samples: 30);
        var again = SurvivalSampler.Survival(state, 5, noisy, samples: 30);

        Assert.Equal(first, again);
        Assert.All(first.Values, p => Assert.InRange(p, 0, 1));
        Assert.True(first["qb1"] < first["rb11"]);                // earlier ADP, less likely to last
        Assert.Equal(state.Available.Count, first.Count);
        Assert.All(SurvivalSampler.Survival(state, 2, noisy, samples: 10).Values, p => Assert.Equal(1, p));      // no opponent pick before pick 2
    }

    [Fact]
    public void The_waiting_bonus_can_use_simulated_survival_and_needs_a_horizon_of_one()
    {
        var reach = new ReachSettings(0, 100);
        var state = Pool();

        var plain = ValueRecommender.Rank(state, reach, NeedSettings.Default, 0, new WaitSettings(4)).ToDictionary(c => c.Player.Id);
        var simulated = ValueRecommender.Rank(state, reach, NeedSettings.Default, 0, new WaitSettings(4, Opponents: Exact, Samples: 5)).ToDictionary(c => c.Player.Id);

        Assert.All(simulated.Values, c => Assert.True(c.WaitBonus >= 0));
        Assert.NotEqual(plain["rb8"].WaitBonus, simulated["rb8"].WaitBonus);
        Assert.Throws<ArgumentException>(() => ValueRecommender.Rank(state, reach, NeedSettings.Default, 0, new WaitSettings(4, Horizon: 2, Opponents: Exact)));
    }
}
