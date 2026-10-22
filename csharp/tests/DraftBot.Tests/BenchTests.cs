using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class BenchTests
{
    static readonly LeagueSettings OneTeam = new(Teams: 1, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);

    static ValuedPlayer Weekly(string id, Position position, params double?[] weeks) =>
        new(new Player(id, id, position, "KC", 100, 16, 0, 1, false, false, weeks.Sum(w => w ?? 0), weeks), 0, 0, 0, false, 1, 0, 1);

    static Roster RosterOf(LeagueSettings league, params ValuedPlayer[] players)
    {
        var roster = new Roster(league);
        foreach (var player in players) roster.Add(player);
        return roster;
    }

    // ---- weekly lineup scoring ----------------------------------------------------------------------------------

    [Fact]
    public void Weekly_scoring_takes_the_best_lineup_from_whoever_played_each_week()
    {
        var roster = RosterOf(OneTeam,
            Weekly("qb-a", Position.QB, 10, 10, 10), Weekly("qb-b", Position.QB, 20, null, null),       // QB-b is a one-week wonder
            Weekly("rb", Position.RB, 5, 5, 5),
            Weekly("wr-a", Position.WR, 8, null, 8), Weekly("wr-b", Position.WR, null, 6, null),         // WR-b covers WR-a's missing week
            Weekly("te", Position.TE, 3, 3, 3));

        // week 1: 20 + 5 + 8 + 3 = 36 | week 2: 10 + 5 + 6 + 3 = 24 | week 3: 10 + 5 + 8 + 3 = 26
        Assert.Equal(86, LineupScorer.ScoreWeekly(roster, OneTeam));
        // season totals would take QB-a (30) + RB 15 + WR-a 16 + TE 9 = 70 and ignore the depth
        Assert.Equal(70, LineupScorer.Score(roster, OneTeam));
        Assert.Equal(86, LineupScorer.Score(roster, OneTeam, weekly: true));
        Assert.Equal(70, LineupScorer.Score(roster, OneTeam, weekly: false));
    }

    [Fact]
    public void Weekly_scoring_fills_flex_each_week_and_a_bye_scores_nothing()
    {
        var league = new LeagueSettings(Teams: 1, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 3);
        var roster = RosterOf(league,
            Weekly("qb", Position.QB, 10, 10), Weekly("te", Position.TE, 4, null),
            Weekly("rb1", Position.RB, 9, 9), Weekly("rb2", Position.RB, 7, 2),
            Weekly("wr1", Position.WR, 6, 6), Weekly("wr2", Position.WR, 8, 1));

        // week 1: QB 10 + RB 9 + WR 8 + TE 4 + FLEX best of (RB 7, WR 6) = 38 | week 2: QB 10 + RB 9 + WR 6 + TE 0 (bye) + FLEX best of (RB 2, WR 1) = 27
        Assert.Equal(65, LineupScorer.ScoreWeekly(roster, league));
    }

    [Fact]
    public void Weekly_scoring_falls_back_to_season_totals_when_a_player_has_no_weekly_points()
    {
        var withoutWeeks = new ValuedPlayer(Player("qb", Position.QB, 100, actual: 50), 0, 0, 0, false, 1, 0, 1);
        var roster = RosterOf(OneTeam, withoutWeeks);

        Assert.Equal(50, LineupScorer.Score(roster, OneTeam, weekly: true));
    }

    [Fact]
    public void Weekly_points_are_read_from_the_projection_file()
    {
        var json = ProjectionJson().Replace("\"actual_ppr\": 47.8}", "\"actual_ppr\": 47.8, \"weekly_ppr\": [10.5, null, 37.3]}");

        var player = ProjectionFile.Parse(json).Players[0];

        Assert.Equal([10.5, null, 37.3], player.WeeklyPpr);
        Assert.Null(ProjectionFile.Parse(ProjectionJson()).Players[1].WeeklyPpr);
    }

    // ---- structural bench weights -------------------------------------------------------------------------------

    [Fact]
    public void The_chance_that_enough_starters_are_out_follows_the_binomial()
    {
        Assert.Equal(0.23, NeedSettings.AtLeast(1, 1, 0.23), 12);
        Assert.Equal(0, NeedSettings.AtLeast(2, 1, 0.23));                      // one starter cannot be out twice
        Assert.Equal(1 - Math.Pow(0.77, 3), NeedSettings.AtLeast(1, 3, 0.23), 12);
        Assert.Equal(3 * 0.23 * 0.23 * 0.77 + Math.Pow(0.23, 3), NeedSettings.AtLeast(2, 3, 0.23), 12);
        Assert.Equal(1, NeedSettings.AtLeast(0, 4, 0.23), 12);
    }

    [Fact]
    public void Backup_slots_count_flex_for_running_backs_and_receivers_only()
    {
        var league = new LeagueSettings();      // 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX

        Assert.Equal([1, 3, 4, 1], Positions.All.Select(p => NeedSettings.BackupSlots(p, league)));
    }

    [Fact]
    public void A_second_backup_quarterback_or_tight_end_is_worth_nothing_but_running_back_depth_keeps_some_value()
    {
        var league = new LeagueSettings();
        var need = NeedSettings.Structural;
        ValuedPlayer V(string id, Position position) => new(Player(id, position, 100), 0, 0, 0, false, 1, 0, 1);
        double Weight(Position position, int alreadyOwned) =>
            need.Weight(V("candidate", position), Enumerable.Range(0, alreadyOwned).Select(i => V($"own{i}", position)).ToList(), league);

        Assert.Equal(0.23, Weight(Position.QB, 1), 12);       // the 1st backup QB (starter already owned)
        Assert.Equal(0, Weight(Position.QB, 2));               // the 2nd backup QB
        Assert.Equal(0, Weight(Position.TE, 2));
        Assert.Equal(1 - Math.Pow(0.77, 3), Weight(Position.RB, 2), 12);                                  // the 1st backup RB
        Assert.Equal(3 * 0.23 * 0.23 * 0.77 + Math.Pow(0.23, 3), Weight(Position.RB, 3), 12);              // the 2nd backup RB
        Assert.True(Weight(Position.WR, 3) > Weight(Position.RB, 2) && Weight(Position.RB, 2) > Weight(Position.QB, 1));
    }

    [Fact]
    public void A_flat_bench_fraction_ignores_position()
    {
        var need = new NeedSettings(0.25);
        var candidate = new ValuedPlayer(Player("c", Position.QB, 100), 0, 0, 0, false, 1, 0, 1);

        Assert.Equal(0.25, need.Weight(candidate, [], new LeagueSettings()));
    }

    [Fact]
    public void The_structural_rule_prices_depth_by_position_in_the_ranking()
    {
        // 2 teams, 1 QB / 2 RB / 1 WR / 1 TE / 1 FLEX. The roster already holds the QB and both RB starters, so the QB and RB candidates are first backups.
        var league = new LeagueSettings(Teams: 2, Qb: 1, Rb: 2, Wr: 1, Te: 1, Flex: 1, Bench: 3);
        ValuedPlayer V(string id, Position position, double projected, double vor) =>
            new(Player(id, position, projected, adp: 1), vor, 0, 0, false, 1, 0, 1);
        // replacement: QB 200, RB 100, WR 100, TE 50
        var state = new DraftState([V("qb-backup", Position.QB, 260, 60), V("rb-backup", Position.RB, 160, 60)], league);
        state.Teams[0].Add(V("qb1", Position.QB, 300, 100));
        state.Teams[0].Add(V("te1", Position.TE, 100, 50));
        state.Teams[0].Add(V("rb1", Position.RB, 150, 50));
        state.Teams[0].Add(V("wr1", Position.WR, 150, 50));
        state.Teams[0].Add(V("rb2", Position.RB, 140, 40));
        var reach = new ReachSettings(1000, 4);

        var ranked = ValueRecommender.Rank(state, reach, NeedSettings.Structural, teamIndex: 0).ToDictionary(c => c.Player.Id);

        Assert.Equal(0.23, ranked["qb-backup"].BenchWeight!.Value, 12);                          // 1 slot to cover
        Assert.Equal(1 - Math.Pow(0.77, 3), ranked["rb-backup"].BenchWeight!.Value, 12);          // 3 RB-eligible slots to cover
    }

    [Fact]
    public void The_bench_sweep_and_the_structural_mock_draft_run()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };
        var text = ReachTuning.ReportBench(files, new SimSettings(new LeagueSettings(), StrategyFollowsRules: false), seeds: 1);
        foreach (var expected in new[] { "bench flat 0.25", "bench structural q=0.23", "need (no bench)", "held-out gain over need (no bench)" }) Assert.Contains(expected, text);

        var output = new StringWriter();
        var finished = new MockDraft(BacktestFile(), new SimSettings(new LeagueSettings()), 5, 0, false,
            new StringReader(string.Concat(Enumerable.Repeat("\n", 16))), output, ValueRecommender.DefaultReach, singleScore: true, need: NeedSettings.Structural).Run();
        Assert.True(finished);
        Assert.Contains("bench", output.ToString());
    }

    // ---- option value, waiver level and dead picks --------------------------------------------------------------

    [Fact]
    public void Option_value_is_the_expected_excess_over_the_waiver_level()
    {
        Assert.Equal(20, NeedSettings.ExpectedExcess(120, 0, 100));                 // no uncertainty: plain difference
        Assert.Equal(0, NeedSettings.ExpectedExcess(80, 0, 100));
        Assert.Equal(50 * 0.3989422804, NeedSettings.ExpectedExcess(100, 50, 100), 6);          // at the waiver level: sd x pdf(0)
        // E[max(0, X - w)] - E[max(0, w - X)] = mean - w, so the two sides must differ by exactly that
        var up = NeedSettings.ExpectedExcess(130, 40, 100);
        var down = NeedSettings.ExpectedExcess(70, 40, 100);
        Assert.Equal(30, up - down, 6);
        Assert.True(NeedSettings.ExpectedExcess(60, 40, 100) > 0);                  // a below-waiver player keeps some upside
    }

    [Fact]
    public void The_waiver_level_is_the_best_undrafted_projection_capped_at_replacement()
    {
        // 2 teams x 8 roster spots = 16 draftable picks
        var league = new LeagueSettings(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 3);
        ValuedPlayer At(string id, Position position, double projected, double adp, double replacement) =>
            new(Player(id, position, projected, adp: adp), projected - replacement, 0, 0, false, 1, 0, 1);
        var state = new DraftState([At("rb-drafted", Position.RB, 200, 5, 100), At("rb-undrafted-a", Position.RB, 90, 20, 100),
            At("rb-undrafted-b", Position.RB, 70, 30, 100), At("wr-undrafted", Position.WR, 140, 25, 100),
            At("qb", Position.QB, 300, 1, 200), At("te", Position.TE, 100, 2, 50)], league);
        var replacement = LineupValue.Replacement(state);

        var waiver = LineupValue.Waiver(state, replacement);

        Assert.Equal(90, waiver[Position.RB]);          // best RB past ADP 16
        Assert.Equal(100, waiver[Position.WR]);         // the 140 undrafted WR is capped at replacement (100)
        Assert.Equal(200, waiver[Position.QB]);         // nobody undrafted: falls back to replacement
    }

    [Fact]
    public void Valued_players_carry_their_position_rmse()
    {
        var valued = Valuator.Value(RealisticPool(), Rmse, new LeagueSettings());

        Assert.All(valued, v => Assert.Equal(Rmse[v.Position], v.Rmse));
    }

    [Fact]
    public void A_player_who_can_never_start_or_be_needed_is_a_dead_pick_ranked_below_any_useful_one()
    {
        var league = new LeagueSettings(Teams: 2, Qb: 1, Rb: 2, Wr: 1, Te: 1, Flex: 1, Bench: 3);
        ValuedPlayer V(string id, Position position, double projected, double adp = 100) =>
            new(Player(id, position, projected, adp: adp), position == Position.QB ? projected - 200 : projected - 100, 0, 0, false, 1, 0, 1, Rmse: 50);
        // the roster holds a starting QB and one backup QB, so a third QB (k = 2 of 1 slot) has weight 0
        var state = new DraftState([V("qb3", Position.QB, 250, adp: 1), V("wr-scrub", Position.WR, 60, adp: 1)], league);
        state.Teams[0].Add(V("qb1", Position.QB, 300, adp: 1));
        state.Teams[0].Add(V("qb2", Position.QB, 280, adp: 1));
        var reach = new ReachSettings(1000, 4);

        var ranked = ValueRecommender.Rank(state, reach, NeedSettings.Option, teamIndex: 0);

        Assert.Equal("wr-scrub", ranked[0].Player.Id);                         // worth ~nothing, but not impossible to need
        Assert.Equal(0, ranked.Single(c => c.Player.Id == "qb3").BenchWeight);
        Assert.True(ranked.Single(c => c.Player.Id == "qb3").Score < -900_000);
    }

    [Fact]
    public void Dead_picks_exist_only_with_structural_weights_not_a_flat_fraction_of_zero()
    {
        var league = new LeagueSettings(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 1, Bench: 3);
        var state = new DraftState([new ValuedPlayer(Player("wr", Position.WR, 60, adp: 1), -40, 0, 0, false, 1, 0, 1)], league);

        var flat = ValueRecommender.Rank(state, new ReachSettings(1000, 4), new NeedSettings(0)).Single();

        Assert.Equal(0, flat.Score);                       // zero value, but not a dead pick
    }

    [Fact]
    public void The_default_need_setting_builds_a_sane_roster_without_caps()
    {
        var file = BacktestFile();
        var pool = Valuator.Value(file.Players, file.PositionRmse, new LeagueSettings());
        var settings = new SimSettings(new LeagueSettings(), StrategyFollowsRules: false);

        var result = DraftSimulator.Run(pool, settings, 4, new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default), seed: 3);

        Assert.True(result.MyPicks.Count(p => p.Position == Position.QB) <= 2, "more than two QBs");
        Assert.True(result.MyPicks.Count(p => p.Position == Position.TE) <= 2, "more than two TEs");
    }
}
