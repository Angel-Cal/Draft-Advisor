using DraftBot.Core;

namespace DraftBot.Sim;

/// <summary>
/// An interactive mock draft on a past season: you pick for one slot, simulated opponents (the same seeded bots the experiment
/// uses) pick for the rest. Each turn shows what the ported recommender would do and why; actual results stay hidden until the
/// end unless <c>reveal</c> is set.
/// </summary>
public sealed class MockDraft
{
    sealed record MyPick(int Round, int Overall, ValuedPlayer Player, bool TookTopRecommendation, PickRegret Regret);

    readonly ProjectionFile file;
    readonly SimSettings settings;
    readonly int slot;
    readonly int seed;
    readonly bool reveal;
    readonly TextReader input;
    readonly TextWriter output;
    readonly ReachSettings? reach;

    /// <param name="reach">If given, the recommender runs with the ADP-reach penalty and cap instead of as the plain baseline.</param>
    public MockDraft(ProjectionFile file, SimSettings settings, int slot, int seed, bool reveal, TextReader input, TextWriter output,
        ReachSettings? reach = null)
    {
        if (file.Players.Any(p => p.ActualPpr is null))
            throw new InvalidDataException("mock drafts need a backtest file with actual_ppr (the live file has none)");
        if (slot < 0 || slot >= settings.League.Teams)
            throw new ArgumentOutOfRangeException(nameof(slot), $"slot must be 1-{settings.League.Teams}");
        (this.file, this.settings, this.slot, this.seed, this.reveal, this.input, this.output, this.reach) = (file, settings, slot, seed, reveal, input, output, reach);
    }

    /// <summary>Runs the draft. False if the user quit before it finished.</summary>
    public bool Run()
    {
        var league = settings.League;
        var pool = Valuator.Value(file.Players, file.PositionRmse, league, new ValuationSettings(settings.TierGapRmse));
        var regret = new RegretCalculator(pool, league);
        var bots = Enumerable.Range(0, league.Teams).Select(t => t == slot ? null : OpponentBot.Create(pool, settings, seed, t)).ToArray();
        var state = new DraftState(pool, league);
        var recent = new List<string>();
        var mine = new List<MyPick>();

        output.WriteLine($"Mock draft: {file.Season} season, {league.Teams} teams, you are slot {slot + 1}, opponent seed {seed}.");
        output.WriteLine("Enter takes the recommender's #1. Also: 1-5, a (what ADP takes), v (what VOR takes), part of a name, q to quit.");

        while (!state.IsComplete)
        {
            var team = state.CurrentTeam;
            var legal = DraftRules.LegalPicks(state, team, settings);
            if (team != slot)
            {
                var pick = bots[team]!.Pick(legal);
                recent.Add($"{state.OverallPick + 1} {pick.Player.PlayerName} {pick.Position}");
                state.Draft(pick.Id);
                continue;
            }

            var turn = HumanTurn(state, legal, recent);
            if (turn is null)
            {
                output.WriteLine("Draft abandoned.");
                return false;
            }
            var chosen = turn.Value;
            recent.Clear();
            var pickRegret = regret.Evaluate(legal.Append(chosen.Player).Distinct().ToList(), chosen.Player, state.Round);
            mine.Add(new MyPick(state.Round, state.OverallPick + 1, chosen.Player, chosen.TookTop, pickRegret));
            if (reveal) output.WriteLine($"  -> {chosen.Player.Player.PlayerName} scored {chosen.Player.Player.ActualPpr:F0} points");
            state.Draft(chosen.Player.Id);
        }

        Summarize(state, pool, mine);
        return true;
    }

    (ValuedPlayer Player, bool TookTop)? HumanTurn(DraftState state, IReadOnlyList<ValuedPlayer> legal, List<string> recent)
    {
        var roster = state.Teams[slot];
        var choice = BaselineRecommender.ChoosePosition(state, slot, reach);
        var candidates = BaselineRecommender.SelectPlayers(choice.Position, state, slot, reach);
        var adpPick = new AdpStrategy().Pick(state, slot, legal);
        var vorPick = new VorStrategy().Pick(state, slot, legal);

        output.WriteLine();
        output.WriteLine(new string('=', 100));
        if (recent.Count > 0) output.WriteLine($"Since your last pick: {string.Join(", ", recent)}");
        output.WriteLine($"Round {state.Round}, pick {state.OverallPick + 1} overall. You are on the clock.");
        output.WriteLine("Your roster: " + string.Join("   ", Positions.All.Select(p =>
            $"{p}: {(roster.At(p).Count == 0 ? "-" : string.Join(", ", roster.At(p).Select(x => x.Player.PlayerName)))}")));
        var (needs, bench) = roster.GetNeeds();
        output.WriteLine($"Open starter slots: {(needs.Count == 0 ? "none" : string.Join(", ", needs))}.  Bench spots left: {bench}");

        if (reach is not null)
        {
            var pick = state.OverallPick + 1;
            output.WriteLine($"Reach control on: at pick {pick} one sigma is {reach.Sigma(pick):F1} picks; players with ADP past {pick + reach.CapSigmas * reach.Sigma(pick):F0} "
                             + $"({reach.CapSigmas:0.#} sigma) are out; each sigma past the pick costs {reach.Lambda:0.##} x z^2 in score"
                             + (reach.UseGapTerm ? "." : "; the ADP-gap term is off."));
        }
        output.WriteLine();
        output.WriteLine("Recommender, step 1: which position? (unmet league demand / players left in the position's best tier)");
        foreach (var s in choice.Scarcity)
            output.WriteLine($"  {s.Position}  demand {s.Demand,3} / supply {s.Supply,3} = {s.Value,5:F2}"
                             + (s.InjuryBoost ? "  (x1.2 injury boost)" : "") + (s.Considered ? "" : "   (not considered: no open slot)")
                             + (s.Position == choice.Position ? "   <-- chosen" : ""));

        output.WriteLine();
        output.WriteLine($"Recommender, step 2: best {choice.Position}s = 0.5 x VOR-rank term + 0.5 x ADP-gap term - injury risk" + (reach is null ? "" : " - reach penalty"));
        output.WriteLine($"  {"#",2} {"player",-22}{"team",-5}{"ADP",6}{"proj",6}{"VOR",6}{"VORrk",6}{"gap",6}{"tier",5}  {"inj",-4}{"rank",6}{"gap",6}{"risk",6}"
                         + (reach is null ? "" : $"{"reach",6}{"z",5}") + $"{"score",7}");
        for (var i = 0; i < candidates.Count; i++)
        {
            var c = candidates[i];
            var p = c.Player;
            output.WriteLine($"  {i + 1,2} {p.Player.PlayerName,-22}{p.Player.Team,-5}{p.Player.Adp,6:F0}{p.Player.ProjectedPpr,6:F0}{p.Vor,6:F0}"
                             + $"{p.VorRank,6:F0}{p.ValueGap,6:F0}{p.Tier,5}  {(p.Player.InjuryFlag ? "yes" : "-"),-4}"
                             + $"{c.RankTerm,6:F2}{c.GapTerm,6:F2}{(c.Penalty == 0 ? 0 : -c.Penalty),6:F2}"
                             + (reach is null ? "" : $"{(c.ReachPenalty == 0 ? 0 : -c.ReachPenalty),6:F2}{c.ReachSigmas,5:F1}") + $"{c.WeightedValue,7:F2}"
                             + (legal.Contains(p) ? "" : "   blocked by the simulator's roster rules"));
        }
        if (candidates.Count == 0) output.WriteLine($"  (no {choice.Position}s left; pick another way)");

        output.WriteLine();
        output.WriteLine($"  a  ADP would take: {Describe(adpPick)}");
        output.WriteLine($"  v  VOR would take: {Describe(vorPick)}");

        while (true)
        {
            output.Write("Your pick> ");
            var line = input.ReadLine();
            if (line is null) return null;
            line = line.Trim();

            if (line.Equals("q", StringComparison.OrdinalIgnoreCase)) return null;
            if (line == "" || line == "1")
            {
                if (candidates.Count > 0) return (candidates[0].Player, true);
                output.WriteLine("  The recommender has no candidates; choose a, v or a name.");
            }
            else if (int.TryParse(line, out var n) && n >= 2 && n <= candidates.Count)
                return (candidates[n - 1].Player, false);
            else if (line.Equals("a", StringComparison.OrdinalIgnoreCase)) return (adpPick, candidates.FirstOrDefault()?.Player == adpPick);
            else if (line.Equals("v", StringComparison.OrdinalIgnoreCase)) return (vorPick, candidates.FirstOrDefault()?.Player == vorPick);
            else
            {
                var matches = state.Available.Where(p => p.Player.PlayerName.Contains(line, StringComparison.OrdinalIgnoreCase)).Take(10).ToList();
                if (matches.Count == 0) output.WriteLine($"  No available player matches '{line}'.");
                else if (matches.Count == 1) return (matches[0], candidates.FirstOrDefault()?.Player == matches[0]);
                else
                {
                    output.WriteLine("  Several match:");
                    for (var i = 0; i < matches.Count; i++) output.WriteLine($"    {i + 1}. {Describe(matches[i])}");
                    output.Write("  Which one (number, or Enter to go back)> ");
                    var answer = input.ReadLine();
                    if (answer is null) return null;
                    if (int.TryParse(answer.Trim(), out var which) && which >= 1 && which <= matches.Count)
                        return (matches[which - 1], candidates.FirstOrDefault()?.Player == matches[which - 1]);
                }
            }
        }
    }

    void Summarize(DraftState state, IReadOnlyList<ValuedPlayer> pool, List<MyPick> mine)
    {
        var league = settings.League;
        var scores = state.Teams.Select(r => LineupScorer.Score(r, league)).ToList();
        var finish = 1 + scores.Count(s => s > scores[slot]);

        output.WriteLine();
        output.WriteLine(new string('=', 100));
        output.WriteLine("Draft complete. Your picks, with how they turned out:");
        output.WriteLine($"  {"rd",3}{"pick",5}  {"player",-22}{"pos",-4}{"ADP",6}{"proj",6}{"VOR",6}{"actual",7}  {"hindsight",10}{"foresight",10}  rec#1");
        foreach (var m in mine)
        {
            var p = m.Player;
            output.WriteLine($"  {m.Round,3}{m.Overall,5}  {p.Player.PlayerName,-22}{p.Position,-4}{p.Player.Adp,6:F0}{p.Player.ProjectedPpr,6:F0}{p.Vor,6:F0}"
                             + $"{p.Player.ActualPpr,7:F0}  {m.Regret.Actual,10:F0}{m.Regret.ProjectedVor,10:F0}  {(m.TookTopRecommendation ? "yes" : "")}");
        }
        output.WriteLine("  (hindsight / foresight = actual points / projected VOR given up versus the best legal player available)");

        output.WriteLine();
        output.WriteLine($"Your best lineup: {scores[slot]:F0} points, finish {finish} of {league.Teams}.");
        output.WriteLine("League: " + string.Join("  ", scores.Select((points, i) => (points, name: i == slot ? "YOU" : $"T{i + 1}"))
            .OrderByDescending(t => t.points).Select(t => $"{t.name} {t.points:F0}")));

        output.WriteLine();
        output.WriteLine("Same slot and opponents, but the strategy drafts the whole way:");
        var strategies = new List<IDraftStrategy> { new AdpStrategy(), new VorStrategy(), new RecommenderStrategy() };
        if (reach is not null) strategies.Add(new WindowedRecommenderStrategy("windowed", reach));
        foreach (var strategy in strategies)
        {
            var result = DraftSimulator.Run(pool, settings, slot, strategy, seed);
            output.WriteLine($"  {strategy.Name,-12}{result.Points,8:F0} points, finish {result.Finish}");
        }
    }

    static string Describe(ValuedPlayer p) =>
        $"{p.Player.PlayerName} {p.Position} ({p.Player.Team}, ADP {p.Player.Adp:F0}, proj {p.Player.ProjectedPpr:F0}, VOR {p.Vor:F0}, tier {p.Tier})";
}
