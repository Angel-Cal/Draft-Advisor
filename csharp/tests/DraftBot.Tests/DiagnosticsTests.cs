using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class DiagnosticsTests
{
    static readonly LeagueSettings League = new();
    static readonly SimSettings Settings = new(League);

    static (DraftState State, IReadOnlyList<ValuedPlayer> Legal) Fresh()
    {
        var file = BacktestFile();
        var state = new DraftState(Valuator.Value(file.Players, file.PositionRmse, League), League);
        return (state, DraftRules.LegalPicks(state, 0, Settings));
    }

    [Fact]
    public void The_position_rule_hybrid_takes_the_best_adp_at_the_recommenders_position()
    {
        var (state, legal) = Fresh();
        var position = BaselineRecommender.ChoosePosition(state, 0, ReachSettings.Default).Position;

        var pick = new HybridStrategy("h", recommenderChoosesPosition: true, ReachSettings.Default).Pick(state, 0, legal);

        Assert.Equal(position, pick.Position);
        Assert.Equal(legal.Where(p => p.Position == position).Min(p => p.Player.Adp), pick.Player.Adp);
    }

    [Fact]
    public void The_player_rule_hybrid_stays_at_the_position_adp_would_pick()
    {
        var (state, legal) = Fresh();
        var adpPosition = new AdpStrategy().Pick(state, 0, legal).Position;

        var pick = new HybridStrategy("h", recommenderChoosesPosition: false, ReachSettings.Default).Pick(state, 0, legal);

        Assert.Equal(adpPosition, pick.Position);
    }

    [Fact]
    public void The_pick_diagnostic_reports_position_mix_round_blocks_and_player_differences()
    {
        var text = PickDiagnostics.Report(BacktestFile(), Settings, "adp", "windowed", seeds: 1);

        Assert.Contains("players drafted per team by position", text);
        Assert.Contains("rounds 1-3", text);
        Assert.Contains("players that cost windowed the most", text);
        Assert.Contains("sum of per-player differences", text);
    }

    [Fact]
    public void The_pick_diagnostic_rejects_an_unknown_strategy()
    {
        Assert.Throws<ArgumentException>(() => PickDiagnostics.Report(BacktestFile(), Settings, "adp", "nonsense", seeds: 1));
    }

    [Fact]
    public void The_decomposition_compares_the_hybrids_with_adp_and_the_windowed_variant_per_season()
    {
        var files = new Dictionary<int, ProjectionFile> { [2023] = BacktestFile(2023), [2024] = BacktestFile(2024) };

        var text = Decomposition.Report(files, Settings, seeds: 1);

        foreach (var name in new[] { "adp", "windowed", "position-rule", "player-rule", "2023", "2024" }) Assert.Contains(name, text);
    }
}
