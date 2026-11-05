using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// How well tiers built at a given threshold explain actual points, independent of any drafting strategy. Tiers use only
/// projections, so the actual points they are scored on are out of sample. Adjusted R-squared alone keeps rising as tiers get
/// finer (any fine partition of a projection-ordered list tracks actual points), so each gap-based partition is compared with
/// equal-size (quantile) tiers of the same count: the advantage is what placing boundaries at projection dropoffs adds.
/// </summary>
public static class TierTuning
{
    public sealed record TierScore(double AdjustedR2, double QuantileR2, int Tiers, double LargestTierShare)
    {
        public double Advantage => AdjustedR2 - QuantileR2;
    }

    public static readonly double[] Grid = [0.02, 0.03, 0.04, .. Enumerable.Range(1, 12).Select(i => Math.Round(i * 0.05, 2))];

    /// <summary>Score for one position of one season; null if the position has too few players to score.</summary>
    public static (double AdjustedR2, double QuantileR2, int N, int Tiers, int Largest)? ScorePosition(
        IReadOnlyList<Player> players, IReadOnlyDictionary<Position, double> rmse, Position position, double gapRmse)
    {
        var tiers = Valuator.Tiers(players, rmse, gapRmse);
        var rows = players.Where(p => p.Position == position).OrderByDescending(p => p.ProjectedPpr)
            .Select(p => (Tier: tiers[p.PlayerId], Actual: p.ActualPpr ?? throw new InvalidOperationException("tuning needs backtest files")))
            .ToList();
        var n = rows.Count;
        var count = rows.Select(r => r.Tier).Distinct().Count();
        if (n - count < 1 || n < 2) return null;

        var actual = rows.Select(r => r.Actual).ToList();
        var quantile = Enumerable.Range(0, n).Select(i => i * count / n).ToList();   // equal-size tiers, same count
        var gapScore = AdjustedR2(rows.Select(r => r.Tier).ToList(), actual);
        var quantileScore = AdjustedR2(quantile, actual);
        if (gapScore is null || quantileScore is null) return null;
        return (gapScore.Value, quantileScore.Value, n, count, rows.GroupBy(r => r.Tier).Max(g => g.Count()));
    }

    /// <summary>Adjusted R-squared of y on group labels; null if y has no variance or there are as many groups as players.</summary>
    public static double? AdjustedR2(IReadOnlyList<int> labels, IReadOnlyList<double> y)
    {
        var n = y.Count;
        var groups = labels.Select((label, i) => (label, i)).GroupBy(t => t.label).ToList();
        if (n - groups.Count < 1 || n < 2) return null;
        var mean = y.Average();
        var total = y.Sum(v => (v - mean) * (v - mean));
        if (total == 0) return null;
        var within = groups.Sum(g => { var m = g.Average(t => y[t.i]); return g.Sum(t => (y[t.i] - m) * (y[t.i] - m)); });
        return 1 - within / (n - groups.Count) / (total / (n - 1));
    }

    /// <summary>Season score: adjusted R-squared per position, weighted by players per position.</summary>
    public static TierScore Score(ProjectionFile file, double gapRmse)
    {
        var scored = Positions.All.Select(p => ScorePosition(file.Players, file.PositionRmse, p, gapRmse)).OfType<(double, double, int, int, int)>().ToList();
        var n = scored.Sum(s => s.Item3);
        return new TierScore(scored.Sum(s => s.Item1 * s.Item3) / n, scored.Sum(s => s.Item2 * s.Item3) / n,
            scored.Sum(s => s.Item4), (double)scored.Sum(s => s.Item5) / n);
    }

    /// <summary>
    /// Leave-one-season-out on the advantage over equal-size tiers: pick the grid value with the best mean advantage on the
    /// other seasons, score it on the held-out season, and compare with the current threshold on that same season.
    /// </summary>
    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, double current)
    {
        var seasons = files.Keys.Order().ToList();
        var grid = Grid.Append(current).Distinct().Order().ToList();
        var scores = grid.ToDictionary(k => k, k => seasons.ToDictionary(s => s, s => Score(files[s], k)));
        var lines = new List<string>
        {
            "advantage = adjusted R2 of gap-based tiers minus equal-size tiers of the same count (actual points; higher is better)",
            $"  {"k",5}" + string.Concat(seasons.Select(s => $"{s,9}")) + $"{"mean",8}{"R2",7}{"R2 qtl",8}{"tiers",7}{"biggest",9}",
        };
        foreach (var k in grid)
            lines.Add($"  {k,5:0.00}" + string.Concat(seasons.Select(s => $"{scores[k][s].Advantage,9:+0.000;-0.000}"))
                      + $"{seasons.Average(s => scores[k][s].Advantage),8:+0.000;-0.000}"
                      + $"{seasons.Average(s => scores[k][s].AdjustedR2),7:F3}{seasons.Average(s => scores[k][s].QuantileR2),8:F3}"
                      + $"{seasons.Average(s => scores[k][s].Tiers),7:F0}{seasons.Average(s => scores[k][s].LargestTierShare),9:P0}"
                      + (k == current ? "  <- current" : ""));

        lines.Add("");
        lines.Add($"leave-one-season-out (k chosen on the other seasons; compared with k={current:0.00} on the held-out season)");
        var diffs = new List<double>();
        foreach (var held in seasons)
        {
            var best = grid.MaxBy(k => seasons.Where(s => s != held).Average(s => scores[k][s].Advantage));
            var diff = scores[best][held].Advantage - scores[current][held].Advantage;
            diffs.Add(diff);
            lines.Add($"  hold out {held}: chose k={best:0.00}  held-out advantage {scores[best][held].Advantage:+0.000;-0.000} vs current {scores[current][held].Advantage:+0.000;-0.000}  ({diff:+0.000;-0.000})");
        }
        var mean = diffs.Average();
        var se = Math.Sqrt(diffs.Sum(d => (d - mean) * (d - mean)) / Math.Max(1, diffs.Count - 1) / diffs.Count);
        lines.Add($"  mean held-out gain over current: {mean:+0.000;-0.000} +/- {se:0.000} (SE over {diffs.Count} seasons)");

        lines.Add("");
        lines.Add("by position at each grid value (mean over seasons): advantage / tiers");
        lines.Add($"  {"k",5}" + string.Concat(Positions.All.Select(p => $"{p,14}")));
        foreach (var k in grid)
        {
            var cells = Positions.All.Select(p =>
            {
                var s = seasons.Select(season => ScorePosition(files[season].Players, files[season].PositionRmse, p, k)).OfType<(double, double, int, int, int)>().ToList();
                return s.Count == 0 ? "n/a" : $"{s.Average(x => x.Item1 - x.Item2):+0.000;-0.000} / {s.Average(x => x.Item4):F0}";
            });
            lines.Add($"  {k,5:0.00}" + string.Concat(cells.Select(c => $"{c,14}")));
        }
        return string.Join(Environment.NewLine, lines);
    }
}
