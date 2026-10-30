using DraftBot.Core;
using DraftBot.Sim;

// dotnet run --project csharp/src/DraftBot.Sim -- backtest [--data DIR] [--seasons 2021-2025] [--seeds 50] [--out FILE.csv] [--tier-gap 0.1]
// dotnet run --project csharp/src/DraftBot.Sim -- diagnose [--season 2025] [--a adp] [--b windowed] [--seeds 30] [--unrestricted true]
// dotnet run --project csharp/src/DraftBot.Sim -- decompose [--seeds 30]
// dotnet run --project csharp/src/DraftBot.Sim -- calibrate-noise [--drafts 150] [--scales 0.5,1,2,3] [--ffc data/raw/ffc]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-bench [--seeds 30] [--unrestricted true] [--season-totals true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-need [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-wait [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-spread [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-standardized [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- diagnose-scales [--seeds 30]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-scarce [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-where [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-horizon [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-lookahead [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-reach-wait [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-reach-survival [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-reach-picks [--seeds 30] [--first-seed 0] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- stability-reach [--seeds 20] [--first-seed 0] [--jitter 0.5] [--noise 1]   (share of advisor decisions whose pick changes when every ADP moves by about --jitter picks)
// dotnet run --project csharp/src/DraftBot.Sim -- case-reach --file projections_2026_v1.json --drafted "J.Gibbs,B.Robinson,J.Chase,P.Nacua" [--team 5]   (each reach variant's ranking in one state)
// dotnet run --project csharp/src/DraftBot.Sim -- world-sweep --data DIR [--arms reach|need|tiers] [--tier-gap 0.1] [--seeds 40] [--first-seed 100] [--noise 1]   (waiting weight x lambda, reach cap and free pick, or the roster-need terms, against the adopted advisor; RESULT lines for run_worlds.py)
// dotnet run --project csharp/src/DraftBot.Sim -- calibrate-deviations [--seeds 30] [--first-seed 0] [--noise 1] [--seasons 2021-2025]   (is the model calibrated on the decisions where the advisor departs from ADP? slope of actual on projected value difference, with a control pair)
// dotnet run --project csharp/src/DraftBot.Sim -- trace-reach [--seeds 30] [--first-seed 0] [--noise 1]   (reach-cost variants asked in the adopted advisor's own states: how often they differ, what the differing picks were worth)
// dotnet run --project csharp/src/DraftBot.Sim -- tune-reach-free [--seeds 30] [--first-seed 0] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- calibrate-survival [--seeds 30] [--noise 1] [--scales 0.4,0.55,0.7,0.85,1,1.25]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-rollout [--seeds 3] [--samples 20] [--candidates 5] [--noise 1] [--metric points|wins|playoffs|title]  (slow)
// dotnet run --project csharp/src/DraftBot.Sim -- tune-reachable [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-survival [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-slot [--seeds 30] [--noise 1]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-bye [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-starter [--seeds 30] [--unrestricted true] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-value [--seeds 30] [--noise 1] [--metric points|wins|playoffs|title]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-reach [--seeds 30] [--seasons 2021-2025]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-tiers [--data DIR] [--seasons 2021-2025]
// dotnet run --project csharp/src/DraftBot.Sim -- draft [--season 2024] [--slot 6] [--seed 0] [--reveal true] [--recommender position|value|need|need-only|bench|option]   (need = roster need + cost of waiting, the default advisor; need-only drops the waiting bonus) [--window true|L,CAP[,nogap]] [--data DIR]
// Every command takes the league: [--teams 12] [--qb 1] [--rb 2] [--wr 3] [--te 1] [--flex 1] [--bench 8] (the default is the user's 1QB/2RB/3WR/1TE/1FLEX league; --wr 2 is the standard one).
// dotnet run --project csharp/src/DraftBot.Sim -- describe [--file projections_2026_v1.json] [--data DIR] [--tier-gap 0.1]

var command = args.FirstOrDefault() ?? "backtest";
var options = ParseOptions(args.Skip(1).ToArray());
var dataDir = options.GetValueOrDefault("data") ?? FindDataDirectory();
int LeagueOption(string name, int fallback) => int.Parse(options.GetValueOrDefault(name) ?? fallback.ToString());
var defaults = new LeagueSettings();
var settings = new SimSettings(new LeagueSettings(Teams: LeagueOption("teams", defaults.Teams), Qb: LeagueOption("qb", defaults.Qb), Rb: LeagueOption("rb", defaults.Rb), Wr: LeagueOption("wr", defaults.Wr),
    Te: LeagueOption("te", defaults.Te), Flex: LeagueOption("flex", defaults.Flex), Bench: LeagueOption("bench", defaults.Bench)));      // every command: --wr 2 gives the standard 1QB/2RB/2WR/1TE/1FLEX league
if (options.TryGetValue("season-totals", out var seasonTotals) && bool.Parse(seasonTotals)) settings = settings with { WeeklyLineups = false };
if (options.TryGetValue("tier-gap", out var tierGap)) settings = settings with { TierGapRmse = double.Parse(tierGap) };

switch (command)
{
    case "describe":
        Describe(options.GetValueOrDefault("file") ?? Path.Combine(dataDir, "projections_2026_v1.json"), settings);
        break;
    case "backtest":
        Backtest(dataDir, options, settings);
        break;
    case "draft":
        return Draft(dataDir, options, settings);
    case "diagnose":
        Console.WriteLine(PickDiagnostics.Report(
            ProjectionFile.Load(Path.Combine(dataDir, $"projections_{options.GetValueOrDefault("season") ?? "2025"}_v1.json")),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            options.GetValueOrDefault("a") ?? "adp", options.GetValueOrDefault("b") ?? "windowed",
            int.Parse(options.GetValueOrDefault("seeds") ?? "30")));
        break;
    case "decompose":
        Console.WriteLine(Decomposition.Report(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings, int.Parse(options.GetValueOrDefault("seeds") ?? "30")));
        break;
    case "calibrate-noise":
        Console.WriteLine(NoiseCalibration.Report(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            options.GetValueOrDefault("ffc") ?? Path.Combine(dataDir, "..", "raw", "ffc"), settings, int.Parse(options.GetValueOrDefault("drafts") ?? "150"),
            (options.GetValueOrDefault("scales") ?? "0.5,1,1.5,2,3,4").Split(',').Select(double.Parse).ToList()));
        break;
    case "fit-noise":
        Console.WriteLine(NoiseCalibration.Fit(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            options.GetValueOrDefault("ffc") ?? Path.Combine(dataDir, "..", "raw", "ffc"), settings, int.Parse(options.GetValueOrDefault("drafts") ?? "150"),
            [0, 0.5, 1, 1.5], [0.08, 0.1, 0.12, 0.14, 0.16, 0.18]));
        break;
    case "tune-bench":
        Console.WriteLine(ReachTuning.ReportBench(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-need":
        Console.WriteLine(ReachTuning.ReportNeed(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-wait":
        Console.WriteLine(ReachTuning.ReportWait(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-spread":
        Console.WriteLine(ReachTuning.ReportSpread(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-standardized":
        Console.WriteLine(ReachTuning.ReportStandardized(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "diagnose-scales":
        Console.WriteLine(ScaleDiagnostics.Report(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings, int.Parse(options.GetValueOrDefault("seeds") ?? "30")));
        break;
    case "tune-scarce":
        Console.WriteLine(ReachTuning.ReportScarce(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-where":
        Console.WriteLine(ReachTuning.ReportWhere(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-horizon":
        Console.WriteLine(ReachTuning.ReportHorizon(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-lookahead":
        Console.WriteLine(ReachTuning.ReportLookahead(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-reach-wait":
        Console.WriteLine(ReachTuning.ReportReachWait(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-reach-survival":
        Console.WriteLine(ReachTuning.ReportReachSurvival(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-reach-picks":
        Console.WriteLine(ReachTuning.ReportReachPicks(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric")),
            int.Parse(options.GetValueOrDefault("first-seed") ?? "0")));
        break;
    case "stability-reach":
        Console.WriteLine(ReachTrace.StabilityReport(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "20"), double.Parse(options.GetValueOrDefault("jitter") ?? "0.5"), double.Parse(options.GetValueOrDefault("noise") ?? "1"),
            int.Parse(options.GetValueOrDefault("first-seed") ?? "0")));
        break;
    case "case-reach":
        Console.WriteLine(ReachTrace.CaseReport(ProjectionFile.Load(Path.Combine(dataDir, options.GetValueOrDefault("file") ?? "projections_2026_v1.json")), settings,
            (options.GetValueOrDefault("drafted") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries), int.Parse(options.GetValueOrDefault("team") ?? "1") - 1));
        break;
    case "world-sweep":
        Console.WriteLine(WorldSweep.Report(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "40"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), int.Parse(options.GetValueOrDefault("first-seed") ?? "100"), options.GetValueOrDefault("arms") ?? "reach"));
        break;
    case "calibrate-deviations":
        Console.WriteLine(DeviationCalibration.Report(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), int.Parse(options.GetValueOrDefault("first-seed") ?? "0")));
        break;
    case "trace-reach":
        Console.WriteLine(ReachTrace.Report(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), int.Parse(options.GetValueOrDefault("first-seed") ?? "0")));
        break;
    case "tune-reach-free":
        Console.WriteLine(ReachTuning.ReportReachFree(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric")),
            int.Parse(options.GetValueOrDefault("first-seed") ?? "0")));
        break;
    case "calibrate-survival":
        Console.WriteLine(SurvivalCalibration.Report(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { NoiseScale = double.Parse(options.GetValueOrDefault("noise") ?? "1") }, int.Parse(options.GetValueOrDefault("seeds") ?? "30"),
            new ValueRecommenderStrategy("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait), ReachSettings.Default,
            (options.GetValueOrDefault("scales") ?? "0.4,0.55,0.7,0.85,1,1.25").Split(',').Select(double.Parse).ToArray(),
            bool.Parse(options.GetValueOrDefault("simulated") ?? "false") ? [("simulated, rules", new OpponentModel()), ("simulated, no rules", OpponentModel.NoRules)] : null));
        break;
    case "tune-rollout":
        Console.WriteLine(ReachTuning.ReportRollout(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "3"), int.Parse(options.GetValueOrDefault("samples") ?? "20"), int.Parse(options.GetValueOrDefault("candidates") ?? "5"),
            double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-reachable":
        Console.WriteLine(ReachTuning.ReportReachable(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-survival":
        Console.WriteLine(ReachTuning.ReportSimulatedSurvival(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-slot":
        Console.WriteLine(ReachTuning.ReportSlot(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings, int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1")));
        break;
    case "tune-bye":
        Console.WriteLine(ReachTuning.ReportBye(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-starter":
        Console.WriteLine(ReachTuning.ReportStarter(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings with { StrategyFollowsRules = !bool.Parse(options.GetValueOrDefault("unrestricted") ?? "false") },
            int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"), SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-value":
        Console.WriteLine(ReachTuning.ReportValue(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings, int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1"),
            SweepMetrics.Parse(options.GetValueOrDefault("metric"))));
        break;
    case "tune-reach":
        TuneReach(dataDir, options, settings);
        break;
    case "tune-tiers":
        TuneTiers(dataDir, options, settings);
        break;
    default:
        Console.Error.WriteLine($"unknown command '{command}' (use backtest, draft, tune-tiers or describe)");
        return 1;
}
return 0;

static void Backtest(string dataDir, Dictionary<string, string> options, SimSettings settings)
{
    var seasons = ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025");
    var seeds = int.Parse(options.GetValueOrDefault("seeds") ?? "50");
    var files = seasons.ToDictionary(s => s, s => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{s}_v1.json")));

    IDraftStrategy[] strategies = [new AdpStrategy(), new VorStrategy(), new RecommenderStrategy(), new WindowedRecommenderStrategy("windowed", ReachSettings.Default),
        new ValueRecommenderStrategy("value", ValueRecommender.DefaultReach),
        new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
        new ValueRecommenderStrategy("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait)];
    var result = Experiment.Run(files, settings, strategies, noiseScales: [0.5, 1.0, 2.0], seeds);

    Console.WriteLine(Experiment.Summarize(result.Rows));
    Console.WriteLine(Experiment.SummarizeBySlot(result.Rows, "need+wait"));
    Console.WriteLine(Experiment.SummarizeRegret(result.Regrets));
    var output = options.GetValueOrDefault("out") ?? Path.Combine(dataDir, "sim_baseline.csv");
    var regretOutput = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(output))!, "sim_regret.csv");
    Experiment.WriteCsv(output, result.Rows);
    Experiment.WriteRegretCsv(regretOutput, result.Regrets);
    Console.WriteLine($"wrote {result.Rows.Count} rows to {output} and per-round regret to {regretOutput}");
}

static void TuneTiers(string dataDir, Dictionary<string, string> options, SimSettings settings)
{
    var seasons = ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025");
    var files = seasons.ToDictionary(s => s, s => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{s}_v1.json")));
    Console.WriteLine(TierTuning.Report(files, settings.TierGapRmse));
}

static int Draft(string dataDir, Dictionary<string, string> options, SimSettings settings)
{
    var season = int.Parse(options.GetValueOrDefault("season") ?? "2024");
    var file = ProjectionFile.Load(Path.Combine(dataDir, $"projections_{season}_v1.json"));
    var slot = int.Parse(options.GetValueOrDefault("slot") ?? "6") - 1;
    var seed = int.Parse(options.GetValueOrDefault("seed") ?? "0");
    var reveal = bool.Parse(options.GetValueOrDefault("reveal") ?? "false");
    var kind = options.GetValueOrDefault("recommender") ?? "position";
    var value = kind is "value" or "need" or "need-only" or "bench" or "option";
    var reach = ParseWindow(options.GetValueOrDefault("window")) ?? (value ? ValueRecommender.DefaultReach : null);
    var need = kind is "need" or "need-only" ? NeedSettings.Default : kind == "bench" ? NeedSettings.Structural : kind == "option" ? NeedSettings.Option : null;
    return new MockDraft(file, settings, slot, seed, reveal, Console.In, Console.Out, reach, value, need, kind == "need" ? ValueRecommender.DefaultWait : null).Run() ? 0 : 1;
}

static void TuneReach(string dataDir, Dictionary<string, string> options, SimSettings settings)
{
    var seasons = ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025");
    var seeds = int.Parse(options.GetValueOrDefault("seeds") ?? "30");
    var files = seasons.ToDictionary(s => s, s => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{s}_v1.json")));
    Console.WriteLine(ReachTuning.Report(files, settings, seeds));
}

static void Describe(string path, SimSettings settings)
{
    var file = ProjectionFile.Load(path);
    var valued = Valuator.Value(file.Players, file.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse));
    var starters = ReplacementLevel.StarterCounts(file.Players, settings.League);
    var replacement = ReplacementLevel.Points(file.Players, settings.League);

    Console.WriteLine($"{Path.GetFileName(path)}: {file.Kind}, season {file.Season}, {file.Players.Count} players, adp {file.AdpSource}");
    Console.WriteLine($"league: {settings.League.Teams} teams, tier gap {settings.TierGapRmse} x RMSE");
    foreach (var position in Positions.All)
    {
        var tiers = valued.Where(v => v.Position == position).GroupBy(v => v.Tier).OrderBy(g => g.Key).Select(g => g.Count());
        Console.WriteLine($"  {position}: {starters[position],2} starters league-wide, replacement {replacement[position],6:F1} pts"
                          + $" (rmse {file.PositionRmse[position]:F1}), tier sizes {string.Join(" ", tiers)}");
    }
}

static Dictionary<string, string> ParseOptions(string[] args)
{
    var options = new Dictionary<string, string>();
    for (var i = 0; i + 1 < args.Length; i += 2)
        options[args[i].TrimStart('-')] = args[i + 1];
    return options;
}

// --window true  -> the default reach settings;  --window 0.3,4  or  0.3,4,nogap  -> lambda, cap in sigmas, optionally without the gap term
static ReachSettings? ParseWindow(string? text)
{
    if (text is null || text.Equals("false", StringComparison.OrdinalIgnoreCase)) return null;
    if (text.Equals("true", StringComparison.OrdinalIgnoreCase)) return ReachSettings.Default;
    var parts = text.Split(',');
    return new ReachSettings(double.Parse(parts[0]), double.Parse(parts[1]), UseGapTerm: !(parts.Length > 2 && parts[2] == "nogap"));
}

static List<int> ParseSeasons(string text)
{
    var parts = text.Split('-');
    return parts.Length == 2
        ? Enumerable.Range(int.Parse(parts[0]), int.Parse(parts[1]) - int.Parse(parts[0]) + 1).ToList()
        : [int.Parse(text)];
}

static string FindDataDirectory()
{
    for (var dir = new DirectoryInfo(Directory.GetCurrentDirectory()); dir is not null; dir = dir.Parent)
    {
        var candidate = Path.Combine(dir.FullName, "data", "processed");
        if (Directory.Exists(candidate)) return candidate;
    }
    throw new DirectoryNotFoundException("could not find data/processed; pass --data DIR");
}
