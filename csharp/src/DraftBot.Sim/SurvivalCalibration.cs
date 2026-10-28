using System.Collections.Concurrent;
using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Checks the survival model behind the waiting bonus: at each of the drafter's turns, the predicted chance that every available player is still
/// there at the drafter's next turn, against whether he was. One prediction per spread scale, so the scales can be compared on the same events.
/// </summary>
public static class SurvivalCalibration
{
    public sealed record Event(double[] Predicted, bool Survived, int Round, Position Position);

    /// <summary>Wraps a strategy and records survival predictions and outcomes without changing its picks.</summary>
    sealed class Recorder(IDraftStrategy inner, ReachSettings reach, double[] scales, IReadOnlyList<(string Label, OpponentModel Model)> simulated, int samples) : IDraftStrategy
    {
        readonly List<(string Id, double[] Predicted, int Round, Position Position)> pending = [];
        public List<Event> Events { get; } = [];
        public string Name => inner.Name;

        public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
        {
            var available = state.Available.Select(p => p.Id).ToHashSet();
            Events.AddRange(pending.Select(p => new Event(p.Predicted, available.Contains(p.Id), p.Round, p.Position)));
            pending.Clear();

            var pick = inner.Pick(state, team, legal);
            if (state.NextPick(team) is { } next)
            {
                var fromSampler = simulated.Select(m => SurvivalSampler.Survival(state, next, m.Model, samples)).ToList();
                foreach (var p in state.Available.Where(p => p.Id != pick.Id && p.Player.Adp is not null))
                {
                    var middle = WaitSettings.Survival(p.Player, next, reach);            // players that are certain either way tell us nothing
                    if (middle is > 1e-4 and < 1 - 1e-4)
                        pending.Add((p.Id, scales.Select(s => WaitSettings.Survival(p.Player, next, reach, s)).Concat(fromSampler.Select(d => d[p.Id])).ToArray(), state.Round, p.Position));
                }
            }
            return pick;
        }
    }

    /// <param name="simulated">Simulated-survival predictions to score next to the normal-model scales (see <see cref="SurvivalSampler"/>).</param>
    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, IDraftStrategy strategy,
        ReachSettings reach, double[] scales, IReadOnlyList<(string Label, OpponentModel Model)>? simulated = null, int samples = 40)
    {
        simulated ??= [];
        var labels = scales.Select(s => $"normal x{s:0.##}").Concat(simulated.Select(m => m.Label)).ToArray();
        var events = new ConcurrentBag<Event>();
        var jobs = (from season in files.Keys from seed in Enumerable.Range(0, seeds) from slot in Enumerable.Range(0, settings.League.Teams) select (season, seed, slot)).ToList();
        var pools = files.ToDictionary(f => f.Key, f => Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));
        Parallel.ForEach(jobs, job =>
        {
            var recorder = new Recorder(strategy, reach, scales, simulated, samples);
            DraftSimulator.Run(pools[job.season], settings, job.slot, recorder, job.seed);
            foreach (var e in recorder.Events) events.Add(e);
        });
        var all = events.ToList();

        double LogLoss(int s) => -all.Average(e => Math.Log(Math.Clamp(e.Survived ? e.Predicted[s] : 1 - e.Predicted[s], 1e-6, 1)));
        double Brier(int s) => all.Average(e => Math.Pow(e.Predicted[s] - (e.Survived ? 1 : 0), 2));

        var lines = new List<string>
        {
            $"{all.Count} predictions at {jobs.Count} drafts' turns by '{strategy.Name}' (spread = scale x ({reach.SigmaBase:0.##} + {reach.SigmaPerPick:0.##} x ADP)); observed survival {all.Average(e => e.Survived ? 1.0 : 0.0):P1}",
            $"  {"model",-24}{"log-loss",10}{"Brier",9}{"mean predicted",16}",
        };
        for (var s = 0; s < labels.Length; s++)
            lines.Add($"  {labels[s],-24}{LogLoss(s),10:F4}{Brier(s),9:F4}{all.Average(e => e.Predicted[s]),16:P1}");

        var best = Enumerable.Range(0, labels.Length).MinBy(LogLoss);
        foreach (var s in new[] { scales.ToList().IndexOf(1.0), best }.Where(s => s >= 0).Distinct())
        {
            lines.Add("");
            lines.Add($"reliability of {labels[s]}: predicted survival vs how often the player was still there");
            lines.Add($"  {"predicted",12}{"n",9}{"mean pred",11}{"observed",10}");
            var edges = new[] { 0.0, 0.05, 0.15, 0.3, 0.5, 0.7, 0.85, 0.95, 1.0001 };
            for (var b = 0; b < edges.Length - 1; b++)
            {
                var inBin = all.Where(e => e.Predicted[s] >= edges[b] && e.Predicted[s] < edges[b + 1]).ToList();
                if (inBin.Count > 0)
                    lines.Add($"  {$"{edges[b]:0.00}-{Math.Min(edges[b + 1], 1):0.00}",12}{inBin.Count,9}{inBin.Average(e => e.Predicted[s]),11:P1}{inBin.Average(e => e.Survived ? 1.0 : 0.0),10:P1}");
            }
        }

        lines.Add("");
        lines.Add($"log-loss by round block, {labels[best]} vs {labels[Math.Max(0, scales.ToList().IndexOf(1.0))]} (lower is better)");
        foreach (var (name, from, to) in new[] { ("rounds 1-3", 1, 3), ("rounds 4-8", 4, 8), ("rounds 9-16", 9, 16) })
        {
            var block = all.Where(e => e.Round >= from && e.Round <= to).ToList();
            var one = Math.Max(0, scales.ToList().IndexOf(1.0));
            double Loss(int s) => -block.Average(e => Math.Log(Math.Clamp(e.Survived ? e.Predicted[s] : 1 - e.Predicted[s], 1e-6, 1)));
            lines.Add($"  {name,-12}{Loss(best),8:F4}{Loss(one),9:F4}   n={block.Count}");
        }
        return string.Join(Environment.NewLine, lines);
    }
}
