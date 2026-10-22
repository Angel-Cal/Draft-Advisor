using System.Text.Json;
using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Compares the simulator's opponents with real drafts on one observable: how much a player's pick position varies from draft to
/// draft, by how early he goes. Real side: Fantasy Football Calculator's public ADP data (mean pick, standard deviation of the pick
/// and times drafted, over thousands of 12-team PPR mock drafts per season). Simulated side: all twelve teams are noisy-ADP bots,
/// the same bots the experiment uses, and the spread is measured across many seeded drafts.
/// </summary>
public static class NoiseCalibration
{
    public static readonly double[] Edges = [0, 6, 12, 24, 36, 60, 84, 120];
    const int MinRealDrafts = 30;

    public sealed record PlayerSpread(double MeanPick, double Sd);

    /// <summary>Real spreads from one FFC file: players drafted at least 30 times with a mean pick inside the last bucket.</summary>
    public static List<PlayerSpread> LoadReal(string path)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        return doc.RootElement.GetProperty("players").EnumerateArray()
            .Where(p => p.GetProperty("times_drafted").GetInt32() >= MinRealDrafts && p.GetProperty("adp").GetDouble() <= Edges[^1])
            .Select(p => new PlayerSpread(p.GetProperty("adp").GetDouble(), p.GetProperty("stdev").GetDouble()))
            .ToList();
    }

    /// <summary>Pick position of every player across <paramref name="drafts"/> drafts where all twelve teams are bots.</summary>
    public static List<PlayerSpread> Simulate(IReadOnlyList<ValuedPlayer> pool, SimSettings settings, int drafts)
    {
        var picks = new Dictionary<string, List<int>>();
        for (var seed = 0; seed < drafts; seed++)
        {
            var bots = Enumerable.Range(0, settings.League.Teams).Select(t => OpponentBot.Create(pool, settings, seed, t)).ToArray();
            var state = new DraftState(pool, settings.League);
            while (!state.IsComplete)
            {
                var team = state.CurrentTeam;
                var pick = bots[team].Pick(DraftRules.LegalPicks(state, team, settings));
                if (!picks.TryGetValue(pick.Id, out var list)) picks[pick.Id] = list = [];
                list.Add(state.OverallPick + 1);
                state.Draft(pick.Id);
            }
        }
        // only players taken in nearly every draft: a player who sometimes goes undrafted has a truncated spread
        return picks.Values.Where(l => l.Count >= 0.95 * drafts && l.Average() <= Edges[^1])
            .Select(l => new PlayerSpread(l.Average(), Math.Sqrt(l.Sum(x => (x - l.Average()) * (x - l.Average())) / (l.Count - 1))))
            .ToList();
    }

    static (double Sd, int N)[] ByBucket(IEnumerable<PlayerSpread> spreads)
    {
        var list = spreads.ToList();
        return Enumerable.Range(0, Edges.Length - 1).Select(i =>
        {
            var inBucket = list.Where(s => s.MeanPick > Edges[i] && s.MeanPick <= Edges[i + 1]).ToList();
            return (inBucket.Count == 0 ? double.NaN : inBucket.Average(s => s.Sd), inBucket.Count);
        }).ToArray();
    }

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, string ffcDirectory, SimSettings settings, int drafts,
        IReadOnlyList<double> scales)
    {
        var real = files.Keys.SelectMany(season => LoadReal(Path.Combine(ffcDirectory, $"ffc_ppr12_{season}.json"))).ToList();
        var realBuckets = ByBucket(real);

        var simulated = scales.ToDictionary(scale => scale, scale =>
        {
            var scaled = settings with { NoiseScale = scale };
            var spreads = files.SelectMany(f => Simulate(
                Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)), scaled, drafts)).ToList();
            return ByBucket(spreads);
        });

        var label = Enumerable.Range(0, Edges.Length - 1).Select(i => $"{Edges[i]:0}-{Edges[i + 1]:0}").ToArray();
        var lines = new List<string>
        {
            $"SD of a player's pick position across drafts, by how early he goes (picks). Real: FFC mock drafts; simulated: {drafts} all-bot drafts per season, 5 seasons.",
            $"  {"mean pick",-10}{"players",8}{"real",8}" + string.Concat(scales.Select(s => $"{"sim x" + s.ToString("0.##"),10}")),
        };
        for (var i = 0; i < label.Length; i++)
            lines.Add($"  {label[i],-10}{realBuckets[i].N,8}{realBuckets[i].Sd,8:F2}" + string.Concat(scales.Select(s => $"{simulated[s][i].Sd,10:F2}")));

        lines.Add("");
        lines.Add("fit: root-mean-square log ratio of simulated to real SD over the buckets (0 = perfect; 0.2 = typically 20% off)");
        foreach (var scale in scales)
        {
            var ratios = Enumerable.Range(0, label.Length).Where(i => !double.IsNaN(simulated[scale][i].Sd)).Select(i => Math.Log(simulated[scale][i].Sd / realBuckets[i].Sd)).ToList();
            lines.Add($"  x{scale,-5:0.##} rms log ratio {Math.Sqrt(ratios.Average(r => r * r)),5:F2}   mean ratio sim/real {Math.Exp(ratios.Average()),5:F2}   " +
                      "by bucket: " + string.Join(" ", Enumerable.Range(0, label.Length).Select(i => $"{simulated[scale][i].Sd / realBuckets[i].Sd:F2}")));
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>
    /// Grid search over the bias SD formula (base + per-ADP slope, scale 1) for the one whose simulated pick spread is closest to the real one,
    /// by root-mean-square log ratio over the same ADP buckets.
    /// </summary>
    public static string Fit(IReadOnlyDictionary<int, ProjectionFile> files, string ffcDirectory, SimSettings settings, int drafts,
        IReadOnlyList<double> bases, IReadOnlyList<double> slopes)
    {
        var realBuckets = ByBucket(files.Keys.SelectMany(season => LoadReal(Path.Combine(ffcDirectory, $"ffc_ppr12_{season}.json"))));
        var pools = files.ToDictionary(f => f.Key, f =>
            Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));

        var results = new List<(double Base, double Slope, double Rms, double[] Ratios)>();
        foreach (var b in bases)
            foreach (var slope in slopes)
            {
                var candidate = settings with { NoiseBase = b, NoisePerAdp = slope, NoiseScale = 1.0 };
                var simulated = ByBucket(pools.SelectMany(p => Simulate(p.Value, candidate, drafts)));
                var ratios = Enumerable.Range(0, realBuckets.Length).Select(i => simulated[i].Sd / realBuckets[i].Sd).ToArray();
                var logs = ratios.Where(r => !double.IsNaN(r)).Select(x => Math.Log(x)).ToList();
                results.Add((b, slope, Math.Sqrt(logs.Average(l => l * l)), ratios));
            }

        var lines = new List<string>
        {
            "bias SD = base + slope x ADP (x1). Fit to real pick spread; ratio sim/real by bucket " + string.Join(" ", Enumerable.Range(0, Edges.Length - 1).Select(i => $"{Edges[i]:0}-{Edges[i + 1]:0}")),
        };
        foreach (var r in results.OrderBy(r => r.Rms).Take(8))
            lines.Add($"  base {r.Base,4:0.##} slope {r.Slope,5:0.###}   rms log ratio {r.Rms,5:F3}   ratios " + string.Join(" ", r.Ratios.Select(x => $"{x:F2}")));
        var current = results.FirstOrDefault(r => r.Base == 1.0 && Math.Abs(r.Slope - 0.1) < 1e-9);
        if (current.Ratios is not null) lines.Add($"  (current setting base 1 slope 0.1: rms {current.Rms:F3})");
        return string.Join(Environment.NewLine, lines);
    }
}
