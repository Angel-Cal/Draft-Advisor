namespace DraftBot.Sim;

/// <summary>
/// Season shape: a regular season of head-to-head weeks, then a single-elimination playoff the next weeks. The best seeds skip the first
/// round when the field is not a power of two (6 teams: seeds 1 and 2 get byes).
/// </summary>
/// <param name="RegularSeasonWeeks">Weeks 1..N are the regular season.</param>
/// <param name="PlayoffTeams">Top teams by wins (then points for) that make the playoffs.</param>
public sealed record SeasonFormat(int RegularSeasonWeeks = 13, int PlayoffTeams = 6)
{
    int Bracket => (int)Math.Pow(2, Math.Ceiling(Math.Log2(PlayoffTeams)));

    /// <summary>Seeds that skip round one.</summary>
    public int Byes => Bracket - PlayoffTeams;

    public int PlayoffRounds => (int)Math.Log2(Bracket);

    public int Weeks => RegularSeasonWeeks + PlayoffRounds;
}

/// <summary>A team's chances over many random schedules: share of games won, making the playoffs, winning the title.</summary>
public sealed record SeasonOdds(double WinPct, double PlayoffProbability, double TitleProbability);

/// <summary>
/// Plays a league season from fixed weekly scores. Rosters and weekly points are fixed by the draft and the real season, so the only luck
/// left is the schedule; averaging over many random schedules gives each team's odds with that luck taken out.
/// </summary>
public static class LeagueSeason
{
    /// <summary>
    /// Odds for every team. Schedule <c>s</c> depends only on <paramref name="seed"/> and <c>s</c>, so teams from different drafts of the same
    /// seed face the same schedules (common random numbers for paired comparisons).
    /// </summary>
    /// <param name="weekly">Weekly lineup points per team; index 0 of each array is week 1.</param>
    public static SeasonOdds[] Odds(IReadOnlyList<double[]> weekly, SeasonFormat format, int schedules, int seed)
    {
        var teams = weekly.Count;
        if (format.PlayoffTeams < 2 || format.PlayoffTeams > teams) throw new ArgumentException($"cannot seed {format.PlayoffTeams} playoff teams from {teams}");
        if (weekly.Any(w => w.Length < format.Weeks)) throw new ArgumentException($"a season of {format.Weeks} weeks needs weekly points for every week");

        var gameShare = new double[teams];
        var playoffs = new double[teams];
        var titles = new double[teams];
        for (var s = 0; s < schedules; s++)
        {
            var random = new Random(unchecked(seed * 100_003 + s));
            var (wins, games, pointsFor) = RegularSeason(weekly, format, random);
            var seeds = Enumerable.Range(0, teams).OrderByDescending(t => wins[t]).ThenByDescending(t => pointsFor[t]).Take(format.PlayoffTeams).ToList();
            for (var t = 0; t < teams; t++) gameShare[t] += games[t] == 0 ? 0 : wins[t] / games[t];
            foreach (var t in seeds) playoffs[t]++;
            titles[Playoffs(weekly, format, seeds)]++;
        }
        return Enumerable.Range(0, teams).Select(t => new SeasonOdds(gameShare[t] / schedules, playoffs[t] / schedules, titles[t] / schedules)).ToArray();
    }

    static (double[] Wins, int[] Games, double[] PointsFor) RegularSeason(IReadOnlyList<double[]> weekly, SeasonFormat format, Random random)
    {
        var teams = weekly.Count;
        var wins = new double[teams];
        var games = new int[teams];
        var pointsFor = new double[teams];
        var rounds = RoundRobin(teams, random);
        for (var week = 0; week < format.RegularSeasonWeeks; week++)
        {
            foreach (var (a, b) in rounds[week % rounds.Count])
            {
                games[a]++;
                games[b]++;
                if (weekly[a][week] > weekly[b][week]) wins[a]++;
                else if (weekly[b][week] > weekly[a][week]) wins[b]++;
                else { wins[a] += 0.5; wins[b] += 0.5; }
            }
            for (var t = 0; t < teams; t++) pointsFor[t] += weekly[t][week];
        }
        return (wins, games, pointsFor);
    }

    /// <summary>Everyone plays everyone once per cycle (circle method), with the team order and the order of the rounds shuffled; an odd league gets a bye each round.</summary>
    static List<(int, int)[]> RoundRobin(int teams, Random random)
    {
        var order = Enumerable.Range(0, teams).OrderBy(_ => random.Next()).Select(t => (int?)t).ToList();
        if (order.Count % 2 == 1) order.Add(null);
        var rounds = new List<(int, int)[]>();
        for (var round = 0; round < order.Count - 1; round++)
        {
            var pairs = new List<(int, int)>();
            for (var i = 0; i < order.Count / 2; i++)
                if (order[i] is { } a && order[^(i + 1)] is { } b) pairs.Add((a, b));
            rounds.Add([.. pairs]);
            order.Insert(1, order[^1]);                  // rotate everyone but the first team one place
            order.RemoveAt(order.Count - 1);
        }
        return rounds.OrderBy(_ => random.Next()).ToList();
    }

    /// <summary>Champion of a single-elimination bracket: the best remaining seed plays the worst each round; a tie goes to the better seed.</summary>
    static int Playoffs(IReadOnlyList<double[]> weekly, SeasonFormat format, List<int> seeds)
    {
        var alive = seeds.ToList();
        for (var round = 0; alive.Count > 1; round++)
        {
            var week = format.RegularSeasonWeeks + round;
            var byes = round == 0 ? format.Byes : 0;
            var playing = alive.Skip(byes).ToList();
            var next = alive.Take(byes).ToList();
            for (var i = 0; i < playing.Count / 2; i++)
            {
                int high = playing[i], low = playing[^(i + 1)];
                next.Add(weekly[low][week] > weekly[high][week] ? low : high);
            }
            alive = next.OrderBy(t => seeds.IndexOf(t)).ToList();
        }
        return alive[0];
    }
}
