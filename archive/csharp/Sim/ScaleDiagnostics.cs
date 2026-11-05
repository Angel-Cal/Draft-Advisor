using System.Collections.Concurrent;
using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// How big are the two things the waiting bonus mixes? At each of the drafter's picks, among the best candidates by one-step score: the spread (standard
/// deviation) of the values (before the reach cost), the spread of the expected shortfalls, and how closely they move together. If the shortfall varies about a quarter as
/// much as value, a raw weight of 4 is roughly equal importance in standardized units.
/// </summary>
public static class ScaleDiagnostics
{
    sealed record Row(int Round, double SdValue, double SdShortfall, double Correlation, double TopValueGap, double TopShortfallGap);

    sealed class Recorder(IDraftStrategy inner, ReachSettings reach, int pool) : IDraftStrategy
    {
        public List<Row> Rows { get; } = [];
        public string Name => inner.Name;

        public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
        {
            // weight 1 makes each candidate's WaitBonus its raw expected shortfall
            var ranked = ValueRecommender.Rank(state, reach, NeedSettings.Default, team, new WaitSettings(1));
            // value before the reach cost (the reach cost is a separate wall, so it is left out of the spread)
            var top = ranked.OrderByDescending(c => c.Score - (c.WaitBonus ?? 0)).Take(pool).Select(c => (OneStep: c.BaseValue, Shortfall: c.WaitBonus ?? 0)).ToList();
            if (top.Count >= 5)
            {
                var (meanV, sdV) = ValueRecommender.MeanAndSd(top.Select(x => x.OneStep));
                var (meanS, sdS) = ValueRecommender.MeanAndSd(top.Select(x => x.Shortfall));
                var corr = sdV < 1e-9 || sdS < 1e-9 ? 0 : top.Average(x => (x.OneStep - meanV) * (x.Shortfall - meanS)) / (sdV * sdS);
                Rows.Add(new Row(state.Round, sdV, sdS, corr, top[0].OneStep - top[1].OneStep, top.Max(x => x.Shortfall) - top.Min(x => x.Shortfall)));
            }
            return inner.Pick(state, team, legal);
        }
    }

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, int pool = 15)
    {
        var rows = new ConcurrentBag<Row>();
        var jobs = (from season in files.Keys from seed in Enumerable.Range(0, seeds) from slot in Enumerable.Range(0, settings.League.Teams) select (season, seed, slot)).ToList();
        var pools = files.ToDictionary(f => f.Key, f => Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));
        var adopted = new ValueRecommenderStrategy("need+wait", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait);
        Parallel.ForEach(jobs, job =>
        {
            var recorder = new Recorder(adopted, ValueRecommender.DefaultReach, pool);
            DraftSimulator.Run(pools[job.season], settings, job.slot, recorder, job.seed);
            foreach (var r in recorder.Rows) rows.Add(r);
        });
        var all = rows.ToList();

        var lines = new List<string>
        {
            $"{all.Count} picks by 'need+wait'; among the best {pool} candidates by one-step score at each pick (standard deviations in points):",
            $"  {"rounds",-10}{"sd value",10}{"sd shortfall",14}{"ratio v/s",11}{"corr",7}{"gap 1st-2nd",13}{"shortfall range",17}",
        };
        foreach (var (name, from, to) in new[] { ("1-2", 1, 2), ("3-4", 3, 4), ("5-9", 5, 9), ("10-16", 10, 16), ("all", 1, 99) })
        {
            var block = all.Where(r => r.Round >= from && r.Round <= to).ToList();
            if (block.Count == 0) continue;
            double sdV = block.Average(r => r.SdValue), sdS = block.Average(r => r.SdShortfall);
            lines.Add($"  {name,-10}{sdV,10:F1}{sdS,14:F1}{sdV / Math.Max(sdS, 1e-9),11:F1}{block.Average(r => r.Correlation),7:F2}{block.Average(r => r.TopValueGap),13:F1}{block.Average(r => r.TopShortfallGap),17:F1}");
        }
        return string.Join(Environment.NewLine, lines);
    }
}
