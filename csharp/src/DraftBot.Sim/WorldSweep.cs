using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// One arm set on one projection world (a `--data` folder), reported both ways at once (mean starter points and title odds, each against the adopted advisor, paired) in
/// tab-separated RESULT lines that a driver can collect across worlds. The point is the sign check: a setting chosen on the validated files must keep its sign in the other
/// worlds (the refit files and noise-perturbed or outcome-resampled copies) before it is believed (LOG.md, 2026-10-29).
/// </summary>
public static class WorldSweep
{
    public const string HeadlineName = "adopted (l1000 w4 free1)";

    /// <summary>
    /// The arm sets: "reach" = the waiting-bonus weight (0 = plain `need`) at lambda 300 / 1000 / 3000, the reach cap and the first free pick; "need" = the roster-need terms (bench weights, the
    /// option value over the waiver level, the bench miss probability q, the starter option and the bye-week cover); "tiers" = no arms (the headline alone, for the tier-gap setting, which only
    /// changes the pool's valuation); "ladder" = the adopted advisor with its terms removed one level at a time (no waiting bonus, then no option value, then no roster need at all), for pricing each
    /// term in points and title odds. All against the adopted advisor.
    /// </summary>
    public static List<ValueRecommenderStrategy> Arms(string set = "reach")
    {
        var arms = new List<ValueRecommenderStrategy>();
        var reach = ValueRecommender.DefaultReach;
        var wait = ValueRecommender.DefaultWait;
        if (set == "reach")
        {
            foreach (var lambda in new[] { 300.0, 1000, 3000 })
                foreach (var weight in new[] { 0.0, 1, 2, 4, 8 })
                {
                    if (lambda == 1000 && weight == 4) continue;                                                   // the headline itself
                    arms.Add(new($"l{lambda:0} w{weight:0.##}", new ReachSettings(lambda, 4, FreePicks: 1), NeedSettings.Default, weight == 0 ? null : new WaitSettings(weight, Reachable: AlternativeReach.WithinCap)));
                }
            foreach (var cap in new[] { 2.0, 3, 6 })
                arms.Add(new($"cap {cap:0}", new ReachSettings(1000, cap, FreePicks: 1), NeedSettings.Default, wait));
            arms.Add(new("free 0 picks", new ReachSettings(1000, 4), NeedSettings.Default, wait));
        }
        else if (set == "need")
        {
            arms.Add(new("no bench value", reach, NeedSettings.NoBench, wait));
            arms.Add(new("structural weights, no option value", reach, NeedSettings.Structural, wait));
            foreach (var f in new[] { 0.1, 0.25, 0.5, 1.0 })
                arms.Add(new($"flat bench {f:0.##}", reach, new NeedSettings(f), wait));
            foreach (var q in new[] { 0.10, 0.15, 0.30, 0.40 })
                arms.Add(new($"q {q:0.##}", reach, NeedSettings.Option with { MissProbability = q }, wait));
            arms.Add(new("starter option 1", reach, NeedSettings.WithStarterOption(1), wait));
            arms.Add(new("bye cover", reach, NeedSettings.WithByes, wait));
        }
        else if (set == "spread")
        {
            foreach (var scale in new[] { 0.5, 2.0, 3, 4 })      // the advisor's survival spread told the opponents' noise (the sim's own noise is --noise); 1 is the headline
                arms.Add(new($"wait spread x{scale:0.#}", reach, NeedSettings.Default, new WaitSettings(4, SpreadScale: scale, Reachable: AlternativeReach.WithinCap)));
        }
        else if (set == "ladder")
        {
            arms.Add(new("no waiting bonus", reach, NeedSettings.Default));
            arms.Add(new("structural bench, no waiting bonus", reach, NeedSettings.Structural));
            arms.Add(new("plain VOR", reach));
        }
        return arms;
    }

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale, int firstSeed, string set = "reach")
    {
        var headline = new ValueRecommenderStrategy(HeadlineName, ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait);
        var arms = Arms(set);
        var strategies = new List<IDraftStrategy> { new AdpStrategy(), headline };
        strategies.AddRange(arms);
        var rows = Experiment.Run(files, settings, strategies, [noiseScale], seeds, firstSeed).Rows;
        var seasons = files.Keys.Order().ToList();
        var points = SweepMetric.Points.Selector();
        var title = SweepMetric.Title.Selector();
        var lines = new List<string>();
        foreach (var strategy in strategies.Where(s => s.Name != "adp"))
        {
            var (pDiff, pSe) = Experiment.PairedDifference(rows, strategy.Name, HeadlineName, points);
            var (tDiff, tSe) = Experiment.PairedDifference(rows, strategy.Name, HeadlineName, title);
            var (pAdp, pAdpSe) = Experiment.PairedDifference(rows, strategy.Name, "adp", points);
            var (tAdp, tAdpSe) = Experiment.PairedDifference(rows, strategy.Name, "adp", title);
            var bySeason = seasons.Select(s => rows.Where(r => r.Strategy == strategy.Name && r.Season == s).Average(points) - rows.Where(r => r.Strategy == HeadlineName && r.Season == s).Average(points));
            lines.Add(string.Join('\t', "RESULT", strategy.Name, F(pDiff), F(pSe), F(tDiff), F(tSe), F(pAdp), F(tAdp), string.Join(',', bySeason.Select(F))));
        }
        return string.Join(Environment.NewLine, lines);

        static string F(double x) => x.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
    }
}
