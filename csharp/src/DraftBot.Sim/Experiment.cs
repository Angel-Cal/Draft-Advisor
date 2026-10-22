using System.Globalization;
using DraftBot.Core;

namespace DraftBot.Sim;

public sealed record RunRow(int Season, double NoiseScale, int Seed, int Slot, string Strategy, double Points, int Finish);
public sealed record RegretRow(int Season, double NoiseScale, int Seed, int Slot, string Strategy, PickRegret Pick);
public sealed record ExperimentResult(List<RunRow> Rows, List<RegretRow> Regrets);

public static class Experiment
{
    /// <summary>
    /// Every strategy drafts from every slot against the same opponents (same seed, same biases), for each season and
    /// noise scale. Rows come back in a fixed order regardless of how the work was scheduled.
    /// </summary>
    public static ExperimentResult Run(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings,
        IReadOnlyList<IDraftStrategy> strategies, IReadOnlyList<double> noiseScales, int seeds)
    {
        var jobs = new List<(int Season, double Scale, int Seed, int Slot)>();
        foreach (var season in files.Keys.Order())
            foreach (var scale in noiseScales)
                for (var seed = 0; seed < seeds; seed++)
                    for (var slot = 0; slot < settings.League.Teams; slot++)
                        jobs.Add((season, scale, seed, slot));

        var pools = files.ToDictionary(f => f.Key,
            f => Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));
        var regretCalculators = pools.ToDictionary(p => p.Key, p => new RegretCalculator(p.Value, settings.League));
        var rows = new RunRow[jobs.Count][];
        var regrets = new RegretRow[jobs.Count][];

        Parallel.For(0, jobs.Count, i =>
        {
            var (season, scale, seed, slot) = jobs[i];
            var scaled = settings with { NoiseScale = scale };
            var results = strategies.Select(strategy =>
                (strategy, result: DraftSimulator.Run(pools[season], scaled, slot, strategy, seed, regretCalculators[season]))).ToArray();
            rows[i] = results.Select(r => new RunRow(season, scale, seed, slot, r.strategy.Name, r.result.Points, r.result.Finish)).ToArray();
            regrets[i] = results.SelectMany(r => r.result.Regrets.Select(pick =>
                new RegretRow(season, scale, seed, slot, r.strategy.Name, pick))).ToArray();
        });
        return new ExperimentResult(rows.SelectMany(r => r).ToList(), regrets.SelectMany(r => r).ToList());
    }

    public static void WriteCsv(string path, IEnumerable<RunRow> rows)
    {
        var lines = rows.Select(r => string.Join(',', r.Season, r.NoiseScale.ToString(CultureInfo.InvariantCulture), r.Seed,
            r.Slot, r.Strategy, r.Points.ToString("F2", CultureInfo.InvariantCulture), r.Finish));
        File.WriteAllLines(path, lines.Prepend("season,noise_scale,seed,slot,strategy,points,finish"));
    }

    /// <summary>Regret averaged over drafts, one row per season, noise level, strategy and round.</summary>
    public static void WriteRegretCsv(string path, IEnumerable<RegretRow> regrets)
    {
        string F(double value) => value.ToString("F2", CultureInfo.InvariantCulture);
        var lines = regrets.GroupBy(r => (r.Season, r.NoiseScale, r.Strategy, r.Pick.Round)).OrderBy(g => g.Key).Select(g => string.Join(',',
            g.Key.Season, g.Key.NoiseScale.ToString(CultureInfo.InvariantCulture), g.Key.Strategy, g.Key.Round,
            F(g.Average(r => r.Pick.Actual)), F(g.Average(r => r.Pick.ActualVorAdjusted)), F(g.Average(r => r.Pick.ProjectedVor))));
        File.WriteAllLines(path, lines.Prepend("season,noise_scale,strategy,round,actual,actual_vor_adjusted,projected_vor"));
    }

    /// <summary>Mean regret per strategy and round (rows are the strategy's own picks), for one opponent noise level.</summary>
    public static string SummarizeRegret(IReadOnlyList<RegretRow> regrets, double noiseScale = 1.0)
    {
        var atScale = regrets.Where(r => r.NoiseScale == noiseScale).ToList();
        var strategies = atScale.Select(r => r.Strategy).Distinct().ToList();
        var rounds = atScale.Select(r => r.Pick.Round).Distinct().Order().ToList();
        var drafts = strategies.ToDictionary(s => s, s => atScale.Where(r => r.Strategy == s).Select(r => (r.Season, r.Seed, r.Slot)).Distinct().Count());
        var lines = new List<string>();
        foreach (var (title, value) in new (string, Func<PickRegret, double>)[]
        {
            ("hindsight regret, actual points (best legal player's actual minus the pick's)", p => p.Actual),
            ("hindsight regret over replacement (actual minus the position's actual replacement level)", p => p.ActualVorAdjusted),
            ("foresight regret, projected VOR (best legal projected VOR minus the pick's)", p => p.ProjectedVor),
        })
        {
            lines.Add($"{title}, opponent noise x{noiseScale:0.##}");
            lines.Add($"  {"round",5}" + string.Concat(strategies.Select(s => $"{s,13}")));
            foreach (var round in rounds)
                lines.Add($"  {round,5}" + string.Concat(strategies.Select(s =>
                    $"{atScale.Where(r => r.Strategy == s && r.Pick.Round == round).Average(r => value(r.Pick)),13:F1}")));
            lines.Add($"  {"total",5}" + string.Concat(strategies.Select(s => $"{atScale.Where(r => r.Strategy == s).Sum(r => value(r.Pick)) / drafts[s],13:F0}")));
            lines.Add("");
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>Mean starter points, finish and top-3 rate per strategy, plus the paired points difference from the ADP baseline.</summary>
    public static string Summarize(IReadOnlyList<RunRow> rows, string baseline = "adp")
    {
        var lines = new List<string>();
        foreach (var scale in rows.Select(r => r.NoiseScale).Distinct().Order())
        {
            var atScale = rows.Where(r => r.NoiseScale == scale).ToList();
            lines.Add($"opponent noise x{scale:0.##}   ({atScale.Select(r => (r.Season, r.Seed, r.Slot)).Distinct().Count()} drafts per strategy)");
            lines.Add($"  {"strategy",-12}{"points",9}{"finish",8}{"top3",7}{"1st",7}   vs {baseline} (paired, +/- 1 SE)");
            foreach (var group in atScale.GroupBy(r => r.Strategy))
            {
                var (diff, se) = PairedDifference(atScale, group.Key, baseline);
                lines.Add($"  {group.Key,-12}{group.Average(r => r.Points),9:F1}{group.Average(r => r.Finish),8:F2}" +
                          $"{group.Average(r => r.Finish <= 3 ? 1.0 : 0.0),7:P0}{group.Average(r => r.Finish == 1 ? 1.0 : 0.0),7:P0}" +
                          (group.Key == baseline ? "" : $"   {diff,+7:F1} +/- {se:F1}"));
            }
            lines.Add($"  mean points by season: " + string.Join("  ", atScale.GroupBy(r => r.Strategy).Select(g =>
                g.Key + " " + string.Join("/", g.GroupBy(r => r.Season).OrderBy(s => s.Key).Select(s => s.Average(r => r.Points).ToString("F0"))))));
            lines.Add("");
        }
        return string.Join(Environment.NewLine, lines);
    }

    public static (double Mean, double StdError) PairedDifference(IReadOnlyList<RunRow> rows, string strategy, string baseline)
    {
        var reference = rows.Where(r => r.Strategy == baseline).ToDictionary(r => (r.Season, r.Seed, r.Slot), r => r.Points);
        var diffs = rows.Where(r => r.Strategy == strategy).Select(r => r.Points - reference[(r.Season, r.Seed, r.Slot)]).ToList();
        var mean = diffs.Average();
        var variance = diffs.Sum(d => (d - mean) * (d - mean)) / Math.Max(1, diffs.Count - 1);
        return (mean, Math.Sqrt(variance / diffs.Count));
    }
}
