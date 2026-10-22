using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class NeedTests
{
    // 2 teams, 1 starter each at QB/RB/WR/TE and one FLEX; replacement points: QB 200, RB 100, WR 100, TE 50
    static readonly LeagueSettings Small = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 3);
    static readonly Dictionary<Position, double> Replacement = new()
        { [Position.QB] = 200, [Position.RB] = 100, [Position.WR] = 100, [Position.TE] = 50 };

    static ValuedPlayer V(string id, Position position, double projected, double adp = 1) =>
        new(Player(id, position, projected, adp: adp), projected - Replacement[position], 0, 0, false, 1, 0, 1);

    static ValuedPlayer[] Roster(params ValuedPlayer[] players) => players;

    static double Gain(ValuedPlayer[] roster, ValuedPlayer candidate) => LineupValue.Gain(roster, candidate, Small, Replacement);

    [Fact]
    public void An_empty_roster_is_valued_at_replacement_level_in_every_slot()
    {
        // 200 QB + 100 RB + 100 WR + 50 TE + a FLEX at the best flex replacement (100)
        Assert.Equal(550, LineupValue.Best([], Small, Replacement));
    }

    [Fact]
    public void A_player_filling_an_open_slot_is_worth_his_vor()
    {
        Assert.Equal(50, Gain(Roster(), V("rb", Position.RB, 150)));
        Assert.Equal(120, Gain(Roster(), V("qb", Position.QB, 320)));
        Assert.Equal(0, Gain(Roster(), V("scrub", Position.WR, 80)));          // below replacement: the ghost is better
    }

    [Fact]
    public void A_second_player_at_a_filled_position_only_competes_for_flex()
    {
        var rb1 = V("rb1", Position.RB, 150);

        Assert.Equal(30, Gain(Roster(rb1), V("rb2", Position.RB, 130)));       // FLEX: 130 vs the 100 ghost
        Assert.Equal(0, Gain(Roster(rb1, V("rb2", Position.RB, 130)), V("rb3", Position.RB, 120)));    // FLEX already holds 130
        Assert.Equal(10, Gain(Roster(rb1, V("rb2", Position.RB, 130)), V("rb3", Position.RB, 140)));   // displaces the 130 in FLEX
    }

    [Fact]
    public void A_redundant_quarterback_adds_nothing()
    {
        Assert.Equal(0, Gain(Roster(V("qb1", Position.QB, 300)), V("qb2", Position.QB, 290)));
        Assert.Equal(20, Gain(Roster(V("qb1", Position.QB, 300)), V("qb3", Position.QB, 320)));         // an upgrade still counts
    }

    [Fact]
    public void Gain_is_never_negative_and_never_exceeds_vor()
    {
        var pool = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());
        var state = new DraftState(pool, new LeagueSettings());
        foreach (var p in state.Available.Where(p => p.Position is Position.RB or Position.WR).Take(5)) state.Teams[0].Add(p);
        foreach (var p in state.Available.Where(p => p.Position == Position.QB).Take(1)) state.Teams[0].Add(p);
        var replacement = LineupValue.Replacement(state);

        foreach (var candidate in state.Available)
        {
            var gain = LineupValue.Gain(state.Teams[0].Picks, candidate, state.League, replacement);
            Assert.True(gain >= -1e-9 && gain <= Math.Max(0, candidate.Vor) + 1e-9, $"{candidate.Id}: gain {gain}, vor {candidate.Vor}");
        }
    }

    [Fact]
    public void Replacement_is_recovered_from_the_valued_players()
    {
        var state = new DraftState([V("qb", Position.QB, 300), V("rb", Position.RB, 150), V("wr", Position.WR, 120), V("te", Position.TE, 90)], Small);

        Assert.Equal(Replacement, LineupValue.Replacement(state));
    }

    [Fact]
    public void Need_makes_a_redundant_quarterback_lose_to_a_lower_vor_player_at_an_open_position()
    {
        var qb2 = V("qb2", Position.QB, 290);       // VOR 90 but the roster already has a better QB
        var wr = V("wr", Position.WR, 180);         // VOR 80, open slot
        var state = new DraftState([qb2, wr], Small);
        state.Teams[0].Add(V("qb1", Position.QB, 300));
        var reach = new ReachSettings(Lambda: 1000, CapSigmas: 4);

        Assert.Equal("qb2", ValueRecommender.Rank(state, reach)[0].Player.Id);                                    // plain VOR
        var ranked = ValueRecommender.Rank(state, reach, new NeedSettings(0), teamIndex: 0);
        Assert.Equal("wr", ranked[0].Player.Id);
        Assert.Equal(80, ranked[0].Gain);
        Assert.Equal(0, ranked.Single(c => c.Player.Id == "qb2").Gain);
    }

    [Fact]
    public void A_bench_fraction_of_one_is_plain_vor_and_zero_is_pure_lineup_gain()
    {
        var state = new DraftState([V("qb2", Position.QB, 290), V("wr", Position.WR, 180)], Small);
        state.Teams[0].Add(V("qb1", Position.QB, 300));
        var reach = new ReachSettings(1000, 4);

        var full = ValueRecommender.Rank(state, reach, new NeedSettings(1.0)).ToDictionary(c => c.Player.Id);
        var none = ValueRecommender.Rank(state, reach, new NeedSettings(0)).ToDictionary(c => c.Player.Id);
        var half = ValueRecommender.Rank(state, reach, new NeedSettings(0.5)).ToDictionary(c => c.Player.Id);

        Assert.Equal(90, full["qb2"].Score);            // VOR
        Assert.Equal(0, none["qb2"].Score);             // no lineup gain, no bench value
        Assert.Equal(45, half["qb2"].Score);            // half of his VOR that does not help the lineup
        Assert.Equal(80, half["wr"].Score);             // a full gain, nothing left over
    }

    [Fact]
    public void Lifting_the_rules_lets_a_strategy_stack_one_position_and_following_them_does_not()
    {
        var file = BacktestFile();
        var pool = Valuator.Value(file.Players, file.PositionRmse, new LeagueSettings());
        var stackQbs = new PositionFirstStrategy(Position.QB);

        var ruled = DraftSimulator.Run(pool, new SimSettings(new LeagueSettings()), 3, stackQbs, seed: 1);
        var free = DraftSimulator.Run(pool, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), 3, stackQbs, seed: 1);

        Assert.True(ruled.MyPicks.Count(p => p.Position == Position.QB) <= 2);
        Assert.True(free.MyPicks.Count(p => p.Position == Position.QB) > 2);
    }

    [Fact]
    public void The_need_sweep_reports_the_bench_fraction_arms_and_the_value_control()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = ReachTuning.ReportNeed(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);

        foreach (var expected in new[] { "need b=0 l=1000", "need b=1 l=400", "value", "adp", "held-out gain over value" }) Assert.Contains(expected, text);
    }

    [Fact]
    public void The_mock_draft_shows_lineup_gain_when_need_is_on()
    {
        var output = new StringWriter();
        var finished = new MockDraft(BacktestFile(), new SimSettings(new LeagueSettings()), 5, 0, false,
            new StringReader(string.Concat(Enumerable.Repeat("\n", 16))), output, ValueRecommender.DefaultReach, singleScore: true, need: NeedSettings.Default).Run();
        var text = output.ToString();

        Assert.True(finished);
        Assert.Contains("lineup gain", text);
        Assert.Contains("gain", text);
        Assert.Contains("need", text.Substring(text.IndexOf("Same slot and opponents", StringComparison.Ordinal)));
    }

    /// <summary>Takes the best-VOR player at one position while any remain, else the best VOR: a deliberately redundant drafter.</summary>
    sealed class PositionFirstStrategy(Position position) : IDraftStrategy
    {
        public string Name => "stack";

        public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal) =>
            legal.Where(p => p.Position == position).MaxBy(p => p.Vor) ?? legal.MaxBy(p => p.Vor)!;
    }
}
