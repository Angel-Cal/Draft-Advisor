using System.Globalization;
using DraftBot.Core;
using DraftBot.Sim;

// dotnet run -c Release --project csharp/src/DraftBot.Sim -- <command> [options]
//   describe [--file projections_2026_v1.json]                          the pool's starters, replacement levels and tiers
//   backtest [--seasons 2021-2025] [--seeds 50] [--out FILE.csv]        every baseline strategy and the adopted advisor against ADP, noise x0.5/1/2
//   draft [--season 2024] [--slot 6] [--seed 0] [--reveal true] [--recommender position|value|need|need-only|bench|option] [--window true|L,CAP]
//                                                                       interactive mock draft (need = the adopted advisor; need-only drops the waiting bonus)
//   pick-log [--seasons 2019-2025] [--seeds 100] [--out FILE.csv]       every own-team pick of plain ADP and the adopted advisor, as CSV
//   world-sweep [--arms reach|need|ladder|tiers|qb|cards] [--seeds 40] [--first-seed 100] [--noise 1]
//                                                                       an arm set against the adopted advisor on one projection world; RESULT lines for world_sweep.py
//   calibrate-deviations [--seeds 30] [--first-seed 0] [--noise 1] [--advisor full|nowait|structural|vor]
//                                                                       is the model calibrated on the decisions where the advisor departs from ADP?
//   case-reach --file projections_2026_v1.json --drafted "J.Gibbs,B.Robinson" [--team 5]
//                                                                       one draft state ranked by the advisor and two reach references, plus the advice
//   calibrate-noise [--drafts 150] [--scales 0.5,1,2,3] [--ffc data/raw/ffc] / fit-noise    the opponents' pick spread against real drafts
// Every command takes:
//   --data DIR (default data/processed/live) and --seasons A-B or A where it reads several seasons
//   the league: [--teams 12] [--qb 1] [--rb 2] [--wr 3] [--te 1] [--flex 1] [--bench 8] (default: the user's 1QB/2RB/3WR/1TE/1FLEX league; --wr 2 is the standard one)
//   the opponent style (default none): [--rb-earlier P] [--wr-earlier P] [--qb-earlier P] [--te-earlier P] [--run-pull P --run-window 6] [--need-pull P]
//   [--tier-gap 0.1] [--season-totals true] [--unrestricted true] (the evaluated drafter ignores the roster rules)
// The concluded experiment commands (tune-*, diagnose, decompose, trace-reach, calibrate-survival, ...) are in archive/csharp/Sim.

var command = args.FirstOrDefault() ?? "backtest";
var options = ParseOptions(args.Skip(1).ToArray());
var dataDir = Option("data") ?? FindDataDirectory();
var settings = Settings();

switch (command)
{
    case "describe":
        Describe(Option("file") ?? Path.Combine(dataDir, "projections_2026_v1.json"), settings);
        break;
    case "backtest":
        Backtest();
        break;
    case "draft":
        return Draft();
    case "pick-log":
    {
        IDraftStrategy[] strategies = [new AdpStrategy(), Adopted()];
        var output = Option("out") ?? Path.Combine(dataDir, "pick_log.csv");
        var n = PickLog.Write(Files("2019-2025"), settings, strategies, Int("seeds", 100), output);
        Console.WriteLine($"wrote {n} picks to {output}");
        break;
    }
    case "world-sweep":
        Console.WriteLine(WorldSweep.Report(Files(), settings, Int("seeds", 40), Double("noise", 1), Int("first-seed", 100), Option("arms") ?? "reach"));
        break;
    case "calibrate-deviations":
        Console.WriteLine(DeviationCalibration.Report(Files(), settings, Int("seeds", 30), Double("noise", 1), Int("first-seed", 0), Option("advisor") ?? "full"));
        break;
    case "case-reach":
        Console.WriteLine(CaseReport.Report(ProjectionFile.Load(Path.Combine(dataDir, Option("file") ?? "projections_2026_v1.json")), settings,
            (Option("drafted") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries), Int("team", 1) - 1));
        break;
    case "calibrate-noise":
        Console.WriteLine(NoiseCalibration.Report(Files(), FfcDirectory(), settings, Int("drafts", 150),
            (Option("scales") ?? "0.5,1,1.5,2,3,4").Split(',').Select(s => double.Parse(s, CultureInfo.InvariantCulture)).ToList()));
        break;
    case "fit-noise":
        Console.WriteLine(NoiseCalibration.Fit(Files(), FfcDirectory(), settings, Int("drafts", 150), [0, 0.5, 1, 1.5], [0.08, 0.1, 0.12, 0.14, 0.16, 0.18]));
        break;
    default:
        Console.Error.WriteLine($"unknown command '{command}' (see the top of Program.cs; the concluded experiment commands are in archive/csharp/Sim)");
        return 1;
}
return 0;

string? Option(string name) => options.GetValueOrDefault(name);
int Int(string name, int fallback) => Option(name) is { } text ? int.Parse(text, CultureInfo.InvariantCulture) : fallback;
double Double(string name, double fallback) => Option(name) is { } text ? double.Parse(text, CultureInfo.InvariantCulture) : fallback;
bool Bool(string name) => Option(name) is { } text && bool.Parse(text);

// One projection file per season of --seasons (or the command's default range), from the data folder.
Dictionary<int, ProjectionFile> Files(string defaultSeasons = "2021-2025") =>
    ParseSeasons(Option("seasons") ?? defaultSeasons).ToDictionary(y => y, y => ProjectionFile.Load(Path.Combine(dataDir, $"projections_{y}_v1.json")));

string FfcDirectory() => Option("ffc") ?? Path.Combine(dataDir, "..", "raw", "ffc");

ValueRecommenderStrategy Adopted() => new("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait);

// The simulator settings every command shares: league, opponent style, tier gap, weekly lineups and the roster rules.
SimSettings Settings()
{
    var defaults = new LeagueSettings();
    var league = new LeagueSettings(Int("teams", defaults.Teams), Int("qb", defaults.Qb), Int("rb", defaults.Rb), Int("wr", defaults.Wr),
        Int("te", defaults.Te), Int("flex", defaults.Flex), Int("bench", defaults.Bench));
    var result = new SimSettings(league) { WeeklyLineups = !Bool("season-totals"), StrategyFollowsRules = !Bool("unrestricted") };
    if (Option("tier-gap") is not null) result = result with { TierGapRmse = Double("tier-gap", result.TierGapRmse) };
    var style = new OpponentStyle(Double("qb-earlier", 0), Double("rb-earlier", 0), Double("wr-earlier", 0), Double("te-earlier", 0), Double("run-pull", 0),
        Int("run-window", 6), Double("need-pull", 0));      // opponents that are not "ADP plus noise": picks earlier than ADP by position, after a run, or for an open starter slot
    return style.IsDefault ? result : result with { Style = style };
}

void Backtest()
{
    IDraftStrategy[] strategies = [new AdpStrategy(), new VorStrategy(), new RecommenderStrategy(), new WindowedRecommenderStrategy("windowed", ReachSettings.Windowed),
        new ValueRecommenderStrategy("value", ValueRecommender.DefaultReach),
        new ValueRecommenderStrategy("need", ValueRecommender.DefaultReach, NeedSettings.Default),
        Adopted()];
    var result = Experiment.Run(Files(), settings, strategies, noiseScales: [0.5, 1.0, 2.0], Int("seeds", 50));

    Console.WriteLine(Experiment.Summarize(result.Rows));
    Console.WriteLine(Experiment.SummarizeBySlot(result.Rows, "need+wait"));
    Console.WriteLine(Experiment.SummarizeRegret(result.Regrets));
    var output = Option("out") ?? Path.Combine(SimOutputDirectory(dataDir), "sim_baseline.csv");
    var regretOutput = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(output))!, "sim_regret.csv");
    Experiment.WriteCsv(output, result.Rows);
    Experiment.WriteRegretCsv(regretOutput, result.Regrets);
    Console.WriteLine($"wrote {result.Rows.Count} rows to {output} and per-round regret to {regretOutput}");
}

int Draft()
{
    var file = ProjectionFile.Load(Path.Combine(dataDir, $"projections_{Int("season", 2024)}_v1.json"));
    var kind = Option("recommender") ?? "position";
    var value = kind is "value" or "need" or "need-only" or "bench" or "option";
    var reach = ParseWindow(Option("window")) ?? (value ? ValueRecommender.DefaultReach : null);
    var need = kind switch
    {
        "need" or "need-only" => NeedSettings.Default,
        "bench" => NeedSettings.Structural,
        "option" => NeedSettings.Option,
        _ => null,
    };
    return new MockDraft(file, settings, Int("slot", 6) - 1, Int("seed", 0), Bool("reveal"), Console.In, Console.Out, reach, value, need,
        kind == "need" ? ValueRecommender.DefaultWait : null).Run() ? 0 : 1;
}

static void Describe(string path, SimSettings settings)
{
    var file = ProjectionFile.Load(path);
    var valued = settings.Pool(file);
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

// --window true  -> the windowed baseline's reach settings;  --window 1000,4  -> lambda, cap in sigmas
static ReachSettings? ParseWindow(string? text)
{
    if (text is null || text.Equals("false", StringComparison.OrdinalIgnoreCase)) return null;
    if (text.Equals("true", StringComparison.OrdinalIgnoreCase)) return ReachSettings.Windowed;
    var parts = text.Split(',');
    return new ReachSettings(double.Parse(parts[0], CultureInfo.InvariantCulture), double.Parse(parts[1], CultureInfo.InvariantCulture));
}

static List<int> ParseSeasons(string text)
{
    var parts = text.Split('-');
    return parts.Length == 2
        ? Enumerable.Range(int.Parse(parts[0]), int.Parse(parts[1]) - int.Parse(parts[0]) + 1).ToList()
        : [int.Parse(text)];
}

/// <summary>Where a run writes its CSVs when --out is not given: data/processed/experiments/sims for the live folder (kept to the C# contract files), else the data folder itself.</summary>
static string SimOutputDirectory(string dataDir)
{
    var dir = new DirectoryInfo(Path.GetFullPath(dataDir));
    if (dir.Name != "live" || dir.Parent is null) return dataDir;
    return Directory.CreateDirectory(Path.Combine(dir.Parent.FullName, "experiments", "sims")).FullName;
}

static string FindDataDirectory()
{
    for (var dir = new DirectoryInfo(Directory.GetCurrentDirectory()); dir is not null; dir = dir.Parent)
    {
        var candidate = Path.Combine(dir.FullName, "data", "processed", "live");
        if (Directory.Exists(candidate)) return candidate;
    }
    throw new DirectoryNotFoundException("could not find data/processed/live; pass --data DIR");
}
