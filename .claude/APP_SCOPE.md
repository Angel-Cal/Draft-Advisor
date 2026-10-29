# DraftBot App Scope (version 1)

Agreed with the user 2026-10-28, on branch `app-build`. The target is `mockup/` (rules and implied engine work in `APP_DESIGN.md`). Nothing below is built yet.

## Decisions

- **Platform:** Windows only. WPF window hosting a BlazorWebView (the roadmap's stack); the mockup's HTML/CSS ports to Razor components.
- **Build order:** engine advice call first, then the app on a practice draft with no network, then Sleeper.
- **Version 1 leaves out** the screens and panels marked Planned: drafter tendencies, the pick-log panel, the "four receivers in a row" run sentence. Picks are still recorded silently to a local file so those features can come later (roadmap defers run detection to Aug 2027).
- **Also out of version 1:** half-PPR and standard scoring (need the Phase 3 retrain), the installer and auto-update (Phase 6), and manual entry for ESPN/Yahoo mock drafts (it is mostly for mock drafts, which cannot be done until the offseason; the Sleeper client's manual pick fallback stays).
- **Layout:** the Sleeper client is its own project, separate from Core and Desktop.

## What gets created

| Piece | Where | Notes |
|---|---|---|
| Advice call | `DraftBot.Core` | One result for the draft screen: top 5, four position tiles (top player, cost of waiting, two fallbacks with survival), "Past the wall" list, tags with hover text, replacement levels. Includes the `Explainer` changes in `APP_DESIGN.md` section 4 |
| Sleeper client | new project | user, leagues, draft, picks polling; league rules to `LeagueSettings`; Sleeper player to GSIS id mapping (verify the ids exist for veterans, name+team for the rest); live / stale / disconnected states; manual pick entry fallback |
| Desktop app | new `DraftBot.Desktop` | Five screens, state service that recomputes advice after each pick, saved settings, timer, practice-draft mode with a visible "Practice" marker |
| Pick log | Desktop | append-only local file, no UI in version 1 |
| Projections bundling | Desktop | `data/` is gitignored, so the live file needs a defined way into the app |

## Milestones (each ends with something checkable)

1. **Advice call + Explainer changes. DONE 2026-10-28.** `DraftAdvisor.Advise` in Core, 205 tests passing. Run on the mockup's draft state it reproduces the mockup: Swift first with the same three
   tags, RB cost 9.5 / QB 3.7 / WR and TE 0, the same likely-to-last players and percentages, and the same three "past the wall" players (after limiting that list to slight reaches, 1.5 sigma).
   One call takes about 1-2 ms.
2. **Desktop shell + Draft screen on a practice draft. DONE 2026-10-28.** Two new projects: `DraftBot.App` (Razor class library: the Draft screen, shared components, `PracticeDraft`, `RosterView`,
   the stylesheet ported from the mockup) and `DraftBot.Desktop` (WPF window hosting a BlazorWebView, package `Microsoft.AspNetCore.Components.WebView.Wpf` 9.0.120). The app starts a practice draft from slot 5 of 12,
   the simulator's opponent bots pick for the other eleven teams, clicking Draft plays on to the next turn, and a finished draft shows the user's picks. Checks: 212 tests pass (7 new: practice draft rules, a full
   draft to the end, roster card layout, rendering); the Draft screen rendered from the mockup's draft state matches `mockup/renders/2-live-draft.png` (same numbers, tags and layout; the tiles come out in the
   mockup's order); the real app was launched, drew the screen with a ticking clock, and was closed.
   Added at the user's request after trying it: a Pause/Resume button in the header (practice drafts only, for testing). Pausing freezes the pick clock, shows a grey "Paused" tag and disables the Draft buttons.
   Not done in this step: Players and Board are greyed-out tabs, there is no gear/Settings, the practice slot is fixed, the window size and display scaling were not tuned, and nothing was clicked by hand in the
   running app (the Draft button is covered by the tests, not by a manual run).
3. **Players, Board, Settings, first-run** (Sleeper stubbed). Check: each screen against its render.
4. **Sleeper client.** Check: replay one of the user's finished drafts pick by pick through the client, then a live poll.
5. **Bundling the projections file**, then Phase 6 packaging later.

## How to run

`dotnet run --project csharp/src/DraftBot.Desktop` from the repo root. It needs `data/processed/projections_2026_v1.json` (found by walking up from the program's folder) or the path in the environment
variable `DRAFTBOT_PROJECTIONS`. `DraftBot.App` references `DraftBot.Sim` for the opponent bots and draft rules; if that coupling gets in the way, move `OpponentBot` and `DraftRules` into Core.

## Next session

First the reach-cost experiment (full plan in `STATUS.md`, hand-off 2026-10-28 evening), because it decides which players get recommendation cards; then milestone 3.

## Open

