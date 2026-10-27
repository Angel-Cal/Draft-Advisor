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

    OpponentBot(Dictionary<string, double> key) => this.key = key;

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
        return new OpponentBot(key);
    }

    public ValuedPlayer Pick(IReadOnlyList<ValuedPlayer> legal) =>
        legal.MinBy(p => key[p.Id]) ?? throw new InvalidOperationException("no legal pick");

    public static double UnrankedAdp(IReadOnlyList<ValuedPlayer> pool) => pool.Max(p => p.Player.Adp ?? 0) + 1;

    static double Gaussian(Random random)
    {
        var u1 = 1.0 - random.NextDouble();      // (0, 1]
        var u2 = random.NextDouble();
        return Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2);
    }
}
