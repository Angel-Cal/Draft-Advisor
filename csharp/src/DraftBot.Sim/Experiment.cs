using System.Globalization;
using DraftBot.Core;

namespace DraftBot.Sim;

/// <param name="WinPct">Share of head-to-head games won, averaged over random schedules; NaN when the file has no weekly points.</param>
/// <param name="Playoff">Probability of making the playoffs; NaN like <paramref name="WinPct"/>.</param>
/// <param name="Title">Probability of winning the title; NaN like <paramref name="WinPct"/>.</param>
public sealed record RunRow(int Season, double NoiseScale, int Seed, int Slot, string Strategy, double Points, int Finish,
    double WinPct = double.NaN, double Playoff = double.NaN, double Title = double.NaN);
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

        var done = 0;
        var clock = System.Diagnostics.Stopwatch.StartNew();
        Parallel.For(0, jobs.Count, i =>
        {
            var (season, scale, seed, slot) = jobs[i];
            var scaled = settings with { NoiseScale = scale };
            var results = strategies.Select(strategy =>
                (strategy, result: DraftSimulator.Run(pools[season], scaled, slot, strategy, seed, regretCalculators[season]))).ToArray();
            rows[i] = results.Select(r => new RunRow(season, scale, seed, slot, r.strategy.Name, r.result.Points, r.result.Finish,
                r.result.Odds?.WinPct ?? double.NaN, r.result.Odds?.PlayoffProbability ?? double.NaN, r.result.Odds?.TitleProbability ?? double.NaN)).ToArray();
            regrets[i] = results.SelectMany(r => r.result.Regrets.Select(pick =>
                new RegretRow(season, scale, seed, slot, r.strategy.Name, pick))).ToArray();
            var finished = Interlocked.Increment(ref done);
            if (finished % 10 == 0 || finished == jobs.Count) Console.Error.WriteLine($"  {finished}/{jobs.Count} drafts done, {clock.Elapsed:hh\\:mm\\:ss}");
        });
        return new ExperimentResult(rows.SelectMany(r => r).ToList(), regrets.SelectMany(r => r).ToList());
    }

    public static void WriteCsv(string path, IEnumerable<RunRow> rows)
    {
        var lines = rows.Select(r => string.Join(',', r.Season, r.NoiseScale.ToString(CultureInfo.InvariantCulture), r.Seed,
            r.Slot, r.Strategy, r.Points.ToString("F2", CultureInfo.InvariantCulture), r.Finish,
            r.WinPct.ToString("F4", CultureInfo.InvariantCulture), r.Playoff.ToString("F4", CultureInfo.InvariantCulture), r.Title.ToString("F4", CultureInfo.InvariantCulture)));
        File.WriteAllLines(path, lines.Prepend("season,noise_scale,seed,slot,strategy,points,finish,win_pct,playoff,title"));
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
            if (atScale.Any(r => !double.IsNaN(r.Title)))
            {
                lines.Add($"  head-to-head season, odds averaged over random schedules (playoff and title differences from {baseline} in percentage points, paired, +/- 1 SE)");
                lines.Add($"  {"strategy",-12}{"win%",8}{"playoffs",10}{"title",8}{"playoffs vs " + baseline,22}{"title vs " + baseline,20}");
                foreach (var group in atScale.GroupBy(r => r.Strategy))
                {
                    var (playoff, playoffSe) = PairedDifference(atScale, group.Key, baseline, r => 100 * r.Playoff);
                    var (title, titleSe) = PairedDifference(atScale, group.Key, baseline, r => 100 * r.Title);
                    lines.Add($"  {group.Key,-12}{group.Average(r => r.WinPct),8:P1}{group.Average(r => r.Playoff),10:P1}{group.Average(r => r.Title),8:P1}" +
                              (group.Key == baseline ? "" : $"{playoff,+13:F1} +/- {playoffSe:F1}{title,+11:F1} +/- {titleSe:F1}"));
                }
            }
            lines.Add("");
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>
    /// The strategy's edge over the baseline by draft slot (1 = first pick), one table per noise level: paired starter-points difference and, when the file has
    /// weekly points, the paired title-odds difference in percentage points, each +/- 1 SE over the seasons and seeds in that slot.
    /// </summary>
    public static string SummarizeBySlot(IReadOnlyList<RunRow> rows, string strategy, string baseline = "adp")
    {
        var lines = new List<string>();
        foreach (var scale in rows.Select(r => r.NoiseScale).Distinct().Order())
        {
            var atScale = rows.Where(r => r.NoiseScale == scale && (r.Strategy == strategy || r.Strategy == baseline)).ToList();
            var hasTitle = atScale.Any(r => !double.IsNaN(r.Title));
            lines.Add($"{strategy} vs {baseline} by draft slot, opponent noise x{scale:0.##} (paired, +/- 1 SE)");
            lines.Add($"  {"slot",4}{"drafts",8}{baseline + " pts",11}{"points diff",18}" + (hasTitle ? $"{"title diff (pp)",20}" : ""));
            foreach (var slot in atScale.Select(r => r.Slot).Distinct().Order())
            {
                var inSlot = atScale.Where(r => r.Slot == slot).ToList();
                var (points, pointsSe) = PairedDifference(inSlot, strategy, baseline);
                var line = $"  {slot + 1,4}{inSlot.Count(r => r.Strategy == strategy),8}{inSlot.Where(r => r.Strategy == baseline).Average(r => r.Points),11:F0}{points,+11:F1} +/- {pointsSe:F1}";
                if (hasTitle)
                {
                    var (title, titleSe) = PairedDifference(inSlot, strategy, baseline, r => 100 * r.Title);
                    line += $"{title,+12:F1} +/- {titleSe:F1}";
                }
                lines.Add(line);
            }
            lines.Add("");
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>
    /// Several arms against one baseline arm by draft slot, for one noise level: paired starter-points difference per slot (and title odds in percentage points
    /// when the file has weekly points), +/- 1 SE. Shows whether the best setting of an arm differs by slot.
    /// </summary>
    public static string SummarizeSlotArms(IReadOnlyList<RunRow> rows, IReadOnlyList<string> arms, string baseline)
    {
        var lines = new List<string>();
        foreach (var (label, metric) in new (string, Func<RunRow, double>)[] { ("starter points", r => r.Points), ("title odds, percentage points", r => 100 * r.Title) })
        {
            if (rows.All(r => double.IsNaN(r.Title)) && label.StartsWith("title")) continue;
            lines.Add($"{label}: each arm minus {baseline}, by draft slot (paired, +/- 1 SE)");
            lines.Add($"  {"slot",4}" + string.Concat(arms.Select(a => $"{a,22}")));
            foreach (var slot in rows.Select(r => r.Slot).Distinct().Order())
            {
                var inSlot = rows.Where(r => r.Slot == slot).ToList();
                lines.Add($"  {slot + 1,4}" + string.Concat(arms.Select(a =>
                {
                    var (diff, se) = PairedDifference(inSlot, a, baseline, metric);
                    return $"{diff,+14:F1} +/- {se,4:F1}";
                })));
            }
            lines.Add($"  {"all",4}" + string.Concat(arms.Select(a =>
            {
                var (diff, se) = PairedDifference(rows, a, baseline, metric);
                return $"{diff,+14:F1} +/- {se,4:F1}";
            })));
            lines.Add("");
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>
    /// Leave-one-season-out check of a slot-dependent setting: for each held-out season and each slot, take the arm (the baseline included) with the best mean
    /// on the other seasons, and score it on the held-out season. Reports the gain over the baseline averaged over slots, per season and its mean +/- SE over seasons.
    /// </summary>
    public static string SlotChoiceCheck(IReadOnlyList<RunRow> rows, IReadOnlyList<string> arms, string baseline)
    {
        var all = arms.Append(baseline).ToList();
        var seasons = rows.Select(r => r.Season).Distinct().Order().ToList();
        var slots = rows.Select(r => r.Slot).Distinct().Order().ToList();
        var lines = new List<string>();
        foreach (var (label, metric) in new (string, Func<RunRow, double>)[] { ("starter points", r => r.Points), ("title odds, percentage points", r => 100 * r.Title) })
        {
            if (rows.All(r => double.IsNaN(r.Title)) && label.StartsWith("title")) continue;
            double Mean(string arm, int slot, Func<int, bool> season) => rows.Where(r => r.Strategy == arm && r.Slot == slot && season(r.Season)).Average(metric);
            var gains = seasons.Select(held => slots.Average(slot =>
            {
                var chosen = all.MaxBy(arm => Mean(arm, slot, s => s != held))!;
                return Mean(chosen, slot, s => s == held) - Mean(baseline, slot, s => s == held);
            })).ToList();
            var mean = gains.Average();
            var se = Math.Sqrt(gains.Sum(g => (g - mean) * (g - mean)) / Math.Max(1, gains.Count - 1) / gains.Count);
            lines.Add($"{label}, best arm per slot chosen on the other seasons, gain over {baseline}: {mean:+0.0;-0.0;0.0} +/- {se:0.0} (SE over {gains.Count} seasons); by season "
                      + string.Join(" ", seasons.Zip(gains, (season, gain) => $"{season}: {gain:+0.0;-0.0;0.0}")));
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <param name="metric">What to compare; the run's starter points by default.</param>
    public static (double Mean, double StdError) PairedDifference(IReadOnlyList<RunRow> rows, string strategy, string baseline, Func<RunRow, double>? metric = null)
    {
        metric ??= r => r.Points;
        var reference = rows.Where(r => r.Strategy == baseline).ToDictionary(r => (r.Season, r.Seed, r.Slot), metric);
        var diffs = rows.Where(r => r.Strategy == strategy).Select(r => metric(r) - reference[(r.Season, r.Seed, r.Slot)]).ToList();
        var mean = diffs.Average();
        var variance = diffs.Sum(d => (d - mean) * (d - mean)) / Math.Max(1, diffs.Count - 1);
        return (mean, Math.Sqrt(variance / diffs.Count));
    }
}
