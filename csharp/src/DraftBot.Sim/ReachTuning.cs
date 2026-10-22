using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Sweeps the settings of the two recommenders that use <see cref="ReachSettings"/>: the position-first recommender
/// (lambda in score units, plus the gap-term switch) and the single-score value recommender (lambda in points).
/// </summary>
public static class ReachTuning
{
    public static readonly double[] Lambdas = [0, 0.03, 0.1, 0.3, 1.0];
    public static readonly double[] Caps = [3, 4, 6];
    public static readonly double[] ValueLambdas = [0, 10, 100, 400, 1000, 3000, 10000, 1000000];
    public static readonly double[] ValueCaps = [4];       // the cap stops mattering once lambda is large

    public static List<WindowedRecommenderStrategy> Arms() =>
        (from gap in new[] { true, false }
         from cap in Caps
         from lambda in Lambdas
         select new WindowedRecommenderStrategy($"l={lambda:0.##} cap={cap:0} {(gap ? "gap" : "nogap")}",
             new ReachSettings(lambda, cap, UseGapTerm: gap))).ToList();

    public static List<ValueRecommenderStrategy> ValueArms() =>
        (from cap in ValueCaps
         from lambda in ValueLambdas
         select new ValueRecommenderStrategy($"value l={lambda:0.##} cap={cap:0}", new ReachSettings(lambda, cap))).ToList();

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds) =>
        ArmSweep.Report(files, settings, seeds, Arms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new RecommenderStrategy()], headline: "recommender");

    public static string ReportValue(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0) =>
        ArmSweep.Report(files, settings, seeds, ValueArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new RecommenderStrategy(), new WindowedRecommenderStrategy("windowed", ReachSettings.Default)],
            headline: "windowed", noiseScale);
}
