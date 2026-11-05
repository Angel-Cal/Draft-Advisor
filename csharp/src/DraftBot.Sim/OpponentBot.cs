using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// An opponent who drafts by ADP plus a personal, fixed bias per player (some teams simply like a player more than the
/// consensus does). Biases depend only on the seed and the team, never on what happened in the draft, so the same
/// opponents face every strategy being compared.
/// </summary>
public sealed class OpponentBot
{
    readonly Dictionary<string, double> key;
    readonly OpponentStyle? style;
    readonly int team;

    OpponentBot(Dictionary<string, double> key, OpponentStyle? style, int team)
    {
        this.key = key;
        this.style = style is { IsDefault: false } ? style : null;
        this.team = team;
    }

    /// <summary>Pick key per player: ADP (unranked players count as one past the last ADP) plus this team's bias.</summary>
    public static OpponentBot Create(IReadOnlyList<ValuedPlayer> pool, SimSettings settings, int seed, int team)
    {
        var random = new Random(seed * 1000 + team);
        var unranked = UnrankedAdp(pool);
        var key = new Dictionary<string, double>(pool.Count);
        foreach (var player in pool.OrderBy(p => p.Id, StringComparer.Ordinal))       // by id, not pool order: pool order follows the projections, which would reassign the draws between players when they change
        {
            var adp = player.Player.Adp ?? unranked;
            key[player.Id] = adp + settings.NoiseSd(adp) * Gaussian(random);
        }
        return new OpponentBot(key, settings.Style, team);
    }

    /// <summary>
    /// The legal player with the lowest key. With a non-default <see cref="OpponentStyle"/> the key also moves earlier for the style's position shift, and, when the draft
    /// <paramref name="state"/> is given, for a run on his position among the latest picks and for an open starter slot of this team at his position.
    /// </summary>
    public ValuedPlayer Pick(IReadOnlyList<ValuedPlayer> legal, DraftState? state = null)
    {
        if (style is null) return legal.MinBy(p => key[p.Id]) ?? throw new InvalidOperationException("no legal pick");
        var recent = state is null || style.RunPull == 0
            ? new Dictionary<Position, int>()
            : state.History.TakeLast(style.RunWindow).GroupBy(h => h.Player.Position).ToDictionary(g => g.Key, g => g.Count());
        double Key(ValuedPlayer p)
        {
            var k = key[p.Id] - style.Earlier(p.Position) - style.RunPull * recent.GetValueOrDefault(p.Position);
            if (state is not null && style.NeedPull != 0 && state.Teams[team].At(p.Position).Count < state.League.Starters(p.Position)) k -= style.NeedPull;
            return k;
        }
        return legal.MinBy(Key) ?? throw new InvalidOperationException("no legal pick");
    }

    public static double UnrankedAdp(IReadOnlyList<ValuedPlayer> pool) => pool.Max(p => p.Player.Adp ?? 0) + 1;

    static double Gaussian(Random random)
    {
        var u1 = 1.0 - random.NextDouble();      // (0, 1]
        var u2 = random.NextDouble();
        return Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2);
    }
}
