using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class MockDraftTests
{
    static readonly SimSettings Settings = new(new LeagueSettings());

    static (bool Finished, string Output) Run(string script, int slot = 5, bool reveal = false, ProjectionFile? file = null)
    {
        var output = new StringWriter();
        var finished = new MockDraft(file ?? BacktestFile(), Settings, slot, seed: 0, reveal, new StringReader(script), output).Run();
        return (finished, output.ToString());
    }

    static string Enters(int count) => string.Concat(Enumerable.Repeat("\n", count));

    [Fact]
    public void Taking_the_top_recommendation_every_turn_finishes_the_draft_and_summarizes_it()
    {
        var (finished, text) = Run(Enters(16));

        Assert.True(finished);
        Assert.Contains("Draft complete", text);
        Assert.Contains("Your best lineup:", text);
        Assert.Contains("finish", text);
        foreach (var strategy in new[] { "adp", "vor", "recommender" }) Assert.Contains(strategy, text);
        Assert.Equal(16, text.Split("You are on the clock.").Length - 1);       // one turn per round
    }

    [Fact]
    public void Each_turn_shows_the_position_reasoning_and_the_scored_candidates()
    {
        var (_, text) = Run(Enters(16));

        Assert.Contains("which position?", text);
        Assert.Contains("demand", text);
        Assert.Contains("<-- chosen", text);
        Assert.Contains("0.5 x VOR-rank term", text);
        Assert.Contains("ADP would take:", text);
        Assert.Contains("VOR would take:", text);
    }

    [Fact]
    public void Quitting_abandons_the_draft()
    {
        var (finished, text) = Run("q\n");

        Assert.False(finished);
        Assert.Contains("Draft abandoned", text);
        Assert.DoesNotContain("Draft complete", text);
    }

    [Fact]
    public void Running_out_of_input_abandons_rather_than_hanging()
    {
        Assert.False(Run("").Finished);
    }

    [Fact]
    public void Actual_results_stay_hidden_until_the_end_unless_revealed()
    {
        var hidden = Run(Enters(16)).Output;
        var revealed = Run(Enters(16), reveal: true).Output;

        Assert.DoesNotContain(" scored ", hidden);
        Assert.Equal(16, revealed.Split(" scored ").Length - 1);
    }

    [Fact]
    public void A_unique_name_fragment_picks_that_player()
    {
        var last = BacktestFile().Players[^1].PlayerName;           // deepest player: the bots will not have taken him
        var (finished, text) = Run($"{last}\n" + Enters(15));

        Assert.True(finished);
        Assert.Contains(last, text.Substring(text.IndexOf("Draft complete", StringComparison.Ordinal)));
    }

    [Fact]
    public void An_ambiguous_name_lists_matches_and_takes_the_numbered_one()
    {
        var (_, text) = Run("WR1\n2\n" + Enters(15));

        Assert.Contains("Several match:", text);
        Assert.Contains("Draft complete", text);
    }

    [Fact]
    public void An_unknown_name_is_reported_and_asks_again()
    {
        var (finished, text) = Run("nobody-by-this-name\n" + Enters(16));

        Assert.True(finished);
        Assert.Contains("No available player matches 'nobody-by-this-name'", text);
    }

    [Fact]
    public void The_adp_and_vor_shortcuts_take_those_players()
    {
        var (finished, text) = Run("a\nv\n" + Enters(14));

        Assert.True(finished);
        Assert.Contains("Draft complete", text);
    }

    [Fact]
    public void A_live_file_without_actuals_is_refused()
    {
        var live = BacktestFile() with { Kind = "live", Players = BacktestFile().Players.Select(p => p with { ActualPpr = null }).ToList() };

        Assert.Throws<InvalidDataException>(() => Run("", file: live));
    }

    [Fact]
    public void The_slot_must_exist_in_the_league()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => Run("", slot: 12));
    }

    [Fact]
    public void Suggestions_the_simulators_roster_rules_would_block_are_marked()
    {
        // the unconstrained recommender keeps drafting quarterbacks; once the team holds two, the sim would refuse more
        var (_, text) = Run(Enters(16));

        Assert.Contains("blocked by the simulator's roster rules", text);
    }
}
