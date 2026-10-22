using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// Where one strategy's points go versus another's in a single season: which players each drafts how often, and what those
/// players scored. Both strategies draft from every slot against the same opponents.
/// </summary>
public static class PickDiagnostics
{
    static IDraftStrategy Strategy(string name) => name switch
    {
        "adp" => new AdpStrategy(),
        "vor" => new VorStrategy(),
        "recommender" => new RecommenderStrategy(),
        "windowed" => new WindowedRecommenderStrategy("windowed", ReachSettings.Default),
        _ => throw new ArgumentException($"unknown strategy '{name}' (adp, vor, recommender, windowed)"),
    };

    public static string Report(ProjectionFile file, SimSettings settings, string nameA, string nameB, int seeds)
    {
        var league = settings.League;
        var pool = Valuator.Value(file.Players, file.PositionRmse, league, new ValuationSettings(settings.TierGapRmse));
        var replacement = ReplacementLevel.Points(pool.Select(p => p.Player with { ProjectedPpr = p.Player.ActualPpr!.Value }).ToList(), league);
        var (a, b) = (Strategy(nameA), Strategy(nameB));

        var drafts = new List<(DraftResult A, DraftResult B)>();
        for (var seed = 0; seed < seeds; seed++)
            for (var slot = 0; slot < league.Teams; slot++)
                drafts.Add((DraftSimulator.Run(pool, settings, slot, a, seed), DraftSimulator.Run(pool, settings, slot, b, seed)));
        var n = drafts.Count;

        double Rate(Func<(DraftResult A, DraftResult B), DraftResult> side, ValuedPlayer p) => drafts.Count(d => side(d).MyPicks.Any(x => x.Id == p.Id)) / (double)n;
        double Over(ValuedPlayer p) => p.Player.ActualPpr!.Value - replacement[p.Position];

        var table = pool.Select(p => (Player: p, RateA: Rate(d => d.A, p), RateB: Rate(d => d.B, p))).Where(t => t.RateA > 0 || t.RateB > 0)
            .Select(t => (t.Player, t.RateA, t.RateB, Contribution: (t.RateB - t.RateA) * Over(t.Player))).ToList();

        var lines = new List<string>
        {
            $"{file.Season}: {nameB} vs {nameA}, {n} drafts each, opponent noise x1",
            $"  mean starter points: {nameA} {drafts.Average(d => d.A.Points):F0}, {nameB} {drafts.Average(d => d.B.Points):F0}   "
            + $"mean finish: {drafts.Average(d => d.A.Finish):F2} vs {drafts.Average(d => d.B.Finish):F2}",
            "",
            "players drafted per team by position (A / B):",
            "  " + string.Join("   ", Positions.All.Select(pos => $"{pos} {drafts.Average(d => d.A.MyPicks.Count(x => x.Position == pos)):F1} / {drafts.Average(d => d.B.MyPicks.Count(x => x.Position == pos)):F1}")),
            "",
            "mean actual points of the pick, by round block (A / B):",
        };
        foreach (var (name, from, to) in new[] { ("rounds 1-3", 0, 3), ("rounds 4-8", 3, 8), ("rounds 9-16", 8, 16) })
            lines.Add($"  {name,-12}{drafts.Average(d => d.A.MyPicks.Skip(from).Take(to - from).Average(x => x.Player.ActualPpr!.Value)):F0} / "
                      + $"{drafts.Average(d => d.B.MyPicks.Skip(from).Take(to - from).Average(x => x.Player.ActualPpr!.Value)):F0}");

        string Row((ValuedPlayer Player, double RateA, double RateB, double Contribution) t) =>
            $"  {t.Player.Player.PlayerName,-22}{t.Player.Position,-4}{t.Player.Player.Adp,6:F0}{t.Player.Player.ProjectedPpr,6:F0}{t.Player.Vor,6:F0}{t.Player.Player.ActualPpr,7:F0}"
            + $"{t.RateA,8:P0}{t.RateB,8:P0}{t.Contribution,9:F0}{(t.Player.Player.MarketEstimate ? "  market" : "")}{(t.Player.Player.InjuryFlag ? "  inj" : "")}";
        var header = $"  {"player",-22}{"pos",-4}{"ADP",6}{"proj",6}{"VOR",6}{"actual",7}{nameA,8}{nameB,8}{"pts diff",9}   (draft rates; pts diff = rate change x actual over replacement)";
        lines.Add("");
        lines.Add($"players that cost {nameB} the most:");
        lines.Add(header);
        lines.AddRange(table.OrderBy(t => t.Contribution).Take(14).Select(Row));
        lines.Add("");
        lines.Add($"players that helped {nameB} the most:");
        lines.Add(header);
        lines.AddRange(table.OrderByDescending(t => t.Contribution).Take(8).Select(Row));
        lines.Add("");
        lines.Add($"sum of per-player differences (rough check on the points gap): {table.Sum(t => t.Contribution):F0}");
        return string.Join(Environment.NewLine, lines);
    }
}

/// <summary>
/// Splits the recommender into its two decisions to see which one drives a result. "position-rule" lets the recommender choose the
/// position but takes the best-ADP player there; "player-rule" takes the position ADP would pick but lets the recommender choose
/// the player. Both use the same reach settings as the windowed variant.
/// </summary>
public sealed class HybridStrategy(string name, bool recommenderChoosesPosition, ReachSettings reach) : IDraftStrategy
{
    public string Name => name;

    public ValuedPlayer Pick(DraftState state, int team, IReadOnlyList<ValuedPlayer> legal)
    {
        var adpPick = new AdpStrategy().Pick(state, team, legal);
        if (recommenderChoosesPosition)
        {
            var position = BaselineRecommender.ChoosePosition(state, team, reach).Position;
            var atPosition = legal.Where(p => p.Position == position).ToList();
            return atPosition.Count > 0 ? new AdpStrategy().Pick(state, team, atPosition) : adpPick;
        }
        return BaselineRecommender.SelectPlayers(adpPick.Position, state, team, reach)
            .Select(c => c.Player).FirstOrDefault(p => legal.Contains(p)) ?? adpPick;
    }
}

public static class Decomposition
{
    public static string Report(IReadOnlyDictionary<int, ProjectionFile> files, SimSettings settings, int seeds)
    {
        var reach = ReachSettings.Default;
        IDraftStrategy[] strategies =
        [
            new AdpStrategy(), new WindowedRecommenderStrategy("windowed", reach),
            new HybridStrategy("position-rule", true, reach), new HybridStrategy("player-rule", false, reach),
        ];
        var rows = Experiment.Run(files, settings, strategies, noiseScales: [1.0], seeds).Rows;
        var seasons = files.Keys.Order().ToList();
        var lines = new List<string>
        {
            "mean starter points, opponent noise x1 (position-rule: recommender picks the position, best ADP there; player-rule: ADP's position, recommender picks the player)",
            $"  {"strategy",-14}{"mean",7}" + string.Concat(seasons.Select(s => $"{s,7}")),
        };
        foreach (var strategy in strategies)
        {
            var bySeason = seasons.Select(s => rows.Where(r => r.Strategy == strategy.Name && r.Season == s).Average(r => r.Points)).ToList();
            lines.Add($"  {strategy.Name,-14}{bySeason.Average(),7:F0}" + string.Concat(bySeason.Select(v => $"{v,7:F0}")));
        }
        return string.Join(Environment.NewLine, lines);
    }
}
