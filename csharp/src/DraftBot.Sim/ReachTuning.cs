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

    public static readonly double[] BenchFractions = [0, 0.1, 0.25, 0.5, 1.0];
    public static readonly double[] NeedLambdas = [400, 1000, 3000];

    /// <summary>Roster-need arms: bench fraction x reach lambda. A bench fraction of 1 is the plain single-score recommender.</summary>
    public static List<ValueRecommenderStrategy> NeedArms() =>
        (from lambda in NeedLambdas
         from beta in BenchFractions
         select new ValueRecommenderStrategy($"need b={beta:0.##} l={lambda:0}", new ReachSettings(lambda, 4), new NeedSettings(beta))).ToList();

    /// <summary>Bench-value arms at the default reach: flat fractions against the structural k-th-backup rule (with q varied around the measured value).</summary>
    public static List<ValueRecommenderStrategy> BenchArms() =>
    [
        new("bench flat 0.25", ValueRecommender.DefaultReach, new NeedSettings(0.25)),
        new("bench structural q=0.15", ValueRecommender.DefaultReach, new NeedSettings(1.0, 0.15)),
        new("bench structural q=0.23", ValueRecommender.DefaultReach, new NeedSettings(1.0, NeedSettings.MeasuredMissProbability)),
        new("bench structural q=0.35", ValueRecommender.DefaultReach, new NeedSettings(1.0, 0.35)),
        new("bench option q=0.23", ValueRecommender.DefaultReach, NeedSettings.Option),
        new("bench option q=0.15", ValueRecommender.DefaultReach, new NeedSettings(1.0, 0.15, OptionValue: true)),
        new("bench option q=0.35", ValueRecommender.DefaultReach, new NeedSettings(1.0, 0.35, OptionValue: true)),
        new("bench option q=0.23 l=10", new ReachSettings(10, 4), NeedSettings.Option),
        new("bench option q=0.23 l=30", new ReachSettings(30, 4), NeedSettings.Option),
        new("bench option q=0.23 l=100", new ReachSettings(100, 4), NeedSettings.Option),
        new("bench option q=0.23 l=300", new ReachSettings(300, 4), NeedSettings.Option),
        new("bench option flat 0.25", ValueRecommender.DefaultReach, new NeedSettings(0.25, OptionValue: true)),
        new("bench option flat 1", ValueRecommender.DefaultReach, new NeedSettings(1.0, OptionValue: true)),
    ];

    public static string ReportBench(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0) =>
        ArmSweep.Report(files, settings, seeds, BenchArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("value", ValueRecommender.DefaultReach),
             new ValueRecommenderStrategy("need (no bench)", ValueRecommender.DefaultReach, NeedSettings.NoBench)],
            headline: "need (no bench)", noiseScale);

    public static string ReportNeed(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0) =>
        ArmSweep.Report(files, settings, seeds, NeedArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("value", ValueRecommender.DefaultReach)], headline: "value", noiseScale);

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds) =>
        ArmSweep.Report(files, settings, seeds, Arms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new RecommenderStrategy()], headline: "recommender");

    public static string ReportValue(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0) =>
        ArmSweep.Report(files, settings, seeds, ValueArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new RecommenderStrategy(), new WindowedRecommenderStrategy("windowed", ReachSettings.Default)],
            headline: "windowed", noiseScale);
}
