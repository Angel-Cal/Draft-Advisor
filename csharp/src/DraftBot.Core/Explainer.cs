namespace DraftBot.Core;

/// <summary>What a recommendation's reasons are about, for badges next to the text.</summary>
public enum ReasonLabel { Starter, Backup, RunningOut, Discount, Reach, InjuryHistory, EstimatedProjection }

/// <summary>
/// A recommendation in plain language: one headline sentence and a few supporting reasons. Numbers in the text are projected season points or
/// pick numbers, never units of the recommender's score.
/// </summary>
public sealed record Explanation(ValuedPlayer Player, string Headline, IReadOnlyList<string> Reasons, IReadOnlyList<ReasonLabel> Labels);

/// <summary>
/// Turns the recommender's candidates into explanations for beginners. It does not change or re-rank anything: each candidate is described by the
/// score terms the recommender gave him (lineup gain, bench value, waiting bonus, reach cost), and the headline names the term that contributes most.
/// </summary>
public static class Explainer
{
    /// <summary>Lineup gain, in projected points, below which a player is described as not starting.</summary>
    const double MinGain = 1;

    /// <summary>How far, in projected points, the best likely survivor at his position must fall short of him before waiting counts as costly.</summary>
    const double NoticeableDropOff = 10;

    /// <summary>Survival chance from which a player counts as "likely still there" at my next pick (he must also be one the recommender could take there).</summary>
    const double LikelyToLast = 0.5;

    const int MaxReasons = 4;

    /// <summary>
    /// One explanation per candidate, in the order given. <paramref name="wait"/> must be the settings the candidates were ranked with, so that the
    /// players called likely to last are the ones the waiting bonus assumed.
    /// </summary>
    public static IReadOnlyList<Explanation> Explain(DraftState state, int teamIndex, IReadOnlyList<ValueCandidate> candidates, ReachSettings reach, WaitSettings? wait = null)
    {
        var next = wait is null ? null : state.NextPick(teamIndex);
        var simulated = next is { } turn && wait?.Opponents is { } opponents ? SurvivalSampler.Survival(state, turn, opponents, wait!.Samples) : null;
        double Survival(ValuedPlayer p) => simulated?[p.Id] ?? WaitSettings.Survival(p.Player, next!.Value, reach, wait!.SpreadScale);

        return candidates.Select(c => Describe(c, state, state.Teams[teamIndex], reach, next is null ? null : p => Survival(p), next)).ToList();
    }

    static Explanation Describe(ValueCandidate c, DraftState state, Roster roster, ReachSettings reach, Func<ValuedPlayer, double>? survival, int? nextPick)
    {
        var player = c.Player;
        var reasons = new List<string>();
        var labels = new List<ReasonLabel>();
        void Add(string reason, ReasonLabel label)
        {
            reasons.Add(reason);
            labels.Add(label);
        }

        var starts = (c.Gain ?? 0) >= MinGain;
        if (c.Gain is not null) Add(starts ? StartReason(c, roster, state.League) : BackupReason(c, roster), starts ? ReasonLabel.Starter : ReasonLabel.Backup);

        var scarcity = survival is null || nextPick is null || c.WaitBonus is not > 0 ? null : ScarcityReason(c, state, reach, survival, nextPick.Value);
        if (scarcity is not null) Add(scarcity, ReasonLabel.RunningOut);

        if (player.Player.InjuryFlag) Add("He has missed time in past seasons (under 15 games a year on average), so his projection carries more risk than most.", ReasonLabel.InjuryHistory);
        if (player.Player.MarketEstimate) Add("His projection is an estimate taken from where drafters rank him (a rookie or a player the model cannot score), so it is less reliable.", ReasonLabel.EstimatedProjection);

        var pick = state.OverallPick + 1;
        if (PriceReason(c, reach, pick) is { } price) Add(price.Text, price.Label);

        return new Explanation(player, Headline(c, starts, scarcity is not null), reasons.Take(MaxReasons).ToList(), labels.Take(MaxReasons).ToList());
    }

    static string Headline(ValueCandidate c, bool starts, bool scarce)
    {
        var p = c.Player;
        var who = $"{p.Player.PlayerName} ({p.Position}, {p.Player.Team})";
        if (c.Gain is null) return $"{who}: the most projected value over a replacement-level {p.Position}.";

        // the term that adds the most to his score decides what the headline is about
        var gain = c.Gain.Value;
        var bench = c.BenchValue ?? 0;
        var wait = scarce ? c.WaitBonus ?? 0 : 0;
        if (wait > Math.Max(gain, bench)) return $"{who}: the {p.Position}s thin out before your next pick, so waiting costs you.";
        if (starts) return $"{who}: he would start for you, adding about {gain:F0} points over a replacement-level player.";
        return $"{who}: good insurance for your {p.Position} spot.";
    }

    static string StartReason(ValueCandidate c, Roster roster, LeagueSettings league)
    {
        var p = c.Player;
        var have = roster.At(p.Position);
        var starters = league.Starters(p.Position);
        var weakest = starters > 0 && have.Count >= starters ? have.OrderByDescending(h => h.Player.ProjectedPpr).ElementAt(starters - 1) : null;

        var role =
            have.Count < starters ? $"fills an open starting {p.Position} spot"
            : weakest is not null && p.Player.ProjectedPpr > weakest.Player.ProjectedPpr ? $"would start ahead of {weakest.Player.PlayerName} ({weakest.Player.ProjectedPpr:F0} projected)"
            : "would fill your FLEX spot";
        return $"He {role} and is projected for {p.Player.ProjectedPpr:F0} points, about {c.Gain:F0} more than a replacement-level {p.Position} (one you could still get in the later rounds) would add to your lineup.";
    }

    static string BackupReason(ValueCandidate c, Roster roster)
    {
        var p = c.Player;
        var best = roster.At(p.Position).OrderByDescending(h => h.Player.ProjectedPpr).FirstOrDefault();
        return best is null
            ? $"He would not start for you yet, but gives you depth at {p.Position}, a position you have not drafted."
            : $"He would not start for you; he is insurance for {best.Player.PlayerName}, covering injuries and bye weeks.";
    }

    static string? ScarcityReason(ValueCandidate c, DraftState state, ReachSettings reach, Func<ValuedPlayer, double> survival, int nextPick)
    {
        var p = c.Player;
        // the alternative is the one the recommender could actually take then: likely to last, inside the reach cap at that pick, best after the reach cost
        // (a player far past his ADP is "there" but would never be recommended, however high the model is on him)
        var likelyLeft = state.Available
            .Where(a => a.Position == p.Position && a.Id != p.Id && survival(a) >= LikelyToLast && reach.Reach(a.Player, nextPick) <= reach.CapSigmas)
            .MaxBy(a => a.Player.ProjectedPpr - reach.Lambda * Math.Pow(reach.Reach(a.Player, nextPick), 2));
        if (likelyLeft is null) return $"Almost no {p.Position}s of note will still be there at your next pick (#{nextPick}).";

        var dropOff = p.Player.ProjectedPpr - likelyLeft.Player.ProjectedPpr;
        return dropOff < NoticeableDropOff
            ? null
            : $"The {p.Position}s thin out before your next pick (#{nextPick}): the best one you could reasonably take then is {likelyLeft.Player.PlayerName}, projected {dropOff:F0} points lower.";
    }

    static (string Text, ReasonLabel Label)? PriceReason(ValueCandidate c, ReachSettings reach, int pick)
    {
        if (c.Player.Player.Adp is not { } adp) return null;
        var sigma = reach.Sigma(pick);
        if (c.ReachSigmas >= 1)
            return ($"This is an early pick for him: drafters usually take him around #{adp:F0} and you pick at #{pick}. The recommender still likes him enough to pay that price.", ReasonLabel.Reach);
        if ((pick - adp) / sigma >= 1)
            return ($"He is a bargain here: drafters usually take him around #{adp:F0} and you pick at #{pick}.", ReasonLabel.Discount);
        return null;
    }
}
