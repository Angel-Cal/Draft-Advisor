using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Shared-state comparison of reach-cost variants: the adopted advisor drafts, and at each of its turns every variant is asked what it would pick in that same
/// state (so the drafts do not drift apart). A disagreement is scored by what the two picks turned out to be worth, actual points over the position's
/// replacement, and by where the reach cost alone decided the pick between players whose ADP differs by less than half a standard deviation.
/// </summary>
public static class ReachTrace
{
    public const double KnifeEdgeSigmas = 0.5;

    sealed record Decision(int Season, int Round, int Pick, string Variant, bool Differs, double HindsightGain, double AdpGapSigmas, int AdoptedRound, string AdoptedName, string OtherName);

    /// <summary>The adopted advisor against the variants; `adp` is plain ADP and `no reach cost` is the advisor with lambda 0 (the 4-sigma cap stays).</summary>
    public static List<ValueRecommenderStrategy> Variants() =>
    [
        new("no reach cost", new ReachSettings(0, 4), NeedSettings.Default, ValueRecommender.DefaultWait),
        new("free 0.5", new ReachSettings(1000, 4, FreeSigmas: 0.5), NeedSettings.Default, ValueRecommender.DefaultWait),
        new("free 1.0", new ReachSettings(1000, 4, FreeSigmas: 1.0), NeedSettings.Default, ValueRecommender.DefaultWait),
        new("old wall", new ReachSettings(1000, 4), NeedSettings.Default, ValueRecommender.DefaultWait),
        new("free 2 picks", new ReachSettings(1000, 4, FreePicks: 2), NeedSettings.Default, ValueRecommender.DefaultWait),
        new("S (survival-scaled)", new ReachSettings(1000, 4, SurvivalPower: 1), NeedSettings.Default, ValueRecommender.DefaultWait),
    ];

    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double noiseScale = 1.0, int firstSeed = 0)
    {
        var adopted = new ValueRecommenderStrategy("adopted", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait);
        var variants = Variants().Cast<IDraftStrategy>().Append(new AdpStrategy()).ToList();
        var scaled = settings with { NoiseScale = noiseScale };
        var pools = files.ToDictionary(f => f.Key, f => Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));
        var replacement = pools.ToDictionary(p => p.Key, p => ReplacementLevel.Points(p.Value.Select(x => x.Player with { ProjectedPpr = x.Player.ActualPpr!.Value }).ToList(), settings.League));
        var reach = ValueRecommender.DefaultReach;

        var jobs = (from season in files.Keys.Order() from seed in Enumerable.Range(firstSeed, seeds) from slot in Enumerable.Range(0, settings.League.Teams) select (season, seed, slot)).ToList();
        var results = new List<Decision>[jobs.Count];
        Parallel.For(0, jobs.Count, i =>
        {
            var (season, seed, slot) = jobs[i];
            var pool = pools[season];
            var over = (ValuedPlayer p) => p.Player.ActualPpr!.Value - replacement[season][p.Position];
            var bots = Enumerable.Range(0, settings.League.Teams).Select(t => t == slot ? null : OpponentBot.Create(pool, scaled, seed, t)).ToArray();
            var state = new DraftState(pool, settings.League);
            var decisions = new List<Decision>();
            while (!state.IsComplete)
            {
                var team = state.CurrentTeam;
                var legal = team == slot && !scaled.StrategyFollowsRules ? state.Available : DraftRules.LegalPicks(state, team, scaled);
                var pick = bots[team]?.Pick(legal);
                if (pick is null)
                {
                    pick = adopted.Pick(state, team, legal);
                    var sigma = reach.Sigma(state.OverallPick + 1);
                    foreach (var variant in variants)
                    {
                        var other = variant.Pick(state, team, legal);
                        var gap = other.Player.Adp is { } a && pick.Player.Adp is { } b ? Math.Abs(a - b) / sigma : double.NaN;
                        decisions.Add(new Decision(season, state.Round, state.OverallPick + 1, variant.Name, other.Id != pick.Id, over(other) - over(pick), gap, state.Round, pick.Player.PlayerName, other.Player.PlayerName));
                    }
                }
                state.Draft(pick.Id);
            }
            results[i] = decisions;
        });

        var all = results.SelectMany(r => r).ToList();
        var seasons = files.Keys.Order().ToList();
        var lines = new List<string>
        {
            $"{jobs.Count} drafts, {all.Count(d => d.Variant == "adp")} advisor decisions, opponent noise x{noiseScale:0.##}; each variant is asked in the adopted advisor's own states.",
            "hindsight = the variant's pick minus the adopted pick, in actual points over replacement at the position (a first-order score: roster fit ignored); +/- is a naive SE over disagreements.",
        };
        foreach (var (label, filter) in new (string, Func<Decision, bool>)[] { ("rounds 1-2", d => d.Round <= 2), ("rounds 3-6", d => d.Round is >= 3 and <= 6), ("rounds 7+", d => d.Round >= 7), ("all rounds", _ => true) })
        {
            lines.Add("");
            lines.Add(label);
            lines.Add($"  {"variant",-22}{"decisions",10}{"differs",9}{"hindsight/disagreement",26}" + string.Concat(seasons.Select(s => $"{s,16}")));
            foreach (var name in variants.Select(v => v.Name))
            {
                var rows = all.Where(d => d.Variant == name && filter(d)).ToList();
                var diff = rows.Where(d => d.Differs).ToList();
                string Cell(IReadOnlyList<Decision> r) => r.Count == 0 ? "-" : $"{r.Average(d => d.HindsightGain):+0.0;-0.0}/{r.Count}";
                lines.Add($"  {name,-22}{rows.Count,10}{(rows.Count == 0 ? 0 : diff.Count / (double)rows.Count),9:P1}{(diff.Count == 0 ? "-" : $"{diff.Average(d => d.HindsightGain):+0.0;-0.0} +/-{Se(diff):0.0}"),26}"
                          + string.Concat(seasons.Select(s => $"{Cell(diff.Where(d => d.Season == s).ToList()),16}")));
            }
        }

        var none = all.Where(d => d.Variant == "no reach cost" && d.Differs).ToList();
        var edge = none.Where(d => d.AdpGapSigmas < KnifeEdgeSigmas).ToList();
        lines.Add("");
        lines.Add($"Where the reach cost decided the pick (adopted pick differs from the no-reach-cost pick): {none.Count} of {all.Count(d => d.Variant == "no reach cost")} decisions ({none.Count / (double)all.Count(d => d.Variant == "no reach cost"):P1}).");
        lines.Add($"  of those, the two players are within {KnifeEdgeSigmas} sigma of each other in ADP ('knife-edge'): {edge.Count} ({(none.Count == 0 ? 0 : edge.Count / (double)none.Count):P0}); hindsight of the no-reach pick over the adopted pick: knife-edge {Mean(edge):+0.0;-0.0}, wider gaps {Mean(none.Where(d => d.AdpGapSigmas >= KnifeEdgeSigmas).ToList()):+0.0;-0.0}.");
        foreach (var (label, filter) in new (string, Func<Decision, bool>)[] { ("rounds 1-2", d => d.Round <= 2), ("rounds 3-6", d => d.Round is >= 3 and <= 6), ("rounds 7+", d => d.Round >= 7) })
        {
            var inRound = all.Where(d => d.Variant == "no reach cost" && filter(d)).ToList();
            var flips = inRound.Where(d => d.Differs).ToList();
            lines.Add($"  {label}: reach cost decided {flips.Count / (double)inRound.Count:P1} of picks, {flips.Count(d => d.AdpGapSigmas < KnifeEdgeSigmas) / (double)inRound.Count:P1} at knife-edge ADP gaps");
        }
        lines.Add("");
        lines.Add("Knife-edge flips (no-reach-cost pick vs adopted pick, ADP within 0.5 sigma): hindsight of the no-reach pick, mean +/- naive SE (n)");
        foreach (var (label, filter) in new (string, Func<Decision, bool>)[] { ("rounds 1-2", d => d.Round <= 2), ("rounds 3-6", d => d.Round is >= 3 and <= 6), ("rounds 7+", d => d.Round >= 7) })
        {
            var sub = edge.Where(filter).ToList();
            lines.Add($"  {label}: {Mean(sub):+0.0;-0.0} +/-{Se(sub):0.0} ({sub.Count})   by season " + string.Join("  ", seasons.Select(s => $"{s}: {Mean(sub.Where(d => d.Season == s).ToList()):+0;-0}")));
        }
        foreach (var (variant, season, rounds) in seasons.Select(y => ("S (survival-scaled)", y, 2)))
        {
            lines.Add("");
            lines.Add($"Biggest contributors, {variant}, {season}, rounds 1-{rounds}: variant's pick (adopted pick instead), summed hindsight / count");
            foreach (var g in all.Where(d => d.Variant == variant && d.Season == season && d.Round <= rounds && d.Differs).GroupBy(d => d.OtherName)
                         .Select(g => (Name: g.Key, Sum: g.Sum(d => d.HindsightGain), Count: g.Count(), Instead: g.GroupBy(d => d.AdoptedName).MaxBy(x => x.Count())!.Key))
                         .OrderBy(t => t.Sum).Take(4).Concat(all.Where(d => d.Variant == variant && d.Season == season && d.Round <= rounds && d.Differs).GroupBy(d => d.OtherName)
                         .Select(g => (Name: g.Key, Sum: g.Sum(d => d.HindsightGain), Count: g.Count(), Instead: g.GroupBy(d => d.AdoptedName).MaxBy(x => x.Count())!.Key))
                         .OrderByDescending(t => t.Sum).Take(3)))
                lines.Add($"  {g.Name,-22} (instead of {g.Instead,-20}) {g.Sum,10:+0;-0} / {g.Count}");
        }
        return string.Join(Environment.NewLine, lines);

        static double Mean(IReadOnlyList<Decision> r) => r.Count == 0 ? double.NaN : r.Average(d => d.HindsightGain);
        static double Se(IReadOnlyList<Decision> r)
        {
            if (r.Count < 2) return double.NaN;
            var m = r.Average(d => d.HindsightGain);
            return Math.Sqrt(r.Sum(d => (d.HindsightGain - m) * (d.HindsightGain - m)) / (r.Count - 1) / r.Count);
        }
    }

    /// <summary>
    /// How much each variant's pick depends on the exact ADP numbers: the same draft is replayed in a twin state whose ADPs are all moved by a fixed random offset (SD
    /// <paramref name="jitterPicks"/>, drawn once per draft), and the share of the advisor's decisions whose pick changes is reported by round. A consensus ADP cannot claim a resolution
    /// much finer than about a pick, so a decision that flips under half a pick of jitter is decided by noise.
    /// </summary>
    public static string StabilityReport(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds, double jitterPicks = 0.5, double noiseScale = 1.0, int firstSeed = 0)
    {
        var adopted = new ValueRecommenderStrategy("adopted", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait);
        var strategies = Variants().Prepend(adopted).ToList();
        var scaled = settings with { NoiseScale = noiseScale };
        var pools = files.ToDictionary(f => f.Key, f => Valuator.Value(f.Value.Players, f.Value.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse)));
        var jobs = (from season in files.Keys.Order() from seed in Enumerable.Range(firstSeed, seeds) from slot in Enumerable.Range(0, settings.League.Teams) select (season, seed, slot)).ToList();
        var changes = new List<(int Round, string Variant, bool Changed)>[jobs.Count];
        Parallel.For(0, jobs.Count, i =>
        {
            var (season, seed, slot) = jobs[i];
            var rng = new Random(seed * 7919 + slot * 31 + season);
            double Normal() => Math.Sqrt(-2 * Math.Log(1 - rng.NextDouble())) * Math.Cos(2 * Math.PI * rng.NextDouble());
            var twinPool = pools[season].Select(p => p.Player.Adp is { } adp ? p with { Player = p.Player with { Adp = Math.Max(0.5, adp + jitterPicks * Normal()) } } : p).ToList();
            var bots = Enumerable.Range(0, settings.League.Teams).Select(t => t == slot ? null : OpponentBot.Create(pools[season], scaled, seed, t)).ToArray();
            var state = new DraftState(pools[season], settings.League);
            var twin = new DraftState(twinPool, settings.League);
            var list = new List<(int, string, bool)>();
            while (!state.IsComplete)
            {
                var team = state.CurrentTeam;
                var legal = team == slot && !scaled.StrategyFollowsRules ? state.Available : DraftRules.LegalPicks(state, team, scaled);
                var pick = bots[team]?.Pick(legal);
                if (pick is null)
                {
                    var twinLegal = team == slot && !scaled.StrategyFollowsRules ? twin.Available : DraftRules.LegalPicks(twin, team, scaled);
                    foreach (var strategy in strategies)
                        list.Add((state.Round, strategy.Name, strategy.Pick(state, team, legal).Id != strategy.Pick(twin, team, twinLegal).Id));
                    pick = strategies[0].Pick(state, team, legal);
                }
                state.Draft(pick.Id);
                twin.Draft(pick.Id);
            }
            changes[i] = list;
        });
        var all = changes.SelectMany(c => c).ToList();
        var lines = new List<string>
        {
            $"{jobs.Count} drafts; every ADP moved by a per-draft random offset, SD {jitterPicks:0.##} picks; share of the advisor's decisions whose pick changes",
            $"  {"variant",-22}{"rounds 1-2",12}{"rounds 3-6",12}{"rounds 7+",12}{"all",10}",
        };
        foreach (var strategy in strategies)
        {
            string Share(Func<int, bool> rounds)
            {
                var rows = all.Where(c => c.Variant == strategy.Name && rounds(c.Round)).ToList();
                return rows.Count == 0 ? "-" : $"{rows.Count(c => c.Changed) / (double)rows.Count:P1}";
            }
            lines.Add($"  {strategy.Name,-22}{Share(r => r <= 2),12}{Share(r => r is >= 3 and <= 6),12}{Share(r => r >= 7),12}{Share(_ => true),10}");
        }
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>
    /// One concrete state: the named players are drafted in order from pick 1, and each variant ranks the pool for team <paramref name="teamIndex"/> (0-based).
    /// Shows the score, the reach cost and what the waiting bonus adds for the top <paramref name="top"/> candidates.
    /// </summary>
    public static string CaseReport(ProjectionFile file, SimSettings settings, IReadOnlyList<string> drafted, int teamIndex, int top = 6)
    {
        var pool = Valuator.Value(file.Players, file.PositionRmse, settings.League, new ValuationSettings(settings.TierGapRmse));
        var state = new DraftState(pool, settings.League);
        foreach (var name in drafted) state.Draft(pool.Where(p => p.Player.PlayerName == name).OrderBy(p => p.Player.Adp ?? 1e9).First().Id);
        var lines = new List<string> { $"pick {state.OverallPick + 1} for team {teamIndex + 1}, after {string.Join(", ", drafted)}" };
        foreach (var variant in Variants().Prepend(new ValueRecommenderStrategy("adopted", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait))
                     .Append(new("S + free 1 pick", new ReachSettings(1000, 4, SurvivalPower: 1, FreePicks: 1), NeedSettings.Default, ValueRecommender.DefaultWait)))
        {
            var ranked = ValueRecommender.Rank(state, variant.Reach, variant.Need, teamIndex, variant.Wait);
            lines.Add("");
            lines.Add($"{variant.Name}:   {"player",-20}{"pos",4}{"ADP",6}{"proj",6}{"score",8}{"reach cost",12}{"z",6}{"wait bonus",12}");
            foreach (var c in ranked.Take(top))
                lines.Add($"    {c.Player.Player.PlayerName,-23}{c.Player.Position,-4}{c.Player.Player.Adp,6:F1}{c.Player.Player.ProjectedPpr,6:F0}{c.Score,8:F0}{c.ReachPenalty,12:F0}{c.ReachSigmas,6:F2}{c.WaitBonus,12:F0}");
        }
        var advice = DraftAdvisor.Advise(state, teamIndex);
        lines.Add("");
        lines.Add($"advice (the adopted default): close call with a {(advice.Rival?.ToString() ?? "none")}");
        foreach (var r in advice.Recommended)
            lines.Add($"    {r.Rank}. {r.Candidate.Player.Player.PlayerName,-20}{r.Candidate.Player.Position,-4} score {r.Candidate.Score,5:F0}  first in {r.TopShare:P0} of nudged re-rankings   {string.Join(", ", r.Tags.Select(t => t.Name))}");
        foreach (var tile in advice.Positions)
            lines.Add($"    {tile.Position}: top {tile.Top.Player.Player.PlayerName}, waiting costs {tile.CostOfWaiting:F1}, take now {tile.TakeNow}, recommended {tile.IsRecommended}, reach {tile.TopIsReach}");
        return string.Join(Environment.NewLine, lines);
    }
}
