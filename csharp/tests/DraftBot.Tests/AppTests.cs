using DraftBot.App.Components;
using DraftBot.App.Services;
using DraftBot.Core;
using Microsoft.AspNetCore.Components;
using Microsoft.AspNetCore.Components.Web;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class AppTests
{
    static readonly LeagueSettings League = new();      // 12 teams, 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX, 8 bench

    static PracticeDraft Start(int slot = 4) => new(BacktestFile(), League, slot, seed: 1);

    static void DraftTheTopRecommendation(PracticeDraft draft) => Assert.True(draft.Draft(draft.Advice!.Recommended[0].Candidate.Player.Id));

    [Fact]
    public void A_practice_draft_plays_the_other_teams_until_it_is_my_turn()
    {
        var draft = Start(slot: 4);

        Assert.Equal(4, draft.State.History.Count);          // teams 1-4 have picked
        Assert.Equal(4, draft.State.CurrentTeam);
        Assert.Equal(5, draft.Advice!.Pick);
    }

    [Fact]
    public void Drafting_a_player_puts_him_on_my_roster_and_the_other_teams_play_on_to_my_next_turn()
    {
        var draft = Start();
        var pick = draft.Advice!.Recommended[0].Candidate.Player;
        var changed = 0;
        draft.Changed += () => changed++;

        Assert.True(draft.Draft(pick.Id));

        Assert.Contains(draft.State.Teams[4].Picks, p => p.Id == pick.Id);
        Assert.Equal(20, draft.Advice!.Pick);                // snake: pick 5, then 20 (slot 5 of 12)
        Assert.Equal(19, draft.State.History.Count);
        Assert.Equal(1, changed);
        Assert.Equal(5, draft.PickNumber(pick.Id));
        Assert.Equal("You", draft.TeamName(4));
        Assert.Equal("Team 1", draft.TeamName(0));
    }

    [Fact]
    public void Drafting_an_unknown_player_does_nothing()
    {
        var draft = Start();

        Assert.False(draft.Draft("nobody"));
        Assert.Equal(5, draft.Advice!.Pick);
        Assert.Equal(4, draft.State.History.Count);
    }

    [Fact]
    public void Pausing_stops_the_pick_clock_and_blocks_drafting_until_resumed()
    {
        var draft = Start();
        var changes = 0;
        draft.Changed += () => changes++;

        draft.Pause();
        var frozen = draft.ElapsedOnPick;
        Thread.Sleep(60);

        Assert.True(draft.IsPaused);
        Assert.Equal(frozen, draft.ElapsedOnPick);                 // the clock stands still
        Assert.False(draft.Draft(draft.Advice!.Recommended[0].Candidate.Player.Id));
        Assert.Equal(4, draft.State.History.Count);

        draft.Resume();

        Assert.False(draft.IsPaused);
        Assert.True(draft.ElapsedOnPick < frozen + TimeSpan.FromMilliseconds(50));          // the 60 ms paused do not count
        Assert.Equal(2, changes);
        DraftTheTopRecommendation(draft);
    }

    [Fact]
    public void A_full_practice_draft_ends_with_a_full_roster_and_no_more_advice()
    {
        var draft = Start();

        while (!draft.IsComplete) DraftTheTopRecommendation(draft);

        Assert.Null(draft.Advice);
        Assert.Equal(League.RosterSize, draft.State.Teams[4].Picks.Count);
        Assert.False(draft.Draft("anyone"));
    }

    [Fact]
    public void The_roster_card_fills_starting_slots_by_projection_then_flex_then_the_bench()
    {
        var roster = new Roster(League);
        foreach (var rb in new[] { 200, 190, 180, 170 }) roster.Add(Valued($"rb{rb}", Position.RB) with { Player = Player($"rb{rb}", Position.RB, rb) });
        roster.Add(Valued("qb1", Position.QB) with { Player = Player("qb1", Position.QB, 300) });
        roster.Add(Valued("qb2", Position.QB) with { Player = Player("qb2", Position.QB, 250) });
        roster.Add(Valued("wr1", Position.WR) with { Player = Player("wr1", Position.WR, 210) });
        var replacement = new Dictionary<Position, double> { [Position.QB] = 248, [Position.RB] = 139, [Position.WR] = 141, [Position.TE] = 129 };

        var view = RosterView.Build(roster, League, replacement);

        Assert.Equal(["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"], view.Starters.Select(s => s.Label));
        Assert.Equal(["qb1", "rb200", "rb190", "wr1"], view.Starters.Where(s => s.Player is not null && s.Label != "FLEX").Select(s => s.Player!.Id));
        Assert.Equal("rb180", view.Starters.Single(s => s.Label == "FLEX").Player!.Id);          // best RB/WR/TE not in a dedicated slot
        Assert.Equal(["rb170", "qb2"], view.Bench.Select(p => p.Id));                         // an extra QB never fills FLEX
        Assert.Equal(8, view.BenchSpots);
        Assert.Equal(141, view.Starters.First(s => s.Position == Position.WR && s.Player is null).Replacement);
        Assert.Equal(129, view.Starters.Single(s => s.Position == Position.TE).Replacement);
    }

    static async Task<string> Render(PracticeDraft draft)
    {
        var services = new ServiceCollection().AddLogging().AddSingleton(draft).BuildServiceProvider();
        await using var renderer = new HtmlRenderer(services, services.GetRequiredService<ILoggerFactory>());
        return await renderer.Dispatcher.InvokeAsync(async () => (await renderer.RenderComponentAsync<Root>(ParameterView.Empty)).ToHtmlString());
    }

    [Fact]
    public async Task The_draft_screen_shows_the_clock_the_band_the_cards_and_the_roster()
    {
        var html = await Render(Start());

        Assert.Contains("You are on the clock", html);
        Assert.Contains("Recommended for pick #5", html);
        Assert.Contains("Take now or wait until #20", html);
        Assert.Contains("Cost of waiting", html);
        Assert.Contains("Your roster", html);
        Assert.Contains("Practice draft", html);
        Assert.Equal(3, html.Split(">Draft</button>").Length - 1);          // one Draft button per card
        Assert.Contains("He fills an open starting", html);
    }

    [Fact]
    public async Task A_paused_draft_says_so_offers_resume_and_disables_the_draft_buttons()
    {
        var draft = Start();
        var running = await Render(draft);
        draft.Pause();

        var paused = await Render(draft);

        Assert.DoesNotContain("Paused", running);
        Assert.Contains(">Pause</button>", running);
        Assert.Contains("Paused", paused);
        Assert.Contains(">Resume</button>", paused);
        Assert.Equal(3, paused.Split("disabled").Length - 1);          // all three Draft buttons
    }

    [Fact]
    public async Task A_finished_practice_draft_shows_the_picks_instead_of_the_draft_screen()
    {
        var draft = Start();
        while (!draft.IsComplete) DraftTheTopRecommendation(draft);

        var html = await Render(draft);

        Assert.Contains("Practice draft complete", html);
        Assert.DoesNotContain("You are on the clock", html);
    }
}
