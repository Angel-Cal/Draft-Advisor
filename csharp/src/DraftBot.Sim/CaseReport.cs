using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// One concrete draft state, for replaying a screen: the named players are drafted in order from pick 1, then the adopted advisor and two reach-cost references rank the pool
/// for one team, followed by the advice the app would show. The variant study that used to live here (`trace-reach`, `stability-reach`) is archived.
/// </summary>
public static class CaseReport
{
    /// <summary>The adopted advisor, the same without the free first pick ("old wall"), and without any reach cost (the 4-sigma cap stays).</summary>
    public static List<ValueRecommenderStrategy> Variants() =>
    [
        new("adopted", ValueRecommender.DefaultReach, NeedSettings.Default, ValueRecommender.DefaultWait),
        new("old wall", ValueRecommender.DefaultReach with { FreePicks = 0 }, NeedSettings.Default, ValueRecommender.DefaultWait),
        new("no reach cost", ValueRecommender.DefaultReach with { Lambda = 0 }, NeedSettings.Default, ValueRecommender.DefaultWait),
    ];

    /// <summary>
    /// The state after <paramref name="drafted"/>, ranked by each variant for team <paramref name="teamIndex"/> (0-based): score, reach cost and waiting bonus of the top
    /// <paramref name="top"/> candidates, then the adopted advice (cards, tags, position tiles).
    /// </summary>
    public static string Report(ProjectionFile file, SimSettings settings, IReadOnlyList<string> drafted, int teamIndex, int top = 6)
    {
        var pool = settings.Pool(file);
        var state = new DraftState(pool, settings.League);
        foreach (var name in drafted) state.Draft(state.Available.Where(p => p.Player.PlayerName == name).OrderBy(p => p.Player.Adp ?? 1e9).First().Id);     // undrafted only: two players can share a name (J.Williams)
        var lines = new List<string> { $"pick {state.OverallPick + 1} for team {teamIndex + 1}, after {string.Join(", ", drafted)}" };
        foreach (var variant in Variants())
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
