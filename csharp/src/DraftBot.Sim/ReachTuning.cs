using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Sweeps the reach penalty (lambda), the hard cap and the gap-term switch, scoring each arm by starter points over the
/// backtests, then checks the choice leave-one-season-out: pick the best arm on four seasons, score it on the fifth.
/// </summary>
public static class ReachTuning
{
    public static readonly double[] Lambdas = [0, 0.03, 0.1, 0.3, 1.0];
    public static readonly double[] Caps = [3, 4, 6];

    public static List<WindowedRecommenderStrategy> Arms() =>
        (from gap in new[] { true, false }
         from cap in Caps
         from lambda in Lambdas
         select new WindowedRecommenderStrategy($"l={lambda:0.##} cap={cap:0} {(gap ? "gap" : "nogap")}",
             new ReachSettings(lambda, cap, UseGapTerm: gap))).ToList();

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds)
    {
        var arms = Arms();
        var strategies = new List<IDraftStrategy> { new AdpStrategy(), new RecommenderStrategy() };
        strategies.AddRange(arms);
        var rows = Experiment.Run(files, settings, strategies, noiseScales: [1.0], seeds).Rows;
        var seasons = files.Keys.Order().ToList();

        double SeasonPoints(string strategy, int season) => rows.Where(r => r.Strategy == strategy && r.Season == season).Average(r => r.Points);
        double MeanPoints(string strategy, IEnumerable<int> over) => over.Average(s => SeasonPoints(strategy, s));

        var lines = new List<string>
        {
            $"{rows.Count(r => r.Strategy == "adp")} drafts per arm, opponent noise x1. Points are mean starter points; 'vs adp' is paired, +/- 1 SE.",
            $"  {"arm",-22}{"points",8}{"vs adp",16}" + string.Concat(seasons.Select(s => $"{s,7}")),
        };
        var names = new[] { "adp", "recommender" }.Concat(arms.Select(a => a.Name)).ToList();
        foreach (var name in names.OrderByDescending(n => MeanPoints(n, seasons)))
        {
            var (diff, se) = Experiment.PairedDifference(rows, name, "adp");
            lines.Add($"  {name,-22}{MeanPoints(name, seasons),8:F0}" + (name == "adp" ? $"{"",16}" : $"{diff,+9:F0} +/-{se,3:F0}")
                      + string.Concat(seasons.Select(s => $"{SeasonPoints(name, s),7:F0}")));
        }

        lines.Add("");
        lines.Add("leave-one-season-out: arm chosen on the other four seasons, scored on the held-out season");
        var gains = new List<double>();
        var versusAdp = new List<double>();
        foreach (var held in seasons)
        {
            var train = seasons.Where(s => s != held).ToList();
            var best = arms.MaxBy(a => MeanPoints(a.Name, train))!;
            var points = SeasonPoints(best.Name, held);
            gains.Add(points - SeasonPoints("recommender", held));
            versusAdp.Add(points - SeasonPoints("adp", held));
            lines.Add($"  hold out {held}: chose {best.Name,-20} {points,6:F0} pts   baseline recommender {SeasonPoints("recommender", held),6:F0}   adp {SeasonPoints("adp", held),6:F0}");
        }
        lines.Add($"  held-out gain over the baseline recommender: {Mean(gains):+0;-0} +/- {StdError(gains):0} (SE over {seasons.Count} seasons)");
        lines.Add($"  held-out difference from plain ADP:          {Mean(versusAdp):+0;-0} +/- {StdError(versusAdp):0}");
        return string.Join(Environment.NewLine, lines);
    }

    static double Mean(IReadOnlyList<double> values) => values.Average();

    static double StdError(IReadOnlyList<double> values)
    {
        var mean = values.Average();
        return Math.Sqrt(values.Sum(v => (v - mean) * (v - mean)) / Math.Max(1, values.Count - 1) / values.Count);
    }
}
