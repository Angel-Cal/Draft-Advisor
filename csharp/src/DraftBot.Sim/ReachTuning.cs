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

    public static readonly double[] WaitWeights = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0];

    /// <summary>Cost-of-waiting arms at the default reach and roster need: the weight on the expected shortfall of waiting.</summary>
    public static List<ValueRecommenderStrategy> WaitArms() =>
        WaitWeights.Select(w => new ValueRecommenderStrategy($"wait w={w:0.##}", ValueRecommender.DefaultReach, NeedSettings.Default, new WaitSettings(w))).ToList();

    public static string ReportWait(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, WaitArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default)],
            headline: "need", noiseScale, metric);

    /// <summary>
    /// Where does the adopted bonus (weight 4) earn its gain? The same bonus switched on only in a block of rounds or only for one position, and switched
    /// off only there (everything else on). If the gain sits in one block, a single constant is hiding structure.
    /// </summary>
    public static List<ValueRecommenderStrategy> WhereArms()
    {
        const int Rounds = 16;
        List<int> Span(int from, int to) => Enumerable.Range(from, to - from + 1).ToList();
        ValueRecommenderStrategy Arm(string name, IReadOnlyList<int>? rounds = null, IReadOnlyList<Position>? positions = null) =>
            new(name, ValueRecommender.DefaultReach, NeedSettings.Default, new WaitSettings(4, ActiveRounds: rounds, ActivePositions: positions));
        var blocks = new[] { (From: 1, To: 4), (From: 5, To: 9), (From: 10, To: 16) };
        var arms = new List<ValueRecommenderStrategy>();
        foreach (var (from, to) in blocks)
        {
            arms.Add(Arm($"rd {from}-{to} only", rounds: Span(from, to)));
            arms.Add(Arm($"all but rd {from}-{to}", rounds: Span(1, Rounds).Except(Span(from, to)).ToList()));
        }
        foreach (var position in Positions.All)
        {
            arms.Add(Arm($"{position} only", positions: [position]));
            arms.Add(Arm($"all but {position}", positions: Positions.All.Where(p => p != position).ToList()));
        }
        return arms;
    }

    /// <summary>
    /// The waiting bonus with the value and the shortfall standardized over the best 15 candidates at each pick (a unit-free mixing weight, 1 = equal importance),
    /// at several weights, against the adopted raw weight of 4.
    /// </summary>
    public static List<ValueRecommenderStrategy> StandardizedArms() =>
        new[] { 0.25, 0.5, 1.0, 2.0, 4.0 }.Select(w => new ValueRecommenderStrategy($"z-mix w={w:0.##}", ValueRecommender.DefaultReach, NeedSettings.Default,
            new WaitSettings(w, Standardize: true))).ToList();

    public static string ReportStandardized(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, StandardizedArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
             new ValueRecommenderStrategy("need+wait (adopted)", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait)],
            headline: "need+wait (adopted)", noiseScale, metric);

    /// <summary>The waiting bonus on for RB and TE only (where the where-sweep says it earns its gain), at several weights; WR and QB keep their one-step score.</summary>
    public static List<ValueRecommenderStrategy> ScarceArms() =>
        new[] { 2.0, 4.0, 6.0, 8.0 }.Select(w => new ValueRecommenderStrategy($"RB+TE w={w:0.##}", ValueRecommender.DefaultReach, NeedSettings.Default,
            new WaitSettings(w, ActivePositions: [Position.RB, Position.TE]))).ToList();

    public static string ReportScarce(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, ScarceArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
             new ValueRecommenderStrategy("need+wait (adopted)", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait)],
            headline: "need+wait (adopted)", noiseScale, metric);

    public static string ReportWhere(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, WhereArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
             new ValueRecommenderStrategy("need+wait (adopted)", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait)],
            headline: "need+wait (adopted)", noiseScale, metric);

    /// <summary>
    /// Waiting-bonus horizon arms: the bonus summed over my next H picks (equal weight, or each later pick halved), against the weight. If the best weight of 4
    /// at horizon 1 is standing in for later picks, a longer horizon should reach the same result at a weight near 1.
    /// </summary>
    public static List<ValueRecommenderStrategy> HorizonArms()
    {
        ValueRecommenderStrategy Arm(int horizon, double decay, double weight) =>
            new($"h={horizon}{(decay == 1.0 ? "" : $" d={decay:0.##}")} w={weight:0.##}", ValueRecommender.DefaultReach, NeedSettings.Default,
                new WaitSettings(weight, Horizon: horizon, HorizonDecay: decay));
        return
        [
            Arm(1, 1.0, 1), Arm(1, 1.0, 2), Arm(1, 1.0, 4),
            Arm(2, 1.0, 0.5), Arm(2, 1.0, 1), Arm(2, 1.0, 2),
            Arm(3, 1.0, 0.5), Arm(3, 1.0, 1), Arm(3, 1.0, 2),
            Arm(3, 0.5, 1), Arm(3, 0.5, 2),
        ];
    }

    public static string ReportHorizon(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, HorizonArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
             new ValueRecommenderStrategy("need+wait (adopted)", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait)],
            headline: "need+wait (adopted)", noiseScale, metric);

    public static readonly double[] LookaheadBetas = [0.5, 1.0, 2.0];
    public static readonly double[] LookaheadLambdas = [0, 100, 300, 1000];

    /// <summary>Two-step lookahead arms: weight on the next-turn term x reach cost (0 = no reach cost beyond the 4-sigma cap, which the lookahead might make unnecessary).</summary>
    public static List<ValueRecommenderStrategy> LookaheadArms() =>
        (from lambda in LookaheadLambdas
         from beta in LookaheadBetas
         select new ValueRecommenderStrategy($"look b={beta:0.##} l={lambda:0}", new ReachSettings(lambda, 4), NeedSettings.Default, lookahead: new LookaheadSettings(beta))).ToList();

    public static string ReportLookahead(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, LookaheadArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
             new ValueRecommenderStrategy("need+wait (adopted)", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait)],
            headline: "need+wait (adopted)", noiseScale, metric);

    public static readonly double[] ReachWaitLambdas = [100, 300, 1000, 3000];
    public static readonly double[] ReachWaitWeights = [0, 1.0, 2.0, 4.0];

    /// <summary>
    /// Reach cost x waiting weight. The reach cost was tuned before the waiting bonus existed and the two pull in opposite directions (stay near ADP /
    /// take him now), so the best weight may partly be undoing an over-strong reach cost. Weight 0 is plain `need` at that reach cost.
    /// </summary>
    public static List<ValueRecommenderStrategy> ReachWaitArms() =>
        (from lambda in ReachWaitLambdas
         from weight in ReachWaitWeights
         select new ValueRecommenderStrategy($"l={lambda:0} w={weight:0.##}", new ReachSettings(lambda, 4), NeedSettings.Default, weight == 0 ? null : new WaitSettings(weight))).ToList();

    public static string ReportReachWait(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, ReachWaitArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default)],
            headline: "need", noiseScale, metric);

    public static readonly double[] SpreadScales = [0.5, 0.7, 1.0];
    public static readonly double[] SpreadWeights = [1.0, 2.0, 4.0];

    /// <summary>Survival-spread arms: the pick spread behind the waiting bonus (1 = the reach spread, about 1.8x the real draft-to-draft spread) against the bonus weight.</summary>
    public static List<ValueRecommenderStrategy> SpreadArms() =>
        (from scale in SpreadScales
         from weight in SpreadWeights
         select new ValueRecommenderStrategy($"spread x{scale:0.##} w={weight:0.##}", ValueRecommender.DefaultReach, NeedSettings.Default, new WaitSettings(weight, scale))).ToList();

    public static string ReportSpread(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, SpreadArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
             new ValueRecommenderStrategy("need+wait (adopted)", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait)],
            headline: "need", noiseScale, metric);

    public static readonly double[] StarterWeights = [0.5, 1.0, 2.0, 4.0];

    /// <summary>Starter option-premium arms at the default reach: the weight on the value of being able to cut a busted starter, alone and with the waiting bonus.</summary>
    public static List<ValueRecommenderStrategy> StarterArms() =>
        StarterWeights.Select(w => new ValueRecommenderStrategy($"starter w={w:0.##}", ValueRecommender.DefaultReach, NeedSettings.WithStarterOption(w)))
            .Append(new ValueRecommenderStrategy("starter w=1 + wait w=2", ValueRecommender.DefaultReach, NeedSettings.WithStarterOption(1), new WaitSettings(2))).ToList();

    public static string ReportStarter(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, StarterArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default)],
            headline: "need", noiseScale, metric);

    public static string ReportBench(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, BenchArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("value", ValueRecommender.DefaultReach),
             new ValueRecommenderStrategy("need (no bench)", ValueRecommender.DefaultReach, NeedSettings.NoBench)],
            headline: "need (no bench)", noiseScale, metric);

    public static string ReportNeed(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, NeedArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new ValueRecommenderStrategy("value", ValueRecommender.DefaultReach)], headline: "value", noiseScale, metric);

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds) =>
        ArmSweep.Report(files, settings, seeds, Arms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new RecommenderStrategy()], headline: "recommender");

    public static string ReportValue(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0,
        SweepMetric metric = SweepMetric.Points) =>
        ArmSweep.Report(files, settings, seeds, ValueArms().Cast<IDraftStrategy>().ToList(),
            [new AdpStrategy(), new RecommenderStrategy(), new WindowedRecommenderStrategy("windowed", ReachSettings.Default)],
            headline: "windowed", noiseScale, metric);
}
