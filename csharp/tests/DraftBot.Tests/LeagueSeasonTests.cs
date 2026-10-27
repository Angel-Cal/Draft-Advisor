using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class LeagueSeasonTests
{
    const int Weeks = 18;

    static List<double[]> Constant(params double[] points) => points.Select(p => Enumerable.Repeat(p, Weeks).ToArray()).ToList();

    [Fact]
    public void The_format_works_out_byes_and_rounds_from_the_playoff_field()
    {
        var six = new SeasonFormat(13, 6);
        Assert.Equal((2, 3, 16), (six.Byes, six.PlayoffRounds, six.Weeks));            // seeds 1-2 rest, three rounds, weeks 14-16
        var four = new SeasonFormat(13, 4);
        Assert.Equal((0, 2, 15), (four.Byes, four.PlayoffRounds, four.Weeks));
    }

    [Fact]
    public void A_team_that_always_scores_the_most_wins_every_game_and_the_title()
    {
        var odds = LeagueSeason.Odds(Constant(60, 50, 40, 30, 20, 10, 5, 4), new SeasonFormat(13, 4), schedules: 20, seed: 1);

        Assert.Equal((1.0, 1.0, 1.0), (odds[0].WinPct, odds[0].PlayoffProbability, odds[0].TitleProbability));
        Assert.Equal(0, odds[7].WinPct);
        Assert.Equal(0, odds[7].PlayoffProbability);
        Assert.Equal(1.0, odds.Take(4).Select(o => o.PlayoffProbability).Distinct().Single());       // the four best always qualify
        Assert.Equal(1.0, odds.Sum(o => o.TitleProbability), 9);
    }

    [Fact]
    public void Byes_let_the_top_two_seeds_skip_round_one_and_the_best_team_still_wins_a_six_team_field()
    {
        var odds = LeagueSeason.Odds(Constant(90, 80, 70, 60, 50, 40, 30, 20, 10, 5), new SeasonFormat(13, 6), schedules: 20, seed: 2);

        Assert.Equal(1.0, odds[0].TitleProbability);
        Assert.Equal(6.0, odds.Sum(o => o.PlayoffProbability), 9);
    }

    [Fact]
    public void A_lower_seed_can_win_by_beating_the_better_seed_in_a_playoff_week()
    {
        // team 5 is the worst all regular season (weeks 1-13) but scores the most in playoff weeks 14-16, so it needs to qualify to win
        var weekly = Constant(60, 50, 40, 30, 20, 10);
        foreach (var week in new[] { 13, 14, 15 }) weekly[5][week] = 1000;

        var odds = LeagueSeason.Odds(weekly, new SeasonFormat(13, 6), schedules: 10, seed: 3);

        Assert.Equal(1.0, odds[5].TitleProbability);        // 6 teams, 6 spots: it qualifies as the 6th seed and wins all three playoff rounds
        Assert.Equal(0.0, odds[0].TitleProbability);
    }

    [Fact]
    public void Identical_teams_have_equal_chances_and_the_odds_add_up()
    {
        var random = new Random(5);
        var weekly = Enumerable.Range(0, 12).Select(_ => Enumerable.Range(0, Weeks).Select(_ => 100 + 20 * random.NextDouble()).ToArray()).ToList();

        var odds = LeagueSeason.Odds(weekly, new SeasonFormat(), schedules: 100, seed: 4);

        Assert.Equal(1.0, odds.Sum(o => o.TitleProbability), 9);
        Assert.Equal(6.0, odds.Sum(o => o.PlayoffProbability), 9);
        Assert.Equal(0.5, odds.Average(o => o.WinPct), 9);
        Assert.All(odds, o => Assert.InRange(o.WinPct, 0, 1));
    }

    [Fact]
    public void The_same_seed_gives_the_same_odds_and_a_different_seed_a_different_schedule()
    {
        var random = new Random(6);
        var weekly = Enumerable.Range(0, 12).Select(_ => Enumerable.Range(0, Weeks).Select(_ => 100 + 20 * random.NextDouble()).ToArray()).ToList();

        var a = LeagueSeason.Odds(weekly, new SeasonFormat(), 10, seed: 1);
        var b = LeagueSeason.Odds(weekly, new SeasonFormat(), 10, seed: 1);
        var c = LeagueSeason.Odds(weekly, new SeasonFormat(), 10, seed: 2);

        Assert.Equal(a, b);
        Assert.NotEqual(a, c);
    }

    [Fact]
    public void Odd_leagues_get_a_bye_week_and_a_season_longer_than_the_data_is_refused()
    {
        var odd = LeagueSeason.Odds(Constant(50, 40, 30, 20, 10), new SeasonFormat(13, 4), 10, seed: 1);
        Assert.Equal(1.0, odd.Sum(o => o.TitleProbability), 9);

        Assert.Throws<ArgumentException>(() => LeagueSeason.Odds(Constant(1, 2, 3, 4).Select(w => w[..10]).ToList(), new SeasonFormat(), 5, 1));
        Assert.Throws<ArgumentException>(() => LeagueSeason.Odds(Constant(1, 2, 3, 4), new SeasonFormat(13, 6), 5, 1));
    }

    [Fact]
    public void A_simulated_draft_reports_season_odds_only_when_weekly_lineups_are_available()
    {
        var pool = Valuator.Value(RealisticPool().Select((p, i) => p with
        {
            ActualPpr = p.ProjectedPpr,
            WeeklyPpr = Enumerable.Range(0, Weeks).Select(w => (double?)(p.ProjectedPpr / 17 * (0.5 + ((i * 7 + w * 13) % 10) / 10.0))).ToList(),
        }).ToList(), Rmse, new LeagueSettings());
        var settings = new SimSettings(new LeagueSettings(), ScheduleSamples: 20);

        var result = DraftSimulator.Run(pool, settings, slot: 3, new AdpStrategy(), seed: 1);
        var totals = DraftSimulator.Run(pool, settings with { WeeklyLineups = false }, slot: 3, new AdpStrategy(), seed: 1);

        Assert.NotNull(result.Odds);
        Assert.InRange(result.Odds!.TitleProbability, 0, 1);
        Assert.True(result.Odds.PlayoffProbability >= result.Odds.TitleProbability);
        Assert.Null(totals.Odds);
    }
}
