using System.Text.Json;
using DraftBot.Core;

namespace DraftBot.App.Services;

/// <summary>
/// Opens the practice draft the app starts with, or says why it cannot: no projections file, or one that does not load (truncated, malformed, wrong schema, unreadable).
/// The host shows the message and exits, so every startup ends in a running draft or a readable error, never an unhandled exception (STATE_MACHINES.md, ISSUE-2).
/// </summary>
public static class PracticeStartup
{
    public const string NotFound = "Could not find the projections file (projections_2026_v1.json). Set DRAFTBOT_PROJECTIONS to its path.";

    /// <summary>The draft from the projections file at <paramref name="path"/> (null when none was found), or the message to show instead.</summary>
    public static (PracticeDraft? Draft, string? Error) Open(string? path, LeagueSettings league, int slot, int seed)
    {
        if (path is null) return (null, NotFound);
        try
        {
            var file = ProjectionFile.Load(path);
            // the bots would run out of players mid-draft (STATE_MACHINES.md, invariant D5)
            var picks = league.Teams * league.RosterSize;
            if (file.Players.Count < picks)
                return (null, $"The projections file {path} has {file.Players.Count} players; a {league.Teams}-team draft needs at least {picks}.");
            return (new PracticeDraft(file, league, slot, seed), null);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
        {
            return (null, $"Could not read the projections file {path}:\n{e.Message}");
        }
    }
}
