using DraftBot.Core;

namespace DraftBot.Tests;

static class TestData
{
    public static readonly Dictionary<Position, double> Rmse = new()
    {
        [Position.QB] = 100, [Position.RB] = 100, [Position.WR] = 100, [Position.TE] = 100,
    };

    public static Player Player(string id, Position position, double projected, double? adp = null, int games = 16,
        int gamesDelta = 0, bool injury = false, bool market = false, double? actual = null) =>
        new(id, id, position, "KC", projected, games, gamesDelta, adp, injury, market, actual);

    /// <summary>A pre-valued player, for tests that need exact VOR rank / gap / tier without running the valuation.</summary>
    public static ValuedPlayer Valued(string id, Position position, double vor = 0, double vorRank = 1, double valueGap = 0,
        int tier = 1, bool injury = false) =>
        new(Player(id, position, 100 + vor, injury: injury), vor, 150, 50, false, vorRank, valueGap, tier);

    /// <summary>
    /// Pool shaped like a real one: positions get projections stepping down from a top value, ADP follows projection
    /// across positions, so the rank order is realistic without depending on the real files.
    /// </summary>
    public static List<Player> RealisticPool(int qb = 24, int rb = 70, int wr = 90, int te = 30)
    {
        var rows = new List<(Position, double)>();
        rows.AddRange(Enumerable.Range(0, qb).Select(i => (Position.QB, 380.0 - 9 * i)));
        rows.AddRange(Enumerable.Range(0, rb).Select(i => (Position.RB, 330.0 - 4.2 * i)));
        rows.AddRange(Enumerable.Range(0, wr).Select(i => (Position.WR, 320.0 - 3.2 * i)));
        rows.AddRange(Enumerable.Range(0, te).Select(i => (Position.TE, 250.0 - 7 * i)));
        return rows.OrderByDescending(r => r.Item2)
            .Select((r, i) => Player($"{r.Item1}{i}", r.Item1, r.Item2, adp: i + 1))
            .ToList();
    }

    /// <summary>A backtest-style file over <see cref="RealisticPool"/> with deterministic, varied actual points.</summary>
    public static ProjectionFile BacktestFile(int season = 2024)
    {
        var players = RealisticPool().Select((p, i) => p with { ActualPpr = p.ProjectedPpr * (0.6 + 0.8 * ((i * 37) % 11) / 10.0) }).ToList();
        return new ProjectionFile("v1", "backtest", season, "fantasypros", Rmse, players);
    }

    public static string ProjectionJson(string schema = "v1", string rmse = """{"QB":84.28,"RB":58.86,"WR":53.48,"TE":38.69}""") => $$"""
        {
          "schema_version": "{{schema}}", "kind": "backtest", "season": 2024, "adp_source": "fantasypros",
          "position_rmse": {{rmse}}, "generated_utc": "2026-10-21T00:00:00+00:00", "git_commit": "abc1234",
          "players": [
            {"player_id": "00-1", "player_name": "A", "position": "RB", "team": "SF", "projected_ppr": 229.12,
             "projected_half": null, "projected_standard": null, "games": 16, "games_delta": -1, "adp": 1.0,
             "injury_flag": false, "market_estimate": false, "actual_ppr": 47.8},
            {"player_id": "market:b", "player_name": "B", "position": "WR", "team": "FA", "projected_ppr": 100.5,
             "projected_half": null, "projected_standard": null, "games": 17, "games_delta": 0, "adp": null,
             "injury_flag": true, "market_estimate": true, "actual_ppr": null}
          ]
        }
        """;
}
