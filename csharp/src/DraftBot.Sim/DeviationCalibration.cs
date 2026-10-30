using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// How well calibrated is the model where the advisor actually acts? Averaged over all draftable players the model's gap to the ADP curve predicts only about 0.3 of the gap that shows up
/// in outcomes, yet shrinking the gap lowers the advisor's edge. The advisor does not act on the average gap: it acts where the player is also inside the reach window. This asks the
/// question on those decisions. At each state of the adopted advisor's drafts, whenever its pick differs from the ADP pick, record how much more the model values the advisor's pick (value over
/// replacement) and how much more it actually scored over replacement, and regress the second on the first with the ADP difference as a control. A slope near 1 means the model is calibrated
/// where it is used (selection explains the contradiction); a slope near 0.3 means the edge comes from somewhere other than the projection gap. The same is computed for a control pair that
/// involves no choice by the advisor: the ADP pick against the next player by ADP.
/// </summary>
public static class DeviationCalibration
{
    sealed record Obs(int Season, int Seed, int Round, bool SamePosition, double DProj, double DAdp, double DActual, Position Taken = default, Position Passed = default);

    const int Bootstraps = 300;
    const int MinN = 40;

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0, int firstSeed = 0)
    {
        var adopted = new ValueRecommenderStrategy("adopted", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait);
        var adp = new AdpStrategy();
        var scaled = settings with { NoiseScale = noiseScale };
        var pools = files.ToDictionary(f => f.Key, f => Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));
        var replacement = pools.ToDictionary(p => p.Key, p => ReplacementLevel.Points(p.Value.Select(x => x.Player with { ProjectedPpr = x.Player.ActualPpr!.Value }).ToList(), settings.League));

        var jobs = (from season in files.Keys.Order() from seed in Enumerable.Range(firstSeed, seeds) from slot in Enumerable.Range(0, settings.League.Teams) select (season, seed, slot)).ToList();
        var deviations = new List<Obs>[jobs.Count];
        var controls = new List<Obs>[jobs.Count];
        Parallel.For(0, jobs.Count, i =>
        {
            var (season, seed, slot) = jobs[i];
            var pool = pools[season];
            var over = (ValuedPlayer p) => p.Player.ActualPpr!.Value - replacement[season][p.Position];
            var bots = Enumerable.Range(0, settings.League.Teams).Select(t => t == slot ? null : OpponentBot.Create(pool, scaled, seed, t)).ToArray();
            var state = new DraftState(pool, settings.League);
            var deviating = new List<Obs>();
            var control = new List<Obs>();
            while (!state.IsComplete)
            {
                var team = state.CurrentTeam;
                var legal = team == slot && !scaled.StrategyFollowsRules ? state.Available : DraftRules.LegalPicks(state, team, scaled);
                var pick = bots[team]?.Pick(legal);
                if (pick is null)
                {
                    pick = adopted.Pick(state, team, legal);
                    var unranked = OpponentBot.UnrankedAdp(state.Available);
                    var adpKey = (ValuedPlayer p) => p.Player.Adp ?? unranked;
                    var adpPick = adp.Pick(state, team, legal);
                    Obs Make(ValuedPlayer a, ValuedPlayer b) => new(season, seed, state.Round, a.Position == b.Position, a.Vor - b.Vor, adpKey(a) - adpKey(b), over(a) - over(b), a.Position, b.Position);
                    if (pick.Id != adpPick.Id) deviating.Add(Make(pick, adpPick));
                    var runnerUp = legal.Where(p => p.Id != adpPick.Id).MinBy(adpKey);
                    if (runnerUp is not null) control.Add(Make(runnerUp, adpPick));
                }
                state.Draft(pick.Id);
            }
            deviations[i] = deviating;
            controls[i] = control;
        });

        var dev = deviations.SelectMany(d => d).ToList();
        var ctl = controls.SelectMany(d => d).ToList();
        var lines = new List<string>
        {
            $"{jobs.Count} drafts, opponent noise x{noiseScale:0.##}; {dev.Count} decisions where the adopted advisor's pick differs from the ADP pick, {ctl.Count} control pairs (ADP pick against the next by ADP).",
            "For each group: d proj = model value over replacement of the first player minus the second, d adp = ADP of the first minus the second (picks), d actual = actual points over replacement, first minus second.",
            "slope = coefficient of d proj in the regression of d actual on d proj and d adp (+/- 1 SE, bootstrap over (season, seed)); 1 = calibrated, 0 = no information.",
            "",
            $"{"group",-34}{"n",7}{"d proj",9}{"d adp",8}{"d actual",10}{"slope",16}",
        };
        foreach (var (label, source) in new[] { ("advisor vs ADP pick", dev), ("control: next by ADP", ctl) })
            foreach (var (kind, same) in new (string, Func<Obs, bool>)[] { ("all", _ => true), ("same position", o => o.SamePosition), ("other position", o => !o.SamePosition) })
                foreach (var (rounds, inRounds) in new (string, Func<Obs, bool>)[] { ("all rounds", _ => true), ("rounds 1-2", o => o.Round <= 2), ("rounds 3-6", o => o.Round is >= 3 and <= 6), ("rounds 7+", o => o.Round >= 7) })
                {
                    var rows = source.Where(o => same(o) && inRounds(o)).ToList();
                    lines.Add(Line($"{label}, {kind}, {rounds}", rows));
                }

        var seasons = files.Keys.Order().ToList();
        lines.Add("");
        lines.Add("Rounds 3-6, advisor takes one position over the ADP pick's position: d actual per decision (points over replacement), n, and its mean in each season (blank under 15 decisions)");
        lines.Add($"{"takes over ADP pick",-22}{"n",7}{"d proj",8}{"d actual",10}{"points/draft",14}   " + string.Join(" ", seasons.Select(s => $"{s,6}")));
        foreach (var group in dev.Where(o => !o.SamePosition && o.Round is >= 3 and <= 6).GroupBy(o => (o.Taken, o.Passed)).Where(g => g.Count() >= 100).OrderByDescending(g => g.Sum(o => o.DActual)))
        {
            var perSeason = seasons.Select(season => group.Where(o => o.Season == season).ToList()).Select(rows => rows.Count >= 15 ? $"{rows.Average(o => o.DActual),6:F1}" : $"{"",6}");
            lines.Add($"{group.Key.Taken + " over " + group.Key.Passed,-22}{group.Count(),7}{group.Average(o => o.DProj),8:F1}{group.Average(o => o.DActual),10:F1}{group.Sum(o => o.DActual) / jobs.Count,14:F1}   " + string.Join(" ", perSeason));
        }
        return string.Join(Environment.NewLine, lines);
    }

    static string Line(string label, IReadOnlyList<Obs> rows)
    {
        if (rows.Count < MinN) return $"{label,-34}{rows.Count,7}";
        var slope = Slope(rows);
        var clusters = rows.GroupBy(o => (o.Season, o.Seed)).Select(g => g.ToList()).ToList();
        var random = new Random(1);
        var draws = new List<double>();
        for (var b = 0; b < Bootstraps; b++)
        {
            var resampled = Enumerable.Range(0, clusters.Count).SelectMany(_ => clusters[random.Next(clusters.Count)]).ToList();
            var s = Slope(resampled);
            if (!double.IsNaN(s)) draws.Add(s);
        }
        var mean = draws.Average();
        var se = Math.Sqrt(draws.Sum(d => (d - mean) * (d - mean)) / Math.Max(1, draws.Count - 1));
        return $"{label,-34}{rows.Count,7}{rows.Average(o => o.DProj),9:F1}{rows.Average(o => o.DAdp),8:F1}{rows.Average(o => o.DActual),10:F1}{slope,9:F2} +/- {se:F2}";
    }

    /// <summary>Least-squares coefficient of DProj in DActual ~ 1 + DProj + DAdp; NaN if the system is singular.</summary>
    static double Slope(IReadOnlyList<Obs> rows)
    {
        var a = new double[3, 4];
        foreach (var o in rows)
        {
            double[] x = [1, o.DProj, o.DAdp];
            for (var r = 0; r < 3; r++)
            {
                for (var c = 0; c < 3; c++) a[r, c] += x[r] * x[c];
                a[r, 3] += x[r] * o.DActual;
            }
        }
        for (var col = 0; col < 3; col++)
        {
            var pivot = Enumerable.Range(col, 3 - col).MaxBy(r => Math.Abs(a[r, col]));
            if (Math.Abs(a[pivot, col]) < 1e-9) return double.NaN;
            for (var c = 0; c < 4; c++) (a[col, c], a[pivot, c]) = (a[pivot, c], a[col, c]);
            for (var r = 0; r < 3; r++)
            {
                if (r == col) continue;
                var factor = a[r, col] / a[col, col];
                for (var c = col; c < 4; c++) a[r, c] -= factor * a[col, c];
            }
        }
        return a[1, 3] / a[1, 1];
    }
}
