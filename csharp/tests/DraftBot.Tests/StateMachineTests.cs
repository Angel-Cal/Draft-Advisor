#pragma warning disable BL0006          // the test renderer reads render tree frames to find a button's event handler, as the browser would
using System.Text.Json;
using System.Text.Json.Serialization;
using DraftBot.App.Components;
using DraftBot.App.Services;
using DraftBot.Core;
using Microsoft.AspNetCore.Components;
using Microsoft.AspNetCore.Components.RenderTree;
using Microsoft.AspNetCore.Components.Web;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

/// <summary>Regression tests for the invalid states and transitions in .claude/STATE_MACHINES.md, one region per issue.</summary>
public class StateMachineTests
{
    static readonly LeagueSettings League = new();

    /// <summary>The draft's clock: it stands still unless a test moves it, so the repeat guard and the pick clock are exact.</summary>
    readonly ManualTime time = new();

    PracticeDraft Start(int slot = 4) => new(BacktestFile(), League, slot, seed: 1, time);

    /// <summary>Waits a second (past the repeat guard), then drafts card <paramref name="card"/> (1 = 0).</summary>
    void TakeCard(PracticeDraft draft, int card = 0)
    {
        time.Advance(TimeSpan.FromSeconds(1));
        Assert.True(draft.Draft(draft.Advice!.Recommended[Math.Min(card, draft.Advice.Recommended.Count - 1)].Candidate.Player.Id, draft.Advice.Pick));
    }

    static async Task<string> Render(PracticeDraft draft)
    {
        var services = new ServiceCollection().AddLogging().AddSingleton(draft).BuildServiceProvider();
        await using var renderer = new HtmlRenderer(services, services.GetRequiredService<ILoggerFactory>());
        return await renderer.Dispatcher.InvokeAsync(async () => (await renderer.RenderComponentAsync<DraftScreen>(ParameterView.Empty)).ToHtmlString());
    }

    // ---- the session's invariants (sections 1-2) -------------------------------------------------------------------------------------------------------------------

    [Theory]
    [InlineData(0, 0)]
    [InlineData(4, 1)]
    [InlineData(11, 2)]
    public void Every_pick_of_a_full_draft_keeps_the_draft_and_session_invariants(int slot, int card)
    {
        var draft = Start(slot);
        var pool = draft.State.Available.Count + draft.State.History.Count;

        while (!draft.IsComplete)
        {
            var state = draft.State;
            Assert.Equal(slot, state.CurrentTeam);                                                   // P1
            Assert.Equal(state.OverallPick + 1, draft.Advice!.Pick);                                // P2
            Assert.Equal(state.NextPick(slot), draft.Advice.NextPick);
            Assert.Equal(state.OverallPick, state.History.Count);                                   // D1
            Assert.Equal(pool, state.Available.Count + state.History.Count);                        // D2
            Assert.Equal(state.History.Count, state.History.Select(h => h.Player.Id).Distinct().Count());
            Assert.Equal(state.History.Count, state.Teams.Sum(t => t.Picks.Count));                 // D3
            TakeCard(draft, card);
        }

        Assert.Null(draft.Advice);
        Assert.All(draft.State.Teams, t => Assert.Equal(League.RosterSize, t.Picks.Count));
    }

    // ---- ISSUE-1: one gesture, two picks ----------------------------------------------------------------------------------------------------------------------------

    /// <summary>A renderer whose display updates are never acknowledged: the browser has not applied them yet, so clicks still target the buttons it was showing.</summary>
    sealed class UnacknowledgedRenderer(IServiceProvider services) : Renderer(services, NullLoggerFactory.Instance)
    {
        public override Dispatcher Dispatcher { get; } = Dispatcher.CreateDefault();

        protected override void HandleException(Exception exception) => throw exception;

        protected override Task UpdateDisplayAsync(in RenderBatch batch) => new TaskCompletionSource().Task;

        public Task<int> Mount<T>() where T : IComponent => Dispatcher.InvokeAsync(async () =>
        {
            var id = AssignRootComponentId(InstantiateComponent(typeof(T)));
            await RenderRootComponentAsync(id);
            return id;
        });

        /// <summary>The click handlers of the Draft buttons, card 1 first, as the component last rendered them.</summary>
        public Task<List<ulong>> DraftButtons(int componentId) => Dispatcher.InvokeAsync(() =>
        {
            var frames = GetCurrentRenderTreeFrames(componentId);
            var handlers = new List<ulong>();
            for (var i = 0; i < frames.Count; i++)
            {
                var frame = frames.Array[i];
                if (frame.FrameType != RenderTreeFrameType.Element || frame.ElementName != "button") continue;
                var (isDraft, handler) = (false, 0UL);
                for (var j = i + 1; j < i + frame.ElementSubtreeLength && frames.Array[j].FrameType == RenderTreeFrameType.Attribute; j++)
                {
                    var attribute = frames.Array[j];
                    if (attribute.AttributeName == "class" && attribute.AttributeValue is string css && css.Contains("draft-btn")) isDraft = true;
                    if (attribute.AttributeName == "onclick") handler = attribute.AttributeEventHandlerId;
                }
                if (isDraft) handlers.Add(handler);
            }
            return handlers;
        });

        public Task Click(ulong handler) => Dispatcher.InvokeAsync(() => DispatchEventAsync(handler, new EventFieldInfo(), new MouseEventArgs()));
    }

    [Fact]
    public async Task A_click_sent_before_the_screen_showed_the_next_pick_does_not_draft_at_that_pick()
    {
        // slot 1 picks 24 and 25 back to back, so the second card at pick 24 is certainly still there at pick 25
        var draft = Start(slot: 0);
        TakeCard(draft);
        Assert.Equal(24, draft.Advice!.Pick);
        var renderer = new UnacknowledgedRenderer(new ServiceCollection().AddSingleton(draft).BuildServiceProvider());
        var buttons = await renderer.DraftButtons(await renderer.Mount<DraftScreen>());
        var secondCard = draft.Advice.Recommended[1].Candidate.Player;

        time.Advance(TimeSpan.FromSeconds(1));
        await renderer.Click(buttons[0]);          // card 1 at pick 24
        time.Advance(TimeSpan.FromSeconds(1));     // past the repeat guard, so only the pick number can refuse it
        await renderer.Click(buttons[1]);          // card 2, clicked before the browser showed pick 25

        Assert.Equal(25, draft.Advice!.Pick);
        Assert.Contains(secondCard, draft.State.Available);
        Assert.Equal(2, draft.State.Teams[0].Picks.Count);
    }

    [Fact]
    public void A_draft_request_for_another_pick_is_refused_even_when_the_player_is_still_there()
    {
        var draft = Start();
        var card = draft.Advice!.Recommended[0].Candidate.Player;
        time.Advance(TimeSpan.FromSeconds(1));

        Assert.False(draft.Draft(card.Id, draft.Advice.Pick - 1));
        Assert.False(draft.Draft(card.Id, draft.Advice.Pick + 1));
        Assert.Equal(4, draft.State.History.Count);
        Assert.True(draft.Draft(card.Id, draft.Advice.Pick));
    }

    [Fact]
    public void The_second_click_of_a_double_click_does_not_draft_at_the_next_pick()
    {
        var draft = Start();
        TakeCard(draft);                                   // the first click
        var next = draft.Advice!;
        var card = next.Recommended[0].Candidate.Player;

        time.Advance(TimeSpan.FromMilliseconds(300));       // the second click, on the next pick's card 1 in the same place
        Assert.False(draft.AcceptsPicks);
        Assert.False(draft.Draft(card.Id, next.Pick));
        Assert.Contains(card, draft.State.Available);

        time.Advance(TimeSpan.FromMilliseconds(200));       // the guard has passed: a deliberate click drafts
        Assert.True(draft.AcceptsPicks);
        Assert.True(draft.Draft(card.Id, next.Pick));
    }

    [Fact]
    public async Task The_draft_buttons_are_disabled_until_the_new_picks_advice_has_been_up_for_the_guard()
    {
        var draft = Start();
        var cards = Math.Min(3, draft.Advice!.Recommended.Count);

        var fresh = await Render(draft);
        time.Advance(PracticeDraft.DefaultRepeatGuard);
        var ready = await Render(draft);

        Assert.Equal(cards, fresh.Split(" disabled").Length - 1);
        Assert.DoesNotContain(" disabled", ready);
    }

    [Fact]
    public void Paused_time_does_not_count_toward_the_guard()
    {
        var draft = Start();
        draft.Pause();
        time.Advance(TimeSpan.FromSeconds(5));
        draft.Resume();

        Assert.False(draft.AcceptsPicks);
        time.Advance(PracticeDraft.DefaultRepeatGuard);
        Assert.True(draft.AcceptsPicks);
    }

    // ---- ISSUE-3: the last pick -------------------------------------------------------------------------------------------------------------------------------------

    [Fact]
    public async Task The_last_pick_says_it_is_the_last_instead_of_weighing_a_wait()
    {
        var draft = Start();
        while (draft.Advice!.NextPick is not null) TakeCard(draft);
        time.Advance(TimeSpan.FromSeconds(1));

        var html = await Render(draft);

        Assert.Contains("Your last pick", html);
        Assert.Contains("Take the best player left.", html);
        Assert.DoesNotContain("Take now or wait", html);
        Assert.DoesNotContain("Cost of waiting", html);
        Assert.DoesNotContain("#?", html);
        Assert.Contains(">Draft</button>", html);
        TakeCard(draft);
        Assert.True(draft.IsComplete);
    }

    [Fact]
    public async Task Every_pick_before_the_last_still_weighs_taking_now_against_the_next_pick()
    {
        var draft = Start();
        TakeCard(draft);

        var html = await Render(draft);

        Assert.Contains($"Take now or wait until #{draft.Advice!.NextPick}?", html);
        Assert.DoesNotContain("Your last pick", html);
    }

    // ---- ISSUE-2: startup -------------------------------------------------------------------------------------------------------------------------------------------

    static string TempFile(string text)
    {
        var path = Path.Combine(Path.GetTempPath(), $"draftbot-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, text);
        return path;
    }

    static string Json(ProjectionFile file) => JsonSerializer.Serialize(file,
        new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower, Converters = { new JsonStringEnumConverter() } });

    [Fact]
    public void Startup_without_a_projections_file_says_where_to_point_it()
    {
        var (draft, error) = PracticeStartup.Open(null, League, 4, 1);

        Assert.Null(draft);
        Assert.Equal(PracticeStartup.NotFound, error);
    }

    [Theory]
    [InlineData("{\"schema_version\": \"v1\", \"players\": [")]          // the export was still writing it
    [InlineData("not json")]
    public void Startup_with_a_file_that_does_not_load_reports_it_instead_of_crashing(string text)
    {
        var path = TempFile(text);

        var (draft, error) = PracticeStartup.Open(path, League, 4, 1);

        Assert.Null(draft);
        Assert.StartsWith($"Could not read the projections file {path}", error);
    }

    [Fact]
    public void Startup_with_another_schema_or_too_few_players_reports_it()
    {
        var other = PracticeStartup.Open(TempFile(ProjectionJson(schema: "v2")), League, 4, 1);
        var small = PracticeStartup.Open(TempFile(ProjectionJson()), League, 4, 1);          // 2 players, 192 picks

        Assert.Null(other.Draft);
        Assert.Contains("unsupported schema_version 'v2'", other.Error);
        Assert.Null(small.Draft);
        Assert.Contains("has 2 players; a 12-team draft needs at least 192", small.Error);
    }

    [Fact]
    public void Startup_with_a_good_file_opens_the_draft_at_the_users_first_pick()
    {
        var (draft, error) = PracticeStartup.Open(TempFile(Json(BacktestFile())), League, 4, 1);

        Assert.Null(error);
        Assert.Equal(5, draft!.Advice!.Pick);
    }

    // ---- ISSUE-4: the pick clock ------------------------------------------------------------------------------------------------------------------------------------

    /// <summary>A clock the test moves by hand: monotonic timestamps and a wall clock that can jump.</summary>
    sealed class ManualTime : TimeProvider
    {
        long ticks;
        DateTimeOffset wall = new(2026, 9, 1, 19, 0, 0, TimeSpan.Zero);

        public void Advance(TimeSpan by) => (ticks, wall) = (ticks + by.Ticks, wall + by);
        public void SetWallClockBack(TimeSpan by) => wall -= by;
        public override long TimestampFrequency => TimeSpan.TicksPerSecond;
        public override long GetTimestamp() => ticks;
        public override DateTimeOffset GetUtcNow() => wall;
    }

    [Fact]
    public async Task Setting_the_system_clock_back_during_a_pick_does_not_move_the_pick_clock()
    {
        var draft = Start();

        time.Advance(TimeSpan.FromSeconds(10));
        time.SetWallClockBack(TimeSpan.FromHours(1));

        Assert.Equal(TimeSpan.FromSeconds(10), draft.ElapsedOnPick);
        Assert.Contains("1:20</span>", await Render(draft));
    }

    [Fact]
    public void The_pick_clock_counts_only_time_running_and_restarts_at_each_pick()
    {
        var draft = Start();

        time.Advance(TimeSpan.FromSeconds(10));
        draft.Pause();
        time.Advance(TimeSpan.FromSeconds(30));
        draft.Resume();
        time.Advance(TimeSpan.FromSeconds(5));

        Assert.Equal(TimeSpan.FromSeconds(15), draft.ElapsedOnPick);
        TakeCard(draft);
        Assert.Equal(TimeSpan.Zero, draft.ElapsedOnPick);
    }
}
