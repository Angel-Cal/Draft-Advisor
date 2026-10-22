using DraftBot.Core;
using DraftBot.Sim;

// dotnet run --project csharp/src/DraftBot.Sim -- backtest [--data DIR] [--seasons 2021-2025] [--seeds 50] [--out FILE.csv] [--tier-gap 0.1]
// dotnet run --project csharp/src/DraftBot.Sim -- diagnose [--season 2025] [--a adp] [--b windowed] [--seeds 30]
// dotnet run --project csharp/src/DraftBot.Sim -- decompose [--seeds 30]
// dotnet run --project csharp/src/DraftBot.Sim -- calibrate-noise [--drafts 150] [--scales 0.5,1,2,3] [--ffc data/raw/ffc]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-value [--seeds 30] [--noise 1]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-reach [--seeds 30] [--seasons 2021-2025]
// dotnet run --project csharp/src/DraftBot.Sim -- tune-tiers [--data DIR] [--seasons 2021-2025]
// dotnet run --project csharp/src/DraftBot.Sim -- draft [--season 2024] [--slot 6] [--seed 0] [--reveal true] [--recommender position|value] [--window true|L,CAP[,nogap]] [--data DIR]
// dotnet run --project csharp/src/DraftBot.Sim -- describe [--file projections_2026_v1.json] [--data DIR] [--tier-gap 0.1]

var command = args.FirstOrDefault() ?? "backtest";
var options = ParseOptions(args.Skip(1).ToArray());
var dataDir = options.GetValueOrDefault("data") ?? FindDataDirectory();
var settings = new SimSettings(new LeagueSettings());
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
            settings, options.GetValueOrDefault("a") ?? "adp", options.GetValueOrDefault("b") ?? "windowed",
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
    case "tune-value":
        Console.WriteLine(ReachTuning.ReportValue(
            ParseSeasons(options.GetValueOrDefault("seasons") ?? "2021-2025").ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json"))),
            settings, int.Parse(options.GetValueOrDefault("seeds") ?? "30"), double.Parse(options.GetValueOrDefault("noise") ?? "1")));
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
        new ValueRecommenderStrategy("value", ValueRecommender.DefaultReach)];
    var result = Experiment.Run(files, settings, strategies, noiseScales: [0.5, 1.0, 2.0], seeds);

    Console.WriteLine(Experiment.Summarize(result.Rows));
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
    var value = (options.GetValueOrDefault("recommender") ?? "position") == "value";
    var reach = ParseWindow(options.GetValueOrDefault("window")) ?? (value ? ValueRecommender.DefaultReach : null);
    return new MockDraft(file, settings, slot, seed, reveal, Console.In, Console.Out, reach, value).Run() ? 0 : 1;
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
