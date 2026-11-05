// Archived from csharp/src/DraftBot.Sim/Experiment.cs (static class Experiment): only `tune-slot` (ReachTuning.ReportSlot) used these.

    /// <summary>
    /// Several arms against one baseline arm by draft slot, for one noise level: paired starter-points difference per slot (and title odds in percentage points
    /// when the file has weekly points), +/- 1 SE. Shows whether the best setting of an arm differs by slot.
    /// </summary>
    public static string SummarizeSlotArms(IReadOnlyList<RunRow> rows, IReadOnlyList<string> arms, string baseline)
    {
        var lines = new List<string>();
        foreach (var (label, metric) in new (string, Func<RunRow, double>)[] { ("starter points", r => r.Points), ("title odds, percentage points", r => 100 * r.Title) })
        {
            if (rows.All(r => double.IsNaN(r.Title)) && label.StartsWith("title")) continue;
            lines.Add($"{label}: each arm minus {baseline}, by draft slot (paired, +/- 1 SE)");
            lines.Add($"  {"slot",4}" + string.Concat(arms.Select(a => $"{a,22}")));
            foreach (var slot in rows.Select(r => r.Slot).Distinct().Order())
            {
                var inSlot = rows.Where(r => r.Slot == slot).ToList();
                lines.Add($"  {slot + 1,4}" + string.Concat(arms.Select(a =>
                {
                    var (diff, se) = PairedDifference(inSlot, a, baseline, metric);
                    return $"{diff,+14:F1} +/- {se,4:F1}";
                })));
            }
            lines.Add($"  {"all",4}" + string.Concat(arms.Select(a =>
            {
                var (diff, se) = PairedDifference(rows, a, baseline, metric);
                return $"{diff,+14:F1} +/- {se,4:F1}";
            })));
            lines.Add("");
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>
    /// Leave-one-season-out check of a slot-dependent setting: for each held-out season and each slot, take the arm (the baseline included) with the best mean
    /// on the other seasons, and score it on the held-out season. Reports the gain over the baseline averaged over slots, per season and its mean +/- SE over seasons.
    /// </summary>
    public static string SlotChoiceCheck(IReadOnlyList<RunRow> rows, IReadOnlyList<string> arms, string baseline)
    {
        var all = arms.Append(baseline).ToList();
        var seasons = rows.Select(r => r.Season).Distinct().Order().ToList();
        var slots = rows.Select(r => r.Slot).Distinct().Order().ToList();
        var lines = new List<string>();
        foreach (var (label, metric) in new (string, Func<RunRow, double>)[] { ("starter points", r => r.Points), ("title odds, percentage points", r => 100 * r.Title) })
        {
            if (rows.All(r => double.IsNaN(r.Title)) && label.StartsWith("title")) continue;
            double Mean(string arm, int slot, Func<int, bool> season) => rows.Where(r => r.Strategy == arm && r.Slot == slot && season(r.Season)).Average(metric);
            var gains = seasons.Select(held => slots.Average(slot =>
            {
                var chosen = all.MaxBy(arm => Mean(arm, slot, s => s != held))!;
                return Mean(chosen, slot, s => s == held) - Mean(baseline, slot, s => s == held);
            })).ToList();
            var mean = gains.Average();
            var se = Math.Sqrt(gains.Sum(g => (g - mean) * (g - mean)) / Math.Max(1, gains.Count - 1) / gains.Count);
            lines.Add($"{label}, best arm per slot chosen on the other seasons, gain over {baseline}: {mean:+0.0;-0.0;0.0} +/- {se:0.0} (SE over {gains.Count} seasons); by season "
                      + string.Join(" ", seasons.Zip(gains, (season, gain) => $"{season}: {gain:+0.0;-0.0;0.0}")));
        }
        return string.Join(Environment.NewLine, lines);
    }
