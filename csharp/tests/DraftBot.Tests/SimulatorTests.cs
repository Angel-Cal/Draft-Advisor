using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class SimulatorTests
{
    static readonly LeagueSettings League = new();
    static readonly SimSettings Settings = new(League);

    static List<ValuedPlayer> Pool(ProjectionFile? file = null)
    {
        file ??= BacktestFile();
        return Valuator.Value(file.Players, file.PositionRmse, League);
    }

    // ---- lineup scoring ---------------------------------------------------------------------------------------

    [Fact]
    public void Lineup_takes_the_best_player_per_slot_and_the_best_leftover_for_flex()
    {
        var roster = new Roster(League);
        void Add(string id, Position position, double actual) =>
            roster.Add(new ValuedPlayer(Player(id, position, 100, actual: actual), 0, 0, 0, false, 1, 0, 1));
        Add("qb1", Position.QB, 300); Add("qb2", Position.QB, 250);                   // only QB1 starts
        Add("rb1", Position.RB, 200); Add("rb2", Position.RB, 180); Add("rb3", Position.RB, 150);
        Add("wr1", Position.WR, 220); Add("wr2", Position.WR, 210); Add("wr3", Position.WR, 120); Add("wr4", Position.WR, 160);
        Add("te1", Position.TE, 100); Add("te2", Position.TE, 140);

        // QB 300 | RB 200+180 | WR 220+210+160 | TE 140 | FLEX = best leftover of RB 150, WR 120, TE 100 = 150
        Assert.Equal(300 + 380 + 590 + 140 + 150, LineupScorer.Score(roster, League));
    }

    [Fact]
    public void Lineup_scoring_needs_actual_points()
    {
        var roster = new Roster(League);
        roster.Add(new ValuedPlayer(Player("qb", Position.QB, 100), 0, 0, 0, false, 1, 0, 1));
        Assert.Throws<InvalidOperationException>(() => LineupScorer.Score(roster, League));
    }

    // ---- roster rules -----------------------------------------------------------------------------------------

    [Fact]
    public void Position_caps_remove_positions_the_team_is_full_at()
    {
        var state = new DraftState(Pool(), League);
        foreach (var qb in state.Available.Where(p => p.Position == Position.QB).Take(2)) state.Teams[0].Add(qb);
        foreach (var te in state.Available.Where(p => p.Position == Position.TE).Take(2)) state.Teams[0].Add(te);

        var legal = DraftRules.LegalPicks(state, 0, Settings);

        Assert.DoesNotContain(legal, p => p.Position is Position.QB or Position.TE);
        Assert.Contains(legal, p => p.Position == Position.RB);
    }

    [Fact]
    public void After_the_cutoff_round_a_team_must_fill_an_open_starter_slot()
    {
        var state = new DraftState(Pool(), League);
        var picks = new[] { Position.QB }.Concat(Enumerable.Repeat(Position.RB, 2)).Concat(Enumerable.Repeat(Position.WR, 3));
        foreach (var position in picks) state.Teams[0].Add(state.Available.First(p => p.Position == position && !state.Teams[0].Picks.Contains(p)));
        // TE is the only open starter slot. Move the draft past round 10: 12 teams x 10 rounds = 120 picks
        foreach (var filler in state.Available.Where(p => p.Position != Position.TE).Take(120).ToList()) state.Draft(filler.Id);

        Assert.Equal(11, state.Round);
        var team = state.Teams.Select((roster, i) => (roster, i)).First(t => t.roster.At(Position.TE).Count < 1).i;
        var legal = DraftRules.LegalPicks(state, team, Settings);
        var open = Positions.All.Where(p => state.Teams[team].At(p).Count < League.Starters(p)).ToHashSet();

        Assert.All(legal, p => Assert.Contains(p.Position, open));
    }

    [Fact]
    public void Rules_are_dropped_rather_than_stalling_when_nothing_is_legal()
    {
        var onlyQbs = Pool().Where(p => p.Position == Position.QB).Take(5).ToList();
        var state = new DraftState(onlyQbs, League);
        foreach (var qb in onlyQbs.Take(2)) state.Teams[0].Add(qb);          // capped at QB, and only QBs remain

        Assert.Equal(5, DraftRules.LegalPicks(state, 0, Settings).Count);
    }

    // ---- opponents --------------------------------------------------------------------------------------------

    [Fact]
    public void Opponent_bias_depends_only_on_seed_and_team()
    {
        var pool = Pool();
        var legal = pool.Take(40).ToList();

        var a = OpponentBot.Create(pool, Settings, seed: 7, team: 3).Pick(legal);
        var b = OpponentBot.Create(pool, Settings, seed: 7, team: 3).Pick(legal);
        Assert.Equal(a.Id, b.Id);

        var picks = Enumerable.Range(0, 12).Select(t => OpponentBot.Create(pool, Settings, seed: 7, team: t).Pick(legal).Id).Distinct();
        Assert.True(picks.Count() > 1);           // different teams like different players
    }

    [Fact]
    public void Without_noise_an_opponent_takes_the_best_adp()
    {
        var pool = Pool();
        var quiet = Settings with { NoiseScale = 0 };
        var bot = OpponentBot.Create(pool, quiet, seed: 1, team: 0);

        var legal = pool.Where(p => p.Position == Position.WR).ToList();
        Assert.Equal(legal.MinBy(p => p.Player.Adp)!.Id, bot.Pick(legal).Id);
    }

    [Fact]
    public void Unranked_players_sort_after_every_ranked_player_when_there_is_no_noise()
    {
        var players = RealisticPool().Select((p, i) => i == 0 ? p with { Adp = null } : p).ToList();
        var pool = Valuator.Value(players, Rmse, League);
        var bot = OpponentBot.Create(pool, Settings with { NoiseScale = 0 }, seed: 1, team: 0);

        Assert.NotNull(bot.Pick(pool).Player.Adp);
    }

    // ---- strategies -------------------------------------------------------------------------------------------

    [Fact]
    public void Adp_and_vor_strategies_take_the_best_legal_player_by_their_own_measure()
    {
        var state = new DraftState(Pool(), League);
        var legal = state.Available.Where(p => p.Position == Position.WR).ToList();

        Assert.Equal(legal.MinBy(p => p.Player.Adp)!.Id, new AdpStrategy().Pick(state, 0, legal).Id);
        Assert.Equal(legal.MaxBy(p => p.Vor)!.Id, new VorStrategy().Pick(state, 0, legal).Id);
    }

    [Fact]
    public void The_recommender_strategy_falls_back_to_vor_when_every_suggestion_is_illegal()
    {
        var state = new DraftState(Pool(), League);
        var suggested = BaselineRecommender.Recommend(state, 0).Candidates.Select(c => c.Player.Id).ToHashSet();
        var legal = state.Available.Where(p => !suggested.Contains(p.Id)).ToList();

        var pick = new RecommenderStrategy().Pick(state, 0, legal);

        Assert.Equal(legal.MaxBy(p => p.Vor)!.Id, pick.Id);
    }

    // ---- full drafts ------------------------------------------------------------------------------------------

    [Fact]
    public void A_draft_fills_every_roster_without_duplicates_and_reports_a_valid_finish()
    {
        var pool = Pool();
        var result = DraftSimulator.Run(pool, Settings, slot: 4, new RecommenderStrategy(), seed: 3);

        Assert.Equal(12, result.TeamPoints.Count);
        Assert.InRange(result.Finish, 1, 12);
        Assert.Equal(result.TeamPoints[4], result.Points);
        Assert.Equal(1 + result.TeamPoints.Count(p => p > result.Points), result.Finish);
    }

    [Fact]
    public void A_draft_is_reproducible()
    {
        var pool = Pool();
        var first = DraftSimulator.Run(pool, Settings, 2, new VorStrategy(), seed: 5);
        var second = DraftSimulator.Run(pool, Settings, 2, new VorStrategy(), seed: 5);

        Assert.Equal(first.TeamPoints, second.TeamPoints);
    }

    // ---- experiment -------------------------------------------------------------------------------------------

    [Fact]
    public void The_experiment_runs_every_strategy_from_every_slot_and_summarizes_against_the_adp_baseline()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };
        IDraftStrategy[] strategies = [new AdpStrategy(), new VorStrategy(), new RecommenderStrategy()];

        var result = Experiment.Run(files, Settings, strategies, noiseScales: [1.0, 2.0], seeds: 2);
        var rows = result.Rows;

        Assert.Equal(2 * 2 * 2 * 12 * 3, rows.Count);
        Assert.Equal(rows.Count, rows.Select(r => (r.Season, r.NoiseScale, r.Seed, r.Slot, r.Strategy)).Distinct().Count());
        var again = Experiment.Run(files, Settings, strategies, noiseScales: [1.0, 2.0], seeds: 2);
        Assert.Equal(rows, again.Rows);
        Assert.Equal(rows.Count * League.RosterSize, result.Regrets.Count);

        var summary = Experiment.Summarize(rows);
        Assert.Contains("recommender", summary);
        Assert.Contains("noise x2", summary);
    }

    [Fact]
    public void The_slot_summary_has_a_paired_row_for_every_slot_and_noise_level()
    {
        var files = new Dictionary<int, ProjectionFile> { [2024] = BacktestFile(2024) };
        IDraftStrategy[] strategies = [new AdpStrategy(), new VorStrategy()];
        var rows = Experiment.Run(files, Settings, strategies, noiseScales: [1.0, 2.0], seeds: 3).Rows;

        var summary = Experiment.SummarizeBySlot(rows, "vor");

        Assert.Equal(2, summary.Split("by draft slot").Length - 1);
        Assert.Equal(2 * League.Teams, summary.Split(Environment.NewLine).Count(line => line.Contains("+/-") && line.TrimStart().Split(' ')[0] is { } slot && int.TryParse(slot, out _)));
        var (overall, _) = Experiment.PairedDifference(rows.Where(r => r.NoiseScale == 1.0).ToList(), "vor", "adp");
        var perSlot = Enumerable.Range(0, League.Teams)
            .Select(slot => Experiment.PairedDifference(rows.Where(r => r.NoiseScale == 1.0 && r.Slot == slot).ToList(), "vor", "adp").Mean).Average();
        Assert.Equal(overall, perSlot, 9);                    // the slots partition the drafts evenly
    }

    [Fact]
    public void The_paired_standard_error_treats_the_drafts_of_one_seed_as_one_cluster()
    {
        RunRow Row(int seed, int slot, string strategy, double points) => new(2024, 1.0, seed, slot, strategy, points, 1, double.NaN, double.NaN, double.NaN);
        // seed 0: both slots +10 over adp, seed 1: both slots -10, so the mean is 0 and the two clusters pull in opposite directions
        var rows = new List<RunRow>();
        foreach (var (seed, edge) in new[] { (0, 10.0), (1, -10.0) })
            for (var slot = 0; slot < 2; slot++) { rows.Add(Row(seed, slot, "adp", 100)); rows.Add(Row(seed, slot, "x", 100 + edge)); }

        var (mean, se) = Experiment.PairedDifference(rows, "x", "adp");

        Assert.Equal(0, mean, 9);
        Assert.Equal(10.0, se, 9);          // 2 clusters; treating the four drafts as independent would give 11.5
    }

    [Fact]
    public void The_slot_choice_check_scores_each_slots_best_arm_on_the_held_out_season()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024), [2025] = BacktestFile(2025) };
        IDraftStrategy[] strategies = [new AdpStrategy(), new VorStrategy()];
        var rows = Experiment.Run(files, Settings, strategies, noiseScales: [1.0], seeds: 2).Rows;

        var report = Experiment.SlotChoiceCheck(rows, ["vor"], baseline: "adp");
        var onlyBaseline = Experiment.SlotChoiceCheck(rows, [], baseline: "adp");

        Assert.Contains("gain over adp", report);
        Assert.Contains("2025:", report);
        Assert.Contains("0.0 +/- 0.0", onlyBaseline);          // choosing among the baseline alone changes nothing
    }
}
