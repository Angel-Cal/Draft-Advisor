using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Scores a set of strategy settings ("arms") by starter points over the backtests, next to fixed reference strategies, then
/// checks the choice leave-one-season-out: pick the best arm on four seasons, score it on the fifth.
/// </summary>
public static class ArmSweep
{
    /// <param name="references">Strategies shown for comparison; one must be named "adp".</param>
    /// <param name="headline">The reference the leave-one-season-out gain is measured against (besides ADP).</param>
    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds,
        IReadOnlyList<IDraftStrategy> arms, IReadOnlyList<IDraftStrategy> references, string headline, double noiseScale = 1.0)
    {
        var rows = Experiment.Run(files, settings, references.Concat(arms).ToList(), noiseScales: [noiseScale], seeds).Rows;
        var seasons = files.Keys.Order().ToList();

        double SeasonPoints(string strategy, int season) => rows.Where(r => r.Strategy == strategy && r.Season == season).Average(r => r.Points);
        double MeanPoints(string strategy, IEnumerable<int> over) => over.Average(s => SeasonPoints(strategy, s));

        var lines = new List<string>
        {
            $"{rows.Count(r => r.Strategy == "adp")} drafts per arm, opponent noise x{noiseScale:0.##}. Points are mean starter points; 'vs adp' is paired, +/- 1 SE.",
            $"  {"arm",-24}{"points",8}{"vs adp",16}" + string.Concat(seasons.Select(s => $"{s,7}")),
        };
        var names = references.Concat(arms).Select(a => a.Name).ToList();
        foreach (var name in names.OrderByDescending(n => MeanPoints(n, seasons)))
        {
            var (diff, se) = Experiment.PairedDifference(rows, name, "adp");
            lines.Add($"  {name,-24}{MeanPoints(name, seasons),8:F0}" + (name == "adp" ? $"{"",16}" : $"{diff,+9:F0} +/-{se,3:F0}")
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
            gains.Add(points - SeasonPoints(headline, held));
            versusAdp.Add(points - SeasonPoints("adp", held));
            lines.Add($"  hold out {held}: chose {best.Name,-22} {points,6:F0} pts   {headline} {SeasonPoints(headline, held),6:F0}   adp {SeasonPoints("adp", held),6:F0}");
        }
        lines.Add($"  held-out gain over {headline}: {gains.Average():+0;-0} +/- {StdError(gains):0} (SE over {seasons.Count} seasons)");
        lines.Add($"  held-out difference from plain ADP: {versusAdp.Average():+0;-0} +/- {StdError(versusAdp):0}");
        return string.Join(Environment.NewLine, lines);
    }

    static double StdError(IReadOnlyList<double> values)
    {
        var mean = values.Average();
        return Math.Sqrt(values.Sum(v => (v - mean) * (v - mean)) / Math.Max(1, values.Count - 1) / values.Count);
    }
}
