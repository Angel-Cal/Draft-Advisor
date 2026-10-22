using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class NoiseCalibrationTests
{
    static readonly SimSettings Settings = new(new LeagueSettings());

    static string WriteFfc(string directory, int season)
    {
        Directory.CreateDirectory(directory);
        var players = Enumerable.Range(1, 130).Select(i => new
        {
            adp = (double)i, stdev = 1 + 0.1 * i, times_drafted = i == 130 ? 5 : 100,   // the last player is too rarely drafted to count
        });
        var path = Path.Combine(directory, $"ffc_ppr12_{season}.json");
        File.WriteAllText(path, System.Text.Json.JsonSerializer.Serialize(new { players }));
        return path;
    }

    static string TempDirectory() => Path.Combine(Path.GetTempPath(), "draftbot-ffc-" + Guid.NewGuid().ToString("N"));

    static IReadOnlyList<ValuedPlayer> Pool() => Valuator.Value(BacktestFile().Players, BacktestFile().PositionRmse, new LeagueSettings());

    [Fact]
    public void Real_spreads_keep_only_often_drafted_players_inside_the_last_bucket()
    {
        var directory = TempDirectory();
        try
        {
            var spreads = NoiseCalibration.LoadReal(WriteFfc(directory, 2024));

            Assert.Equal(120, spreads.Count);                                    // adp 121-130 are beyond 120; none drafted < 30 times inside
            Assert.Equal(1 + 0.1 * 50, spreads.Single(s => s.MeanPick == 50).Sd);
        }
        finally { Directory.Delete(directory, true); }
    }

    [Fact]
    public void Without_noise_every_draft_is_identical_and_with_noise_pick_positions_vary_more_as_noise_grows()
    {
        var pool = Pool();

        var none = NoiseCalibration.Simulate(pool, Settings with { NoiseScale = 0 }, drafts: 30);
        var some = NoiseCalibration.Simulate(pool, Settings with { NoiseScale = 1 }, drafts: 30);
        var lots = NoiseCalibration.Simulate(pool, Settings with { NoiseScale = 3 }, drafts: 30);

        Assert.NotEmpty(none);
        Assert.All(none, s => Assert.Equal(0, s.Sd, 9));
        Assert.True(some.Average(s => s.Sd) > 0.5);
        Assert.True(lots.Average(s => s.Sd) > some.Average(s => s.Sd));
    }

    [Fact]
    public void The_report_compares_real_and_simulated_spread_by_bucket_and_scores_each_scale()
    {
        var directory = TempDirectory();
        try
        {
            WriteFfc(directory, 2023);
            WriteFfc(directory, 2024);
            var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

            var text = NoiseCalibration.Report(files, directory, Settings, drafts: 20, scales: [1, 2]);

            foreach (var expected in new[] { "mean pick", "real", "sim x1", "sim x2", "0-6", "84-120", "rms log ratio" }) Assert.Contains(expected, text);
        }
        finally { Directory.Delete(directory, true); }
    }

    [Fact]
    public void The_fit_ranks_noise_formulas_and_includes_the_current_one()
    {
        var directory = TempDirectory();
        try
        {
            WriteFfc(directory, 2024);
            var files = new Dictionary<int, ProjectionFile> { [2024] = BacktestFile(2024) };

            var text = NoiseCalibration.Fit(files, directory, Settings with { NoisePerAdp = 0.1 }, drafts: 20, bases: [1.0], slopes: [0.1, 0.2]);

            Assert.Contains("slope   0.1 ", text);
            Assert.Contains("slope   0.2 ", text);
            Assert.Contains("current setting base 1 slope 0.1", text);
        }
        finally { Directory.Delete(directory, true); }
    }
}
