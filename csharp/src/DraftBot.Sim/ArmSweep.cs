using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Scores a set of strategy settings ("arms") over the backtests, next to fixed reference strategies, then
/// checks the choice leave-one-season-out: pick the best arm on four seasons, score it on the fifth.
/// The score is mean starter points by default, or head-to-head season odds (see <see cref="SweepMetric"/>).
/// </summary>
public static class ArmSweep
{
    /// <param name="references">Strategies shown for comparison; one must be named "adp".</param>
    /// <param name="headline">The reference the leave-one-season-out gain is measured against (besides ADP).</param>
    /// <param name="metric">What the arms are ranked and chosen by.</param>
    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds,
        IReadOnlyList<IDraftStrategy> arms, IReadOnlyList<IDraftStrategy> references, string headline, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points)
    {
        var rows = Experiment.Run(files, settings, references.Concat(arms).ToList(), noiseScales: [noiseScale], seeds).Rows;
        var seasons = files.Keys.Order().ToList();
        var value = metric.Selector();
        var f = metric.Format();

        double SeasonScore(string strategy, int season) => rows.Where(r => r.Strategy == strategy && r.Season == season).Average(value);
        double MeanScore(string strategy, IEnumerable<int> over) => over.Average(s => SeasonScore(strategy, s));
        var signedFormat = metric == SweepMetric.Points ? "+0;-0;0" : "+0.0;-0.0;0.0";
        string Signed(double x) => x.ToString(signedFormat);

        var lines = new List<string>
        {
            $"{rows.Count(r => r.Strategy == "adp")} drafts per arm, opponent noise x{noiseScale:0.##}. Score: {metric.Label()}; 'vs adp' is paired, +/- 1 SE.",
            $"  {"arm",-24}{"score",8}{"vs adp",16}{"vs " + headline,20}" + string.Concat(seasons.Select(s => $"{s,7}")),
        };
        var names = references.Concat(arms).Select(a => a.Name).ToList();
        foreach (var name in names.OrderByDescending(n => MeanScore(n, seasons)))
        {
            var (diff, se) = Experiment.PairedDifference(rows, name, "adp", value);
            var (headDiff, headSe) = Experiment.PairedDifference(rows, name, headline, value);
            lines.Add($"  {name,-24}{MeanScore(name, seasons).ToString(f),8}" + (name == "adp" ? $"{"",16}" : $"{Signed(diff),9} +/-{se.ToString(f),3}")
                      + (name == headline ? $"{"",20}" : $"{Signed(headDiff),13} +/-{headSe.ToString(f),3}")
                      + string.Concat(seasons.Select(s => $"{SeasonScore(name, s).ToString(f),7}")));
        }

        lines.Add("");
        lines.Add("leave-one-season-out: arm chosen on the other four seasons, scored on the held-out season");
        var gains = new List<double>();
        var versusAdp = new List<double>();
        foreach (var held in seasons)
        {
            var train = seasons.Where(s => s != held).ToList();
            var best = arms.MaxBy(a => MeanScore(a.Name, train))!;
            var score = SeasonScore(best.Name, held);
            gains.Add(score - SeasonScore(headline, held));
            versusAdp.Add(score - SeasonScore("adp", held));
            lines.Add($"  hold out {held}: chose {best.Name,-22} {score.ToString(f),6}   {headline} {SeasonScore(headline, held).ToString(f),6}   adp {SeasonScore("adp", held).ToString(f),6}");
        }
        lines.Add($"  held-out gain over {headline}: {Signed(gains.Average())} +/- {StdError(gains).ToString(f)} (SE over {seasons.Count} seasons)");
        lines.Add($"  held-out difference from plain ADP: {Signed(versusAdp.Average())} +/- {StdError(versusAdp).ToString(f)}");
        return string.Join(Environment.NewLine, lines);
    }

    static double StdError(IReadOnlyList<double> values)
    {
        var mean = values.Average();
        return Math.Sqrt(values.Sum(v => (v - mean) * (v - mean)) / Math.Max(1, values.Count - 1) / values.Count);
    }
}
